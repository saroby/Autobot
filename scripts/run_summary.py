#!/usr/bin/env python3
"""Generate `run-summary.json` and `run-summary.md` for every Autobot build —
success or failure — so the operator (or the next /autobot:resume) can read
one screen and know what happened.

Inputs (all under the project root):
    .autobot/build-state.json
    .autobot/build-log.jsonl
    .autobot/phase-5/runtime-smoke/screenshot.png   (optional)
    .autobot/learnings.json                         (optional)

Output:
    artifacts/<buildId>/run-summary.json
    artifacts/<buildId>/run-summary.md

Symlink:
    artifacts/latest → <buildId>/                   (always updated, atomic)

Sections in the markdown:
    - Header: app name, build id, started/ended, duration, status
    - Phase table: status / duration / retries / metadata flags
    - Build attempts: every xcodebuild attempt + signature hash
    - Gate ledger: every gate_pass / gate_fail in order
    - Quality signals: runtime smoke, visual contract, metadata readiness, axiom audit, peer review
    - Learnings ledger: applied this run + outcome
    - Failure footprint (if status != completed): latest primary failure, recent reasons, resume command
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from spec_loader import load_spec


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # ISO 8601 with trailing Z
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _epoch_ts(value: object) -> float | None:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _events_for_current_build(state: dict, events: list[dict]) -> list[dict]:
    """Return only events attributable to the current state build.

    New rows are explicitly buildId-scoped. Legacy rows are accepted only when
    both the run start and event timestamp are parseable and the row occurred on
    or after this run started. Missing/invalid timestamps never cross the legacy
    boundary; silently importing all unscoped history would be less compatible
    than it is misleading.
    """
    build_id = state.get("buildId")
    if build_id in (None, ""):
        return []
    build_id = str(build_id)
    started_at = _epoch_ts(state.get("startedAt"))

    scoped: list[dict] = []
    for entry in events:
        event_build_id = entry.get("buildId")
        if event_build_id not in (None, ""):
            if str(event_build_id) == build_id:
                scoped.append(entry)
            continue

        event_ts = _epoch_ts(entry.get("ts"))
        if started_at is not None and event_ts is not None and event_ts >= started_at:
            scoped.append(entry)
    return scoped


def _phase_durations(events: list[dict]) -> dict[str, dict]:
    per: dict[str, dict] = defaultdict(lambda: {"start": None, "end": None})
    for entry in events:
        phase = entry.get("phase")
        if phase is None:
            continue
        ev = entry.get("event")
        ts = _parse_ts(entry.get("ts", ""))
        if ts is None:
            continue
        bucket = per[str(phase)]
        if ev == "start" and bucket["start"] is None:
            bucket["start"] = ts
        if ev in {"complete", "fallback", "skip", "fail"} or ev.startswith("gate_"):
            bucket["end"] = ts
    out: dict[str, dict] = {}
    for phase, bucket in per.items():
        start = bucket["start"]
        end = bucket["end"]
        duration = round((end - start).total_seconds(), 1) if start and end else None
        out[phase] = {
            "startedAt": start.isoformat() if start else None,
            "endedAt": end.isoformat() if end else None,
            "durationSeconds": duration,
        }
    return out


def _phase_ledger(state: dict, events: list[dict], spec: dict) -> dict[str, dict]:
    durations = _phase_durations(events)
    state_phases = state.get("phases") or {}
    spec_phases = spec.get("phases") or {}
    event_fix_attempts: dict[str, int] = defaultdict(int)
    for entry in events:
        if entry.get("event") == "build_fix_attempt" and entry.get("phase") is not None:
            event_fix_attempts[str(entry["phase"])] += 1

    phase_ids = set(durations) | {
        str(pid) for pid, block in state_phases.items() if isinstance(block, dict)
    }
    out: dict[str, dict] = {}
    for phase_id in phase_ids:
        block = state_phases.get(phase_id) or {}
        phase_spec = spec_phases.get(phase_id) or {}
        history = block.get("errorSignatureHistory")
        history_attempts = len(history) if isinstance(history, list) else 0
        fix_attempts = max(history_attempts, event_fix_attempts.get(phase_id, 0))
        info = dict(durations.get(phase_id) or {
            "startedAt": block.get("startedAt"),
            "endedAt": block.get("completedAt") or block.get("failedAt"),
            "durationSeconds": None,
        })
        info.update({
            "status": block.get("status"),
            "retryCount": int(block.get("retryCount", 0) or 0),
            "maxRetry": phase_spec.get("maxRetry"),
            "error": block.get("error"),
            "buildFixAttempts": fix_attempts,
            "operatorOverrides": int(block.get("operatorOverrides", 0) or 0),
        })
        out[phase_id] = info
    return out


def _gate_ledger(events: list[dict]) -> list[dict]:
    ledger: list[dict] = []
    for entry in events:
        ev = entry.get("event")
        if ev not in {"gate_pass", "gate_fail"}:
            continue
        ledger.append({
            "ts": entry.get("ts"),
            "event": ev,
            "phase": entry.get("phase"),
            "detail": entry.get("detail"),
        })
    return ledger


def _build_attempts(events: list[dict]) -> list[dict]:
    attempts: list[dict] = []
    for entry in events:
        ev = entry.get("event")
        if ev in {"build_attempt", "build_fix_attempt", "build_fix_loop_exhausted"}:
            attempts.append({
                "ts": entry.get("ts"),
                "event": ev,
                "phase": entry.get("phase"),
                "detail": entry.get("detail"),
            })
    return attempts


def _failure_footprint(state: dict, events: list[dict]) -> dict:
    failed: list[dict] = []
    for entry in events:
        if entry.get("event") in {"fail", "gate_fail", "circuit_open"}:
            failed.append({
                "ts": entry.get("ts"),
                "event": entry.get("event"),
                "phase": entry.get("phase"),
                "detail": entry.get("detail"),
            })
    failed = [
        item
        for _, item in sorted(
            enumerate(failed),
            key=lambda pair: (
                _epoch_ts(pair[1].get("ts"))
                if _epoch_ts(pair[1].get("ts")) is not None
                else float("-inf"),
                pair[0],
            ),
            reverse=True,
        )
    ]
    primary_failure = failed[0] if failed else None
    failed_phase = None
    for pid, block in (state.get("phases") or {}).items():
        if isinstance(block, dict) and block.get("status") == "failed":
            failed_phase = str(pid)
            break
    if failed_phase is None and primary_failure and primary_failure.get("phase") is not None:
        failed_phase = str(primary_failure["phase"])
    resume_hint = f"/autobot:resume {failed_phase}" if failed_phase else "/autobot:resume"
    return {
        "events": failed[:5],
        "primaryFailure": primary_failure,
        "resumeCommand": resume_hint,
        "failedPhase": failed_phase,
    }


def _quality_signals(state: dict) -> dict:
    phases = state.get("phases") or {}
    p3 = phases.get("3") or {}
    p5 = phases.get("5") or {}
    p7 = phases.get("7") or {}
    p5_metadata = p5.get("metadata") or {}
    p7_metadata = p7.get("metadata") or {}
    axiom_critical = p5_metadata.get("axiom_critical_audit")
    legacy_axiom = p5_metadata.get("axiomAudit") or p7_metadata.get("axiomAudit")
    return {
        "scaffoldBuild": (p3.get("metadata") or {}).get("scaffoldBuild"),
        "runtimeSmoke": p5_metadata.get("runtimeSmoke"),
        "visualContract": p5_metadata.get("visualContract"),
        "visualJudge": p5_metadata.get("visualJudge"),
        "metadataReadiness": p5_metadata.get("metadataReadiness"),
        "axiomCriticalAudit": axiom_critical,
        # Compatibility alias for consumers of the pre-schema summary. New
        # consumers should prefer the explicit critical/health fields.
        "axiomAudit": axiom_critical or legacy_axiom,
        "axiomHealthCheck": p7_metadata.get("axiom_health_check"),
        "peerReview": p5_metadata.get("peerReview"),
    }


def _learnings_summary(project_root: Path) -> dict:
    try:
        from learning_impact import active, quarantined
    except ImportError:
        return {}
    return {
        "activeCount": len(active(project_root).get("items", [])),
        "quarantined": quarantined(project_root),
    }


def _coverage(project_root: Path) -> dict:
    """Capability-coverage report — makes the feature's limits loud, not silent.
    Fail-safe: a missing module or any error degrades to an empty dict so summary
    generation never breaks."""
    try:
        import capability_coverage
        return capability_coverage.assess(project_root)
    except Exception:
        return {}


def _overall_status(state: dict) -> str:
    phases = state.get("phases") or {}
    statuses = [b.get("status") for b in phases.values() if isinstance(b, dict)]
    if not statuses:
        # Missing/corrupt build-state must not report as a completed run.
        return "unknown"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s is None for s in statuses):
        # A phase block present but carrying no status is indeterminate — the
        # same "not enough info to call it done" case as an empty phases dict.
        # Report unknown rather than laundering a missing status into
        # "completed" (the prior `or s is None` did exactly that).
        return "unknown"
    if all(s in {"completed", "fallback", "skipped"} for s in statuses):
        return "completed"
    return "in_progress"


def _gate56_findings(state: dict) -> tuple[list[dict], list[dict]]:
    """Return (failed, degraded) check findings from gate 5->6's recorded
    evidence, each as {check, message}. Lets the badge name the ACTUAL reason
    (e.g. visual_contract screen-fill unmet) instead of a hardcoded
    "axe unavailable" — so "verified-and-bad" is never laundered as "missing tool".
    """
    gate = (state.get("gates", {}) or {}).get("5->6") or {}
    groups = (gate.get("detail") or {}).get("checks") or []
    failed: list[dict] = []
    degraded: list[dict] = []
    for grp in groups:
        if not isinstance(grp, dict) or grp.get("passed"):
            continue
        msgs = [
            str(sc.get("message"))
            for sc in (grp.get("sub_checks") or [])
            if isinstance(sc, dict) and not sc.get("passed") and sc.get("message")
        ]
        finding = {"check": grp.get("check"), "message": ("; ".join(msgs))[:240] or grp.get("check")}
        (degraded if grp.get("degraded") else failed).append(finding)
    return failed, degraded


def _functional_verification(state: dict) -> dict:
    """Derive the shipping-verification badge from gate 5->6's recorded verdict.

    badge:
      VERIFIED   — gate 5->6 status == 'passed' (functional flows ran + passed)
      DEGRADED   — gate 5->6 status == 'degraded' (a degradable check could not run)
      UNVERIFIED — gate 5->6 status is soft_failed/failed/absent (a check FAILED,
                   e.g. visual_contract screen-fill unmet — verified-and-bad)
    Only VERIFIED is shippable. This mirrors check_functional_verification_passed.

    `failedChecks` / `degradedChecks` carry the ACTUAL non-green checks so the
    reason is honest: a tool-absence DEGRADE and a quality FAIL no longer collapse
    into one hardcoded "install axe" message.
    """
    status = (state.get("gates", {}).get("5->6") or {}).get("status")
    if status == "passed":
        badge = "VERIFIED"
    elif status == "degraded":
        badge = "DEGRADED"
    else:
        badge = "UNVERIFIED"
    failed, degraded = _gate56_findings(state)
    return {
        "badge": badge,
        "gate56Status": status,
        "shippable": badge == "VERIFIED",
        "failedChecks": failed,
        "degradedChecks": degraded,
    }


def build_summary(project_root: Path) -> dict:
    state = _load_json(project_root / ".autobot" / "build-state.json")
    events = _events_for_current_build(
        state,
        _load_jsonl(project_root / ".autobot" / "build-log.jsonl"),
    )
    spec = load_spec()

    summary = {
        "schemaVersion": 1,
        "buildId": state.get("buildId"),
        "appName": state.get("appName"),
        "displayName": state.get("displayName"),
        "bundleId": state.get("bundleId"),
        "startedAt": state.get("startedAt"),
        "environment": state.get("environment"),
        "status": _overall_status(state),
        "functionalVerification": _functional_verification(state),
        "coverage": _coverage(project_root),
        "phases": _phase_ledger(state, events, spec),
        "gateLedger": _gate_ledger(events),
        "buildAttempts": _build_attempts(events),
        "qualitySignals": _quality_signals(state),
        "learnings": _learnings_summary(project_root),
        "failureFootprint": _failure_footprint(state, events),
    }
    return summary


_BADGE_BANNER = {
    "VERIFIED": "> ✅ **VERIFIED** — functional flows passed. Shippable.",
    "DEGRADED": "> ⚠️ **DEGRADED — functional UNVERIFIED.** Phases completed but the "
                "flows could not run (simulator/axe/xcodebuild unavailable). "
                "**NOT shippable** — `/autobot:testflight` will refuse this build.",
    "UNVERIFIED": "> ❌ **UNVERIFIED** — no clean functional verification on record. "
                  "**NOT shippable** — re-run Phase 5 (`/autobot:resume 5`).",
}


def render_markdown(summary: dict) -> str:
    fv = summary.get("functionalVerification") or {}
    badge = fv.get("badge", "UNVERIFIED")
    phase_status = summary.get("status")

    lines: list[str] = []
    lines.append(f"# {summary.get('displayName') or summary.get('appName') or 'Autobot Build'} — Run Summary")
    lines.append("")
    # Lead with the shipping-verification verdict so the first thing a reader
    # sees reflects shippability — never let a bare phase-rollup "completed"
    # stand in for "verified". (A DEGRADED build has completed phases but is
    # not shippable; surfacing only the phase status here would mislead.)
    lines.append(_BADGE_BANNER.get(badge, _BADGE_BANNER["UNVERIFIED"]))
    lines.append("")
    lines.append(f"- **buildId**: `{summary.get('buildId')}`")
    lines.append(f"- **bundleId**: `{summary.get('bundleId') or '(none)'}`")
    # The status line carries BOTH the phase rollup and the verification badge,
    # so "completed" is never shown without its shippability qualifier.
    if badge == "VERIFIED":
        lines.append(f"- **status**: `{phase_status}` · ✅ VERIFIED (shippable)")
    else:
        lines.append(f"- **status**: `{phase_status}` · {badge} — **NOT shippable** (see Verification)")
    lines.append(f"- **startedAt**: {summary.get('startedAt') or '(unknown)'}")
    env = summary.get("environment") or {}
    if env:
        envline = ", ".join(f"{k}={v}" for k, v in sorted(env.items()) if not k.startswith("_"))
        lines.append(f"- **environment**: {envline}")
    lines.append("")

    lines.append("## Verification")
    lines.append("")
    def _reasons(items: list[dict]) -> str:
        return "; ".join(
            f"`{it.get('check')}` — {it.get('message')}" for it in (items or []) if it
        )
    if badge == "VERIFIED":
        lines.append("- **functional verification**: ✅ VERIFIED "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — shippable")
    elif badge == "DEGRADED":
        why = _reasons(fv.get("degradedChecks")) or "a degradable check could not run (simulator/axe/xcodebuild unavailable)"
        lines.append("- **functional verification**: ⚠️ **DEGRADED (functional unverified)** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable. Degraded checks: {why}")
    else:
        why = _reasons(fv.get("failedChecks"))
        # A FAILED quality/build check (e.g. visual_contract screen-fill unmet) is a
        # real product defect — name it, don't imply "just install a tool".
        suffix = f". Failed checks: {why}" if why else ""
        lines.append("- **functional verification**: ❌ **UNVERIFIED** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable{suffix}")
    lines.append("")

    # Capability coverage — surface every silent limit (downgraded features,
    # unsupported categories, backend-pending, device-deploy, depth caveats).
    coverage = summary.get("coverage") or {}
    if coverage:
        try:
            import capability_coverage
            section = capability_coverage.render(coverage)
            if section:
                lines.append(section)
                lines.append("")
        except Exception:
            pass

    lines.append("## Phase Ledger")
    lines.append("")
    lines.append("| Phase | Status | Duration | Retries | Build fixes | Overrides | Error |")
    lines.append("|------:|--------|---------:|--------:|------------:|----------:|-------|")
    phase_block = summary.get("phases") or {}
    for pid in sorted(phase_block.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        info = phase_block[pid]
        dur = info.get("durationSeconds")
        dur_str = f"{dur}s" if dur is not None else "—"
        status = info.get("status") or "unknown"
        retries = info.get("retryCount", 0)
        max_retry = info.get("maxRetry")
        retry_str = f"{retries}/{max_retry}" if max_retry is not None else str(retries)
        error = str(info.get("error") or "—").replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(
            f"| {pid} | {status} | {dur_str} | {retry_str} | "
            f"{info.get('buildFixAttempts', 0)} | {info.get('operatorOverrides', 0)} | {error} |"
        )
    lines.append("")

    lines.append("## Gate Ledger")
    lines.append("")
    if not summary.get("gateLedger"):
        lines.append("_No gate events recorded._")
    else:
        lines.append("| ts | phase | event | detail |")
        lines.append("|----|------:|-------|--------|")
        for g in summary["gateLedger"][:30]:
            detail = json.dumps(g.get("detail"), ensure_ascii=False) if g.get("detail") else ""
            detail = detail.replace("|", "\\|")[:120]
            lines.append(f"| {g.get('ts')} | {g.get('phase')} | {g.get('event')} | {detail} |")
    lines.append("")

    lines.append("## Build Attempts")
    lines.append("")
    if not summary.get("buildAttempts"):
        lines.append("_No xcodebuild attempts recorded._")
    else:
        for entry in summary["buildAttempts"][:20]:
            detail = json.dumps(entry.get("detail"), ensure_ascii=False) if entry.get("detail") else ""
            lines.append(f"- `{entry.get('ts')}` phase {entry.get('phase')} **{entry.get('event')}**: {detail[:160]}")
    lines.append("")

    quality = summary.get("qualitySignals") or {}
    lines.append("## Quality Signals")
    lines.append("")
    for label, value in quality.items():
        if value is None:
            lines.append(f"- **{label}**: _not recorded_")
        else:
            lines.append(f"- **{label}**: `{json.dumps(value, ensure_ascii=False)[:200]}`")
    lines.append("")

    learnings = summary.get("learnings") or {}
    lines.append("## Learnings")
    lines.append("")
    lines.append(f"- active count: **{learnings.get('activeCount', 0)}**")
    quar = learnings.get("quarantined") or []
    if quar:
        lines.append(f"- quarantined: **{len(quar)}**")
        for q in quar[:5]:
            lines.append(
                f"  - `{q.get('id')}` (phase {q.get('phase')}, "
                f"score {q.get('effect_score')}): {q.get('rule_preview', '')[:120]}"
            )
    lines.append("")

    failure = summary.get("failureFootprint") or {}
    if failure.get("events"):
        lines.append("## Failure Footprint")
        lines.append("")
        for entry in failure["events"]:
            detail = json.dumps(entry.get("detail"), ensure_ascii=False)[:240]
            lines.append(f"- `{entry.get('ts')}` phase {entry.get('phase')} **{entry.get('event')}**: {detail}")
        lines.append("")
        lines.append(f"**Resume**: `{failure.get('resumeCommand')}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_summary(project_root: Path) -> dict:
    summary = build_summary(project_root)
    build_id = summary.get("buildId") or "unknown-build"
    run_dir = project_root / "artifacts" / build_id
    run_dir.mkdir(parents=True, exist_ok=True)

    json_path = run_dir / "run-summary.json"
    md_path = run_dir / "run-summary.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")

    # latest symlink — atomic-ish replace via temp link.
    latest = project_root / "artifacts" / "latest"
    tmp_link = project_root / "artifacts" / ".latest.tmp"
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        os.symlink(build_id, tmp_link)
        os.replace(tmp_link, latest)
    except OSError:
        # Symlinks not supported on this fs — write a pointer file instead.
        latest.write_text(build_id, encoding="utf-8")

    summary["_paths"] = {"json": str(json_path), "md": str(md_path), "latest": str(latest)}

    return summary


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_w = sub.add_parser("write")
    p_w.add_argument("--project-dir", default=".")
    p_p = sub.add_parser("print")
    p_p.add_argument("--project-dir", default=".")
    p_p.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "write":
        result = write_summary(proj)
        print(result["_paths"]["md"])
        return 0
    summary = build_summary(proj)
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
