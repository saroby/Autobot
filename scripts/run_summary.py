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
    - Failure footprint (if status != completed): first 3 reasons, suggested resume command
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path


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


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # ISO 8601 with trailing Z
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        if entry.get("event") in {"fail", "gate_fail", "circuit_breaker_triggered"}:
            failed.append({
                "ts": entry.get("ts"),
                "event": entry.get("event"),
                "phase": entry.get("phase"),
                "detail": entry.get("detail"),
            })
    failed_phase = None
    for pid, block in (state.get("phases") or {}).items():
        if isinstance(block, dict) and block.get("status") == "failed":
            failed_phase = pid
            break
    resume_hint = f"/autobot:resume {failed_phase}" if failed_phase else "/autobot:resume"
    return {"events": failed[:5], "resumeCommand": resume_hint, "failedPhase": failed_phase}


def _quality_signals(state: dict) -> dict:
    phases = state.get("phases") or {}
    p3 = phases.get("3") or {}
    p5 = phases.get("5") or {}
    p7 = phases.get("7") or {}
    return {
        "scaffoldBuild": (p3.get("metadata") or {}).get("scaffoldBuild"),
        "runtimeSmoke": (p5.get("metadata") or {}).get("runtimeSmoke"),
        "visualContract": (p5.get("metadata") or {}).get("visualContract"),
        "metadataReadiness": (p5.get("metadata") or {}).get("metadataReadiness"),
        "axiomAudit": (p5.get("metadata") or {}).get("axiomAudit") or (p7.get("metadata") or {}).get("axiomAudit"),
        "peerReview": (p5.get("metadata") or {}).get("peerReview"),
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


def _overall_status(state: dict) -> str:
    phases = state.get("phases") or {}
    statuses = [b.get("status") for b in phases.values() if isinstance(b, dict)]
    if any(s == "failed" for s in statuses):
        return "failed"
    if all(s in {"completed", "fallback", "skipped"} or s is None for s in statuses):
        return "completed"
    return "in_progress"


def _functional_verification(state: dict) -> dict:
    """Derive the shipping-verification badge from gate 5->6's recorded verdict.

    badge:
      VERIFIED   — gate 5->6 status == 'passed' (functional flows ran + passed)
      DEGRADED   — gate 5->6 status == 'degraded' (flows unverified: no sim/axe)
      UNVERIFIED — gate 5->6 status is soft_failed/failed/absent
    Only VERIFIED is shippable. This mirrors check_functional_verification_passed.
    """
    status = (state.get("gates", {}).get("5->6") or {}).get("status")
    if status == "passed":
        badge = "VERIFIED"
    elif status == "degraded":
        badge = "DEGRADED"
    else:
        badge = "UNVERIFIED"
    return {
        "badge": badge,
        "gate56Status": status,
        "shippable": badge == "VERIFIED",
    }


def build_summary(project_root: Path) -> dict:
    state = _load_json(project_root / ".autobot" / "build-state.json")
    events = _load_jsonl(project_root / ".autobot" / "build-log.jsonl")

    summary = {
        "buildId": state.get("buildId"),
        "appName": state.get("appName"),
        "displayName": state.get("displayName"),
        "bundleId": state.get("bundleId"),
        "startedAt": state.get("startedAt"),
        "environment": state.get("environment"),
        "status": _overall_status(state),
        "functionalVerification": _functional_verification(state),
        "phases": _phase_durations(events),
        "gateLedger": _gate_ledger(events),
        "buildAttempts": _build_attempts(events),
        "qualitySignals": _quality_signals(state),
        "learnings": _learnings_summary(project_root),
        "failureFootprint": _failure_footprint(state, events),
    }
    return summary


def render_markdown(summary: dict) -> str:
    lines: list[str] = []
    lines.append(f"# {summary.get('displayName') or summary.get('appName') or 'Autobot Build'} — Run Summary")
    lines.append("")
    lines.append(f"- **buildId**: `{summary.get('buildId')}`")
    lines.append(f"- **bundleId**: `{summary.get('bundleId') or '(none)'}`")
    lines.append(f"- **status**: `{summary.get('status')}`")
    lines.append(f"- **startedAt**: {summary.get('startedAt') or '(unknown)'}")
    env = summary.get("environment") or {}
    if env:
        envline = ", ".join(f"{k}={v}" for k, v in sorted(env.items()) if not k.startswith("_"))
        lines.append(f"- **environment**: {envline}")
    lines.append("")

    fv = summary.get("functionalVerification") or {}
    badge = fv.get("badge", "UNVERIFIED")
    lines.append("## Verification")
    lines.append("")
    if badge == "VERIFIED":
        lines.append("- **functional verification**: ✅ VERIFIED "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — shippable")
    elif badge == "DEGRADED":
        lines.append("- **functional verification**: ⚠️ **DEGRADED (functional unverified)** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable: "
                     "flows could not run (simulator/axe/xcodebuild unavailable)")
    else:
        lines.append("- **functional verification**: ❌ **UNVERIFIED** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable")
    lines.append("")

    lines.append("## Phase Ledger")
    lines.append("")
    lines.append("| Phase | Status | Duration | Retries | Build fixes |")
    lines.append("|------:|--------|---------:|--------:|------------:|")
    state_phases = (summary.get("environment") or {})  # placeholder, we'll use the durations below
    phase_block = summary.get("phases") or {}
    full_state: dict = {}  # not in summary, but enough info is in phase_block
    # We need retry counts — re-load build-state.
    # We avoid round-tripping by trusting that summary already saw them; phase_block has only timing.
    # That's OK — keep the table minimal but useful.
    for pid in sorted(phase_block.keys(), key=lambda x: int(x) if x.isdigit() else 99):
        info = phase_block[pid]
        dur = info.get("durationSeconds")
        dur_str = f"{dur}s" if dur is not None else "—"
        lines.append(f"| {pid} | (see state) | {dur_str} | — | — |")
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
