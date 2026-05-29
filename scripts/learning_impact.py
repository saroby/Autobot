#!/usr/bin/env python3
"""Track which `.autobot/learnings.json` items actually helped the build, and
quarantine ones that consistently hurt or did nothing.

Without this, every retrospective dumps more "lessons" into the file and the
next Phase 0 loads all of them — including the ones that *caused* problems
last run. With this, each learning gets:

    id              stable hash of its phase + rule body (so renames don't drift)
    effect_score    cumulative integer: +1 helped / 0 neutral / -1 hurt
    last_outcome    "helped" | "neutral" | "hurt" | "untried"
    applied_runs    list of build ids that consumed this learning
    last_signature  optional error signature this learning was supposed to prevent

CLI:
    learning_impact.py grade --build-id <id> --project-dir .
        Read the build's gate results vs. `phases.<N>.learningsConsumed` and
        update each consumed learning's effect_score / last_outcome.
    learning_impact.py active --project-dir .
        Print learnings.json with quarantined items (effect_score <= -2)
        filtered out — Phase 0 bootstrap should consume this.
    learning_impact.py quarantined --project-dir .
        Print the list of quarantined learning ids (operator visibility).

This module is import-safe (no spec dependency) so retrospective / orchestrator
can call it directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_store import state_file_for, try_load_state  # noqa: E402

QUARANTINE_THRESHOLD = -2  # effect_score <= -2 → quarantined
LEARNINGS_FILE = ".autobot/learnings.json"
GLOBAL_LEARNINGS_REL = "autobot/learnings.json"  # under XDG_CONFIG_HOME or ~/.config


def _global_learnings_path() -> Path:
    """Return the host-wide learnings store. Honours XDG_CONFIG_HOME so the
    location follows the same convention as `~/.config/autobot/.env`."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / GLOBAL_LEARNINGS_REL


def _learnings_path(project_root: Path) -> Path:
    return project_root / LEARNINGS_FILE


def _load(project_root: Path) -> dict:
    path = _learnings_path(project_root)
    if not path.is_file():
        return {"patterns": {}, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "items" not in data:
            data["items"] = []
        return data
    except (json.JSONDecodeError, OSError):
        return {"patterns": {}, "items": []}


def _save(project_root: Path, data: dict) -> None:
    path = _learnings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_id(phase: str, rule_body: str) -> str:
    """Hash phase + first 200 chars of the rule body. Renames the headline
    without changing the underlying advice → same id."""
    raw = f"{phase}:{rule_body.strip()[:200]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _norm_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _propagate_to_common_errors(data: dict, rule_text: str, delta: int) -> int:
    """Apply ``delta`` to the effect_score of any ``patterns.common_build_errors``
    entry whose pattern/fix/prevention text matches ``rule_text``.

    This is the bridge that makes the RENDERED ``## Prevention Rules`` honor
    quarantine: render-active-learnings.py drops entries whose effect_score has
    fallen to QUARANTINE_THRESHOLD. Without it a prevention rule graded "hurt"
    in items[] kept being rendered into every future build's prompt — the
    primary prompt channel ignored quarantine entirely (the W2 defect). The
    match is best-effort text equality/containment: when an agent logs the exact
    prevention rule it applied via ``--rule`` the link is exact, and a miss is
    harmless (the items[]/context_pack channel still honors quarantine on its
    own). Returns the number of entries updated.
    """
    rule_n = _norm_text(rule_text)
    if not rule_n:
        return 0
    errors = data.get("patterns", {}).get("common_build_errors")
    if not isinstance(errors, list):
        return 0
    touched = 0
    for entry in errors:
        if not isinstance(entry, dict):
            continue
        prevention_n = _norm_text(entry.get("prevention", ""))
        fix_n = _norm_text(entry.get("fix", ""))
        haystack = " ".join((prevention_n, fix_n, _norm_text(entry.get("pattern", ""))))
        if rule_n == prevention_n or rule_n == fix_n or rule_n in haystack:
            entry["effect_score"] = int(entry.get("effect_score", 0) or 0) + delta
            touched += 1
    return touched


def grade_build(project_root: Path, build_id: str | None = None) -> dict:
    """Inspect the just-finished build state and update learning effect scores.

    Heuristic per learning consumed in phase N:
      - gate passed AND no fix attempts were needed (errorSignatureHistory
        empty) → "helped" (+1)
      - gate passed AFTER ≥1 build-fix attempt (errorSignatureHistory
        non-empty) → "neutral" (0)
      - phase N's outgoing gate failed → "hurt" (−1)
      - circuit breaker tripped in phase N where this learning was applied → "hurt" (−2)

    All updates are applied to learnings.json items in-place. Returns a summary.
    """
    data = _load(project_root)
    state = try_load_state(state_file_for(project_root))
    if not state:
        return {"updated": 0, "reason": "no_build_state"}

    items_by_id = {item.get("id"): item for item in data["items"] if isinstance(item, dict) and item.get("id")}
    updated = 0
    summaries: list[dict] = []
    phases = state.get("phases") or {}

    for phase_id, phase_block in phases.items():
        if not isinstance(phase_block, dict):
            continue
        consumed_records = phase_block.get("learningsConsumed") or []
        if not consumed_records:
            continue

        # Aggregate phase-level signals.
        status = phase_block.get("status")
        breaker = (phase_block.get("circuitBreaker") or {}).get("tripped") is True
        # Number of build-fix attempts in this phase = entries appended to
        # errorSignatureHistory (error_signature.record appends one per recorded
        # compile-error signature). The previous code read `buildFixAttempts`,
        # a key NO code ever writes — so the count was always 0, every completed
        # phase graded "helped" (+1), and the "neutral" branch was dead. This
        # uses the real signal so a phase that passed only after fix loops is
        # graded neutral, not credited as a clean win.
        history = phase_block.get("errorSignatureHistory")
        fix_attempts = len(history) if isinstance(history, list) else 0

        if breaker:
            outcome, delta = "hurt", -2
        elif status in ("failed", "skipped"):
            outcome, delta = "hurt", -1
        elif status in ("completed", "fallback") and fix_attempts == 0:
            outcome, delta = "helped", 1
        elif status in ("completed", "fallback"):
            outcome, delta = "neutral", 0
        else:
            continue

        # Prefer structured per-rule records when present so grading is
        # per-rule, not per-agent (the W4 defect was collapsing every rule an
        # agent applied into one stable_id(phase, agent) bucket). The bare
        # agent-name string is kept in state for the *_consumed_learnings gate,
        # but we don't also grade it when richer per-rule records exist — that
        # would double-count the phase outcome.
        records_to_grade = [r for r in consumed_records if isinstance(r, dict)] or consumed_records

        for rec in records_to_grade:
            # Accept both legacy (str = agent name) and structured records.
            if isinstance(rec, str):
                learning_id = stable_id(phase_id, rec)
                rule_text = ""
            elif isinstance(rec, dict):
                rule_text = rec.get("rule", "")
                learning_id = rec.get("id") or stable_id(phase_id, rule_text or rec.get("agent", ""))
            else:
                continue

            item = items_by_id.get(learning_id)
            if item is None:
                item = {
                    "id": learning_id,
                    "phase": phase_id,
                    "effect_score": 0,
                    "last_outcome": "untried",
                    "applied_runs": [],
                    "rule_preview": (rec if isinstance(rec, str) else rec.get("rule", ""))[:200],
                }
                data["items"].append(item)
                items_by_id[learning_id] = item

            item["effect_score"] = int(item.get("effect_score", 0)) + delta
            item["last_outcome"] = outcome
            runs = item.setdefault("applied_runs", [])
            if build_id and build_id not in runs:
                runs.append(build_id)
                runs[:] = runs[-10:]  # cap history
            # Mirror the outcome onto the rendered prevention-rule store so a
            # hurtful rule also drops out of active-learnings.md / phase files,
            # not only the items[]/context_pack channel (W2).
            if rule_text:
                _propagate_to_common_errors(data, rule_text, delta)
            updated += 1
            summaries.append({
                "id": learning_id,
                "phase": phase_id,
                "outcome": outcome,
                "delta": delta,
                "effect_score": item["effect_score"],
            })

    _save(project_root, data)

    # Promote graded learnings to the host-wide store so the next project's
    # bootstrap inherits the latest effect scores. Best-effort; cannot block
    # the retrospective if global write fails (e.g. read-only home).
    publish_summary: dict | None = None
    try:
        publish_summary = publish_project_to_global(project_root)
    except Exception:  # noqa: BLE001 — never crash grade on global publish
        publish_summary = None

    result: dict = {"updated": updated, "summaries": summaries}
    if publish_summary:
        result["global_publish"] = publish_summary
    return result


def active(project_root: Path) -> dict:
    """Return learnings.json with quarantined items filtered out."""
    data = _load(project_root)
    active_items = [
        item for item in data.get("items", [])
        if not isinstance(item, dict) or int(item.get("effect_score", 0)) > QUARANTINE_THRESHOLD
    ]
    return {
        "patterns": data.get("patterns", {}),
        "items": active_items,
    }


def _merge_items(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge two `items` lists by id. Incoming wins on id collision (more
    recent grade typically reflects the latest effect). Items without an id
    are kept verbatim from existing first, then appended from incoming."""
    by_id: dict[str, dict] = {}
    no_id: list[dict] = []
    for item in existing:
        if isinstance(item, dict) and item.get("id"):
            by_id[item["id"]] = item
        else:
            no_id.append(item)
    for item in incoming:
        if isinstance(item, dict) and item.get("id"):
            by_id[item["id"]] = item
        else:
            no_id.append(item)
    return list(by_id.values()) + no_id


def _merge_patterns(existing: dict, incoming: dict) -> dict:
    """Deep-merge two `patterns` dicts. For per-key entries with a numeric
    `frequency`, sum them; otherwise incoming overwrites."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return merged
    for cat, cat_val in incoming.items():
        if isinstance(cat_val, dict) and isinstance(merged.get(cat), dict):
            sub_merged = dict(merged[cat])
            for key, val in cat_val.items():
                if (isinstance(val, dict) and isinstance(sub_merged.get(key), dict)
                        and "frequency" in val and "frequency" in sub_merged[key]):
                    combined = dict(sub_merged[key])
                    try:
                        combined["frequency"] = int(sub_merged[key]["frequency"]) + int(val["frequency"])
                    except (TypeError, ValueError):
                        combined["frequency"] = val["frequency"]
                    # Preserve fix_summary etc. from incoming when present
                    for k, v in val.items():
                        if k != "frequency":
                            combined[k] = v
                    sub_merged[key] = combined
                else:
                    sub_merged[key] = val
            merged[cat] = sub_merged
        else:
            merged[cat] = cat_val
    return merged


def load_global() -> dict:
    """Read the host-wide learnings store. Returns an empty skeleton when
    absent or malformed — never raises, since cross-project enrichment must
    never block a build."""
    path = _global_learnings_path()
    if not path.is_file():
        return {"patterns": {}, "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"patterns": {}, "items": []}
    if not isinstance(data, dict):
        return {"patterns": {}, "items": []}
    data.setdefault("patterns", {})
    data.setdefault("items", [])
    return data


def merge_global_into_project(project_root: Path) -> dict:
    """Bootstrap-time enrichment: when a new project has no `.autobot/learnings.json`
    yet, seed it from the global store. When the project already has its own
    file, merge global entries in (project wins on id collisions so per-project
    grading isn't clobbered)."""
    glob = load_global()
    if not glob.get("items") and not glob.get("patterns"):
        return {"enriched": False, "reason": "no_global_learnings"}

    path = _learnings_path(project_root)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(glob, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"enriched": True, "mode": "seeded_from_global",
                "items": len(glob.get("items", []))}

    project = _load(project_root)
    merged_items = _merge_items(glob.get("items", []), project.get("items", []))
    merged_patterns = _merge_patterns(glob.get("patterns", {}), project.get("patterns", {}))
    project["items"] = merged_items
    project["patterns"] = merged_patterns
    _save(project_root, project)
    return {"enriched": True, "mode": "merged_with_existing",
            "items": len(merged_items)}


def publish_project_to_global(project_root: Path) -> dict:
    """Phase 7 hand-off: push project learnings up to the global store so the
    next project benefits. Project items overlay global items on id collision
    (latest grade is the truth)."""
    project = _load(project_root)
    glob = load_global()
    merged_items = _merge_items(glob.get("items", []), project.get("items", []))
    merged_patterns = _merge_patterns(glob.get("patterns", {}), project.get("patterns", {}))

    path = _global_learnings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"patterns": merged_patterns, "items": merged_items}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"published": True, "global_path": str(path),
            "items": len(merged_items)}


def quarantined(project_root: Path) -> list[dict]:
    data = _load(project_root)
    return [
        {
            "id": item.get("id"),
            "phase": item.get("phase"),
            "effect_score": item.get("effect_score"),
            "last_outcome": item.get("last_outcome"),
            "rule_preview": item.get("rule_preview"),
        }
        for item in data.get("items", [])
        if isinstance(item, dict) and int(item.get("effect_score", 0)) <= QUARANTINE_THRESHOLD
    ]


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_g = sub.add_parser("grade")
    p_g.add_argument("--project-dir", default=".")
    p_g.add_argument("--build-id", default=None)
    p_a = sub.add_parser("active")
    p_a.add_argument("--project-dir", default=".")
    p_q = sub.add_parser("quarantined")
    p_q.add_argument("--project-dir", default=".")
    p_m = sub.add_parser("merge-global")
    p_m.add_argument("--project-dir", default=".")
    p_pub = sub.add_parser("publish-global")
    p_pub.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "grade":
        print(json.dumps(grade_build(proj, args.build_id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "active":
        print(json.dumps(active(proj), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-global":
        print(json.dumps(merge_global_into_project(proj), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "publish-global":
        print(json.dumps(publish_project_to_global(proj), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(quarantined(proj), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
