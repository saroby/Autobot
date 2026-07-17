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
        filtered out — consumed by run_summary.py. (Phase 0 bootstrap uses the
        load-learnings.sh merge-global + render path, not this subcommand.)
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
    or ``patterns.external_feedback`` entry whose rule text matches ``rule_text``.

    This is the bridge that makes the RENDERED prompt sections honor
    quarantine: render-active-learnings.py drops entries whose effect_score has
    fallen to QUARANTINE_THRESHOLD. Without it a prevention rule graded "hurt"
    in items[] kept being rendered into every future build's prompt — the
    primary prompt channel ignored quarantine entirely (the W2 defect; the
    ``## External Feedback`` section had the same writer-less dead check). The
    match is best-effort text equality/containment: when an agent logs the exact
    prevention rule it applied via ``--rule`` the link is exact, and a miss is
    harmless because items[] remains audit/grade data rather than a prompt
    channel. Returns the number of entries updated.
    """
    rule_n = _norm_text(rule_text)
    if not rule_n:
        return 0
    patterns = data.get("patterns", {})
    if not isinstance(patterns, dict):
        return 0
    # (entries, exact-match fields, containment-only fields) per prompt store.
    targets = (
        (patterns.get("common_build_errors"), ("prevention", "fix"), ("pattern",)),
        (patterns.get("external_feedback"), ("suggested_prevention_rule",), ("theme",)),
    )
    touched = 0
    for entries, exact_fields, extra_fields in targets:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            exact = [_norm_text(entry.get(f, "")) for f in exact_fields]
            haystack = " ".join(exact + [_norm_text(entry.get(f, "")) for f in extra_fields])
            if any(rule_n == e for e in exact if e) or rule_n in haystack:
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

    One vote per build per item: applied_runs is the idempotency ledger, so
    re-running the retrospective on the same build_id (fail → resume →
    complete) never re-adds a delta, and an item consumed in several phases
    of one build is graded by the first phase only.
    """
    data = _load(project_root)
    state = try_load_state(state_file_for(project_root))
    if not state:
        return {"updated": 0, "reason": "no_build_state"}

    # A build identity is what makes grading idempotent (applied_runs guard
    # below). A retrospective can run twice on the same build (fail → resume →
    # complete); without the guard every re-run re-added its delta.
    build_id = build_id or state.get("buildId")
    if not build_id:
        return {"updated": 0, "reason": "no_build_id"}

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
        # A phase that only completed because an operator overrode the breaker
        # or retry exhaustion is not evidence the learnings helped — demote
        # "helped" to "neutral". Defensive read: the field is written by the
        # transitions path and may be absent on older states.
        try:
            overrides = int(phase_block.get("operatorOverrides") or 0)
        except (TypeError, ValueError):
            overrides = 0

        if breaker:
            outcome, delta = "hurt", -2
        elif status in ("failed", "skipped"):
            outcome, delta = "hurt", -1
        elif status in ("completed", "fallback") and fix_attempts == 0 and overrides == 0:
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
            if item is None and rule_text:
                # External-feedback items are keyed stable_id("external", rule)
                # (external_feedback.py) while agents record with a phase key.
                # Re-keying at this grading chokepoint is what lets review-born
                # rules ever earn a score instead of minting an untried twin.
                external_item = items_by_id.get(stable_id("external", rule_text))
                if external_item is not None:
                    item = external_item
                    learning_id = external_item["id"]
            just_minted = False
            if item is None:
                if not rule_text:
                    # Never MINT items from rule-less records: bare agent-name
                    # strings (legacy + the gate-visible name cli.py always
                    # appends) and first-build sources:[] placeholders would
                    # otherwise promote strings like "architect" or fabricated
                    # "clean first build" rules into active learnings and
                    # leak to the global store. Existing items keep grading.
                    continue
                item = {
                    "id": learning_id,
                    "phase": phase_id,
                    "effect_score": 0,
                    "last_outcome": "untried",
                    "applied_runs": [],
                    "rule_preview": rule_text[:200],
                    # Provenance: this item was first SEEN at grade time, not
                    # loaded from the pre-build store — so it earns no score
                    # this pass (see the just_minted branch below).
                    "minted_by": "grade_build",
                }
                data["items"].append(item)
                items_by_id[learning_id] = item
                just_minted = True

            runs = item.setdefault("applied_runs", [])
            if build_id in runs:
                continue  # this build already voted on this item (idempotency)
            if just_minted:
                # A rule first reported AT grade time is recorded for audit but
                # must NOT self-certify: otherwise an agent could report any
                # fabricated rule and collect +1 in the same build. The item's
                # effect_score stays 0 until a LATER build applies the now
                # pre-existing rule and grades it for real. The build is still
                # banked (a same-build re-grade stays a no-op), and any EXISTING
                # pattern entry the rule matches still gets the outcome mirrored
                # — those entries are not agent-fabricated, so propagating to
                # them is safe and keeps the render-store quarantine honest.
                runs.append(build_id)
                runs[:] = runs[-10:]
                if rule_text:
                    _propagate_to_common_errors(data, rule_text, delta)
                summaries.append({
                    "id": learning_id,
                    "phase": phase_id,
                    "outcome": "minted",
                    "delta": 0,
                    "effect_score": 0,
                })
                continue
            item["effect_score"] = int(item.get("effect_score", 0)) + delta
            item["last_outcome"] = outcome
            runs.append(build_id)
            runs[:] = runs[-10:]  # cap history
            # Mirror the outcome onto the rendered prevention-rule store so a
            # hurtful rule also drops out of active-learnings.md / phase files.
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
    # AUTOBOT_NO_GLOBAL_PUBLISH=1 skips the publish entirely — the test suite
    # sets it (run_tests.sh / conftest.py) so grading fixtures can never leak
    # into the developer's real ~/.config/autobot/learnings.json again.
    publish_summary: dict | None = None
    if os.environ.get("AUTOBOT_NO_GLOBAL_PUBLISH") != "1":
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


def _merge_entry(old: dict, new: dict) -> dict:
    """Merge two pattern entries that describe the SAME recurring pattern.

    frequency takes max(old, new) — NOT the sum. The stores round-trip
    (global → project at bootstrap, project → global at publish), so after a
    bootstrap seed the project copy already CONTAINS the global count; summing
    on every hop compounded counts across round trips (the real store hit
    retry_exhaustion_recovery frequency=882). max() is idempotent across
    round trips and still grows when a project genuinely increments its local
    count. All other fields: incoming wins (latest narrative is the truth).
    """
    combined = dict(old)
    for k, v in new.items():
        if k == "frequency":
            continue
        if k == "source_apps" and isinstance(v, list) and isinstance(old.get(k), list):
            # external_feedback: the global store exists to spot CROSS-app
            # themes, so app provenance must union, not get clobbered by the
            # last publisher.
            combined[k] = old[k] + [app for app in v if app not in old[k]]
            continue
        combined[k] = v
    if "frequency" in old or "frequency" in new:
        try:
            combined["frequency"] = max(int(old.get("frequency", 0) or 0),
                                        int(new.get("frequency", 0) or 0))
        except (TypeError, ValueError):
            combined["frequency"] = new.get("frequency", old.get("frequency"))
    return combined


def _merge_list_patterns(existing: list, incoming: list, *, add_only: bool) -> list:
    """Merge two list-form pattern categories — the canonical learning-schema
    shape for common_build_errors / effective_architectures / deployment_tips.

    Entries match by normalized `pattern` text (reuses _norm_text, same key the
    quarantine propagation matches on), falling back to `theme` — the identity
    key of patterns.external_feedback entries. Matched entries merge via
    _merge_entry (or stay untouched in add_only mode); unmatched incoming
    entries append. This replaces the old wholesale `merged[cat] = cat_val`
    clobber that erased every global prevention rule on each publish.
    """

    def _entry_key(entry: dict) -> str:
        return _norm_text(entry.get("pattern", "") or entry.get("theme", ""))

    merged: list = []
    index: dict[str, int] = {}
    for entry in existing:
        if isinstance(entry, dict):
            key = _entry_key(entry)
            if key and key not in index:
                index[key] = len(merged)
        merged.append(entry)
    for entry in incoming:
        key = _entry_key(entry) if isinstance(entry, dict) else ""
        if key and key in index:
            if not add_only:
                merged[index[key]] = _merge_entry(merged[index[key]], entry)
            continue
        if entry in merged:  # keyless entries: dedupe by equality
            continue
        merged.append(entry)
        if key:
            index[key] = len(merged) - 1
    return merged


def _merge_patterns(existing: dict, incoming: dict, *, add_only: bool = False) -> dict:
    """Deep-merge two `patterns` dicts.

    add_only=False (publish direction, existing=global / incoming=project):
    matched entries merge with max-frequency + incoming-fields-win; unmatched
    incoming entries/keys are added; existing-only entries always survive.

    add_only=True (bootstrap direction, existing=project / incoming=global):
    project entries are kept verbatim — global contributes only entries/keys
    the project doesn't have yet. Re-merging global counts into the project and
    then publishing them back was the frequency-compounding bug (finding: dict
    frequencies grew Fibonacci-style across round trips).
    """
    merged = dict(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return merged
    for cat, cat_val in incoming.items():
        cur = merged.get(cat)
        if isinstance(cat_val, list) and isinstance(cur, list):
            merged[cat] = _merge_list_patterns(cur, cat_val, add_only=add_only)
        elif isinstance(cat_val, dict) and isinstance(cur, dict):
            sub_merged = dict(cur)
            for key, val in cat_val.items():
                if key not in sub_merged:
                    sub_merged[key] = val
                elif add_only:
                    continue  # project-first: keep the existing entry untouched
                elif (isinstance(val, dict) and isinstance(sub_merged[key], dict)
                        and "frequency" in val and "frequency" in sub_merged[key]):
                    sub_merged[key] = _merge_entry(sub_merged[key], val)
                else:
                    sub_merged[key] = val
            merged[cat] = sub_merged
        elif cat not in merged:
            merged[cat] = cat_val
        elif not add_only:
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
    # Project-first, add-only: global contributes only entries the project
    # doesn't have. Never re-sum/overwrite project counts on the inbound hop —
    # accumulation happens on the publish hop only (and idempotently, via max).
    merged_patterns = _merge_patterns(project.get("patterns", {}), glob.get("patterns", {}),
                                      add_only=True)
    project["items"] = merged_items
    project["patterns"] = merged_patterns
    _save(project_root, project)
    return {"enriched": True, "mode": "merged_with_existing",
            "items": len(merged_items)}


def _filter_unapproved_external(project: dict) -> dict:
    """External-feedback entries are untrusted user text until an operator
    approves them (data-level gate written by external_feedback.py approve).
    Filtering HERE — the single choke point every global publish goes through
    (feedback path AND Phase 7 grade) — is what makes the gate real instead of
    prose. Unapproved entries and their phase=="external" tracking items stay
    project-local. sample_quotes are stripped from published entries: quotes
    exist for the operator's approval judgement and are untrusted review text —
    they must not propagate cross-project once the theme is approved."""
    entries = project.get("patterns", {}).get("external_feedback")
    if not isinstance(entries, list):
        return project
    approved = [
        {k: v for k, v in e.items() if k not in ("sample_quotes", "_consumed_signals")}
        for e in entries if isinstance(e, dict) and e.get("approved") is True
    ]
    approved_ids = {
        stable_id("external", e.get("suggested_prevention_rule") or "")
        for e in approved
    }
    filtered = dict(project)
    filtered["patterns"] = dict(project.get("patterns", {}))
    filtered["patterns"]["external_feedback"] = approved
    filtered["items"] = [
        item for item in project.get("items", [])
        if not (isinstance(item, dict) and item.get("phase") == "external"
                and item.get("id") not in approved_ids)
    ]
    return filtered


GLOBAL_ITEMS_CAP = 500


def _cap_global_items(items: list) -> list:
    """Best-effort size ceiling for the monotonically-growing global items[].

    Over the cap, evict oldest-first (list order ≈ append age) only the items
    that are quarantined tombstones no build ever consumed (empty applied_runs,
    untried/hurt). Live or graded items are NEVER dropped — quarantine scores
    must keep travelling cross-project so new projects don't re-learn a bad
    rule from zero. If tombstones alone can't reach the cap, the list stays
    over it rather than losing real learnings."""
    if len(items) <= GLOBAL_ITEMS_CAP:
        return items

    def evictable(item: object) -> bool:
        return (isinstance(item, dict)
                and int(item.get("effect_score", 0) or 0) <= QUARANTINE_THRESHOLD
                and not item.get("applied_runs")
                and item.get("last_outcome") in ("untried", "hurt"))

    overflow = len(items) - GLOBAL_ITEMS_CAP
    kept: list = []
    for item in items:
        if overflow > 0 and evictable(item):
            overflow -= 1
            continue
        kept.append(item)
    return kept


def publish_project_to_global(project_root: Path) -> dict:
    """Phase 7 hand-off: push project learnings up to the global store so the
    next project benefits. Project items overlay global items on id collision
    (latest grade is the truth)."""
    project = _filter_unapproved_external(_load(project_root))
    glob = load_global()
    merged_items = _cap_global_items(
        _merge_items(glob.get("items", []), project.get("items", [])))
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
