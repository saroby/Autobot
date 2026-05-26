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
from pathlib import Path

QUARANTINE_THRESHOLD = -2  # effect_score <= -2 → quarantined
LEARNINGS_FILE = ".autobot/learnings.json"


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


def _state_path(project_root: Path) -> Path:
    return project_root / ".autobot" / "build-state.json"


def _load_state(project_root: Path) -> dict:
    p = _state_path(project_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def grade_build(project_root: Path, build_id: str | None = None) -> dict:
    """Inspect the just-finished build state and update learning effect scores.

    Heuristic per learning consumed in phase N:
      - phase N's outgoing gate passed AND no fix attempts were needed → "helped" (+1)
      - phase N's outgoing gate passed AFTER ≥1 build_fix_attempt → "neutral" (0)
      - phase N's outgoing gate failed → "hurt" (−1)
      - circuit breaker tripped in phase N where this learning was applied → "hurt" (−2)

    All updates are applied to learnings.json items in-place. Returns a summary.
    """
    data = _load(project_root)
    state = _load_state(project_root)
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
        build_attempts = sum(
            1 for entry in (phase_block.get("buildFixAttempts") or [])
        ) if isinstance(phase_block.get("buildFixAttempts"), list) else 0

        if breaker:
            outcome, delta = "hurt", -2
        elif status in ("failed", "skipped"):
            outcome, delta = "hurt", -1
        elif status in ("completed", "fallback") and build_attempts == 0:
            outcome, delta = "helped", 1
        elif status in ("completed", "fallback"):
            outcome, delta = "neutral", 0
        else:
            continue

        for rec in consumed_records:
            # Accept both legacy (str = agent name) and structured records.
            if isinstance(rec, str):
                learning_id = stable_id(phase_id, rec)
            elif isinstance(rec, dict):
                learning_id = rec.get("id") or stable_id(phase_id, rec.get("rule", rec.get("agent", "")))
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
            updated += 1
            summaries.append({
                "id": learning_id,
                "phase": phase_id,
                "outcome": outcome,
                "delta": delta,
                "effect_score": item["effect_score"],
            })

    _save(project_root, data)
    return {"updated": updated, "summaries": summaries}


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
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "grade":
        print(json.dumps(grade_build(proj, args.build_id), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "active":
        print(json.dumps(active(proj), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(quarantined(proj), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
