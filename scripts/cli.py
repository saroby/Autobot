#!/usr/bin/env python3
"""Argparse + command handlers for the runtime CLI.

Each *_command function below is the implementation of one subcommand exposed
by `python3 runtime.py <cmd>`. Higher-level rules live in their own modules
(spec_loader / state_store / event_log / transitions / gate_persistence) and
this file orchestrates them.

The advance-phase command is implemented here because it composes gate
execution + phase mutation + log emission inside one mutate_state_with_validation
call; keeping it co-located with its argparse hookup (rather than yet another
module) avoids extra indirection without clouding responsibilities.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from event_log import append_build_log
from gate_persistence import execute_and_record_gate
from gate_runner import format_text as format_gate_text
from phase_advance import advance_phase
from spec_loader import load_spec
from state_store import (
    collect_schema_issues,
    default_phases,
    load_json,
    load_state,
    mutate_state_with_validation,
    parse_json_value,
    parse_key_value,
    save_state,
    state_file_from_args,
    utc_now,
)
from transitions import update_phase_status, validate_transition_request


# ── State inspection / construction ──


def validate_schema(args: argparse.Namespace) -> int:
    spec = load_spec()
    state = load_state(state_file_from_args(args))
    errors, warnings = collect_schema_issues(spec, state)

    if errors:
        for message in errors:
            print(f"ERROR: {message}")
        return 1
    for message in warnings:
        print(f"WARN: {message}")
    print(f"OK: schema valid (spec v{spec.get('schemaVersion', 'unknown')})")
    return 0


def validate_transition(args: argparse.Namespace) -> int:
    spec = load_spec()
    state = load_state(state_file_from_args(args))
    ok, messages = validate_transition_request(
        spec, state, str(args.phase), args.to,
        allow_terminal_restart=args.allow_terminal_restart,
    )
    for message in messages:
        print(message)
    return 0 if ok else 1


def init_state(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)
    if state_path.exists() and not args.force:
        raise SystemExit(f"FATAL: build-state.json already exists at {state_path}")

    timestamp = args.started_at or utc_now()
    state: dict[str, Any] = {
        "schemaVersion": spec.get("schemaVersion"),
        "buildId": args.build_id,
        "appName": args.app_name,
        "displayName": args.display_name,
        "projectPath": args.project_path or str(Path(args.project_dir).resolve()),
        "startedAt": timestamp,
        "contracts": {
            "modelsSnapshotPath": args.models_snapshot_path,
            "modelsChecksumFile": args.models_checksum_file,
        },
        "environment": {},
        "phases": default_phases(spec),
        "backend_required": args.backend_required,
        "backend": None,
    }
    if args.bundle_id:
        state["bundleId"] = args.bundle_id
    if args.idea:
        state["idea"] = args.idea

    errors, warnings = collect_schema_issues(spec, state)
    if errors:
        raise SystemExit("FATAL: refusing to initialize invalid build state: " + "; ".join(errors))

    save_state(state_path, state)
    for warning in warnings:
        print(f"WARN: {warning}")
    print(f"OK: initialized build state at {state_path}")
    return 0


def record_environment(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)

    updates: dict[str, Any] = {}
    known_keys = ["xcodegen", "fastlane", "ascConfigured", "axiom", "stitch"]
    for key in known_keys:
        value = getattr(args, key)
        if value is not None:
            updates[key] = parse_json_value(value)
    for raw in args.field:
        key, value = parse_key_value(raw)
        updates[key] = value

    if not updates:
        raise SystemExit("FATAL: record-environment requires at least one field update")

    mutate_state_with_validation(
        state_path, spec,
        lambda next_state: next_state.setdefault("environment", {}).update(updates),
    )
    print(f"OK: recorded environment fields {sorted(updates)}")
    return 0


# ── Phase lifecycle ──


# Maps the user-visible CLI status onto the build-log event name.
_STATUS_TO_EVENT = {
    "in_progress": "start",
    "completed": "complete",
    "fallback": "fallback",
    "skipped": "skip",
    "failed": "fail",
}


def _run_lifecycle_command(
    args: argparse.Namespace,
    *,
    target_status: str,
    detail_builder=None,
    success_message: str | None = None,
) -> int:
    """Shared body for start/complete/fail. The three commands differ only in
    target_status, the build-log detail shape, and the final OK message.
    """
    spec = load_spec()
    phase = str(args.phase)
    ok, messages, timestamp = update_phase_status(
        spec, state_file_from_args(args),
        phase=phase, target_status=target_status, at=args.at,
        error=getattr(args, "error", None),
        retry_count=getattr(args, "retry_count", None),
        increment_retry=getattr(args, "increment_retry", False),
        allow_terminal_restart=getattr(args, "allow_terminal_restart", False),
        metadata_items=args.metadata,
    )
    for message in messages:
        print(message)
    if not ok:
        return 1

    detail = detail_builder(args) if detail_builder else getattr(args, "detail", None)
    append_build_log(
        Path(args.project_dir).resolve(),
        _STATUS_TO_EVENT[target_status],
        phase=phase, detail=detail, timestamp=timestamp, spec=spec,
    )
    print(success_message.format(phase=phase) if success_message else f"OK: phase {phase}")
    return 0


def set_phase_status(args: argparse.Namespace) -> int:
    spec = load_spec()
    phase = str(args.phase)
    ok, messages, _ = update_phase_status(
        spec, state_file_from_args(args),
        phase=phase, target_status=args.to, at=args.at,
        error=args.error, retry_count=args.retry_count,
        increment_retry=args.increment_retry,
        allow_terminal_restart=args.allow_terminal_restart,
        metadata_items=args.metadata,
    )
    for message in messages:
        print(message)
    if not ok:
        return 1
    print(f"OK: wrote phase {phase} status={args.to}")
    return 0


def start_phase(args: argparse.Namespace) -> int:
    return _run_lifecycle_command(
        args, target_status="in_progress",
        success_message="OK: phase {phase} started",
    )


def complete_phase(args: argparse.Namespace) -> int:
    return _run_lifecycle_command(
        args, target_status=args.status,
        success_message=f"OK: phase {{phase}} marked {args.status}",
    )


def _fail_detail(args: argparse.Namespace) -> dict[str, Any]:
    detail: dict[str, Any] = {"error": args.error}
    if args.detail:
        detail["context"] = args.detail
    return detail


def fail_phase(args: argparse.Namespace) -> int:
    return _run_lifecycle_command(
        args, target_status="failed",
        detail_builder=_fail_detail,
        success_message="OK: phase {phase} marked failed",
    )


# ── Gate / flag / log ──


def record_gate_result(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)
    gate_id = args.gate
    if gate_id not in spec.get("gates", {}):
        raise SystemExit(f"FATAL: unknown gate '{gate_id}'")

    timestamp = args.at or utc_now()
    gate_spec = spec["gates"][gate_id]
    checks: dict[str, Any] = {}
    for raw in args.check:
        key, value = parse_key_value(raw)
        checks[key] = value

    detail: Any = None
    if args.detail_json:
        detail = parse_json_value(args.detail_json)
    elif args.detail:
        detail = args.detail

    def mutate(next_state: dict[str, Any]) -> None:
        gates = next_state.setdefault("gates", {})
        gate_state: dict[str, Any] = {
            "status": args.status,
            "checkedAt": timestamp,
            "fromPhase": gate_spec.get("fromPhase"),
            "toPhase": gate_spec.get("toPhase"),
            "soft": bool(gate_spec.get("soft", False)),
        }
        if checks:
            gate_state["checks"] = checks
        if detail is not None:
            gate_state["detail"] = detail
        gates[gate_id] = gate_state

    mutate_state_with_validation(state_path, spec, mutate)
    print(f"OK: recorded gate {gate_id} status={args.status}")
    return 0


def run_gate_command(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()
    state_path = state_file_from_args(args)
    if not args.no_record and not state_path.is_file():
        raise SystemExit(f"FATAL: build-state.json not found at {state_path}")

    state = load_json(state_path) if state_path.is_file() else {"phases": {}, "backend_required": False}
    app_name = args.app_name or state.get("appName", "")
    if not app_name:
        raise SystemExit("FATAL: --app-name required (or appName must exist in build-state.json)")

    timestamp = args.at or utc_now()
    result = execute_and_record_gate(
        spec, state_path, project_dir, args.gate, app_name,
        timestamp=timestamp, no_record=args.no_record,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_gate_text(result))

    return 0 if result["passed"] else (0 if result.get("soft") else 1)


def set_flag(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)
    project_dir = Path(args.project_dir).resolve()

    allowed = set(spec.get("policies", {}).get("allowedFlags", []))
    if args.key not in allowed:
        raise SystemExit(
            f"FATAL: unsupported flag '{args.key}'. "
            f"Allowed (from spec.policies.allowedFlags): {sorted(allowed)}"
        )

    new_value = parse_json_value(args.value)
    state = load_state(state_path)
    old_value = state.get(args.key)

    def mutate(next_state: dict[str, Any]) -> None:
        next_state[args.key] = new_value

    mutate_state_with_validation(state_path, spec, mutate)

    timestamp = args.at or utc_now()
    append_build_log(
        project_dir, "flag_changed", spec=spec, timestamp=timestamp,
        detail={"key": args.key, "from": old_value, "to": new_value, "reason": args.reason or ""},
    )
    print(f"OK: flag '{args.key}' {old_value!r} → {new_value!r}")
    return 0


def append_log(args: argparse.Namespace) -> int:
    """Validated build-log append, used by build-log.sh."""
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()

    detail: Any = None
    if args.detail_json:
        detail = parse_json_value(args.detail_json)
    elif args.detail:
        try:
            detail = json.loads(args.detail)
        except (json.JSONDecodeError, ValueError):
            detail = args.detail

    # learning_applied has a side-effect on state: phases.<id>.learningsConsumed
    # accumulates the agent name so gates can require it. The state mutation
    # and the log append run inside the same command for atomicity (a failure
    # in either fail-loud, leaving no half-written audit trail).
    if args.event == "learning_applied" and args.phase and args.agent:
        state_path = state_file_from_args(args)
        if state_path.is_file():
            def mutate(next_state: dict[str, Any]) -> None:
                phases = next_state.setdefault("phases", {})
                phase_state = phases.setdefault(str(args.phase), {"status": "pending"})
                consumed = phase_state.setdefault("learningsConsumed", [])
                if args.agent not in consumed:
                    consumed.append(args.agent)
                    consumed.sort()

            mutate_state_with_validation(state_path, spec, mutate)

    append_build_log(
        project_dir, args.event,
        phase=args.phase, agent=args.agent, detail=detail,
        timestamp=args.at, spec=spec,
    )
    print(f"OK: logged event '{args.event}'")
    return 0



# ── argparse wiring ──


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autobot pipeline runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    schema = sub.add_parser("validate-schema", help="Validate build-state.json against the pipeline spec")
    schema.add_argument("--project-dir", default=".")
    schema.add_argument("--state-file")
    schema.set_defaults(func=validate_schema)

    transition = sub.add_parser("validate-transition", help="Validate a phase status transition")
    transition.add_argument("--phase", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--project-dir", default=".")
    transition.add_argument("--state-file")
    transition.add_argument("--allow-terminal-restart", action="store_true")
    transition.set_defaults(func=validate_transition)

    init = sub.add_parser("init-state", help="Initialize build-state.json from the pipeline spec")
    init.add_argument("--project-dir", default=".")
    init.add_argument("--state-file")
    init.add_argument("--build-id", required=True)
    init.add_argument("--app-name", required=True)
    init.add_argument("--display-name", required=True)
    init.add_argument("--bundle-id")
    init.add_argument("--project-path")
    init.add_argument("--idea")
    init.add_argument("--started-at")
    init.add_argument("--backend-required", action="store_true")
    init.add_argument("--models-snapshot-path", default=".autobot/contracts/phase-1-models")
    init.add_argument("--models-checksum-file", default=".autobot/contracts/models.sha256")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=init_state)

    phase = sub.add_parser("set-phase-status", help="Write a validated phase status update")
    phase.add_argument("--project-dir", default=".")
    phase.add_argument("--state-file")
    phase.add_argument("--phase", required=True)
    phase.add_argument("--to", required=True)
    phase.add_argument("--at")
    phase.add_argument("--error")
    phase.add_argument("--retry-count", type=int)
    phase.add_argument("--increment-retry", action="store_true")
    phase.add_argument("--allow-terminal-restart", action="store_true")
    phase.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    phase.set_defaults(func=set_phase_status)

    environment = sub.add_parser("record-environment", help="Write environment detection fields")
    environment.add_argument("--project-dir", default=".")
    environment.add_argument("--state-file")
    environment.add_argument("--xcodegen")
    environment.add_argument("--fastlane")
    environment.add_argument("--ascConfigured")
    environment.add_argument("--axiom")
    environment.add_argument("--stitch")
    environment.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    environment.set_defaults(func=record_environment)

    gate = sub.add_parser("record-gate-result", help="Write gate execution results")
    gate.add_argument("--project-dir", default=".")
    gate.add_argument("--state-file")
    gate.add_argument("--gate", required=True)
    gate.add_argument("--status", required=True)
    gate.add_argument("--at")
    gate.add_argument("--check", action="append", default=[], metavar="CHECK=VALUE")
    gate.add_argument("--detail")
    gate.add_argument("--detail-json")
    gate.set_defaults(func=record_gate_result)

    start = sub.add_parser("start-phase", help="Validate, persist, and log a phase start")
    start.add_argument("--project-dir", default=".")
    start.add_argument("--state-file")
    start.add_argument("--phase", required=True)
    start.add_argument("--at")
    start.add_argument("--detail")
    start.add_argument("--allow-terminal-restart", action="store_true")
    start.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    start.set_defaults(func=start_phase)

    complete = sub.add_parser("complete-phase", help="Validate, persist, and log phase completion")
    complete.add_argument("--project-dir", default=".")
    complete.add_argument("--state-file")
    complete.add_argument("--phase", required=True)
    complete.add_argument("--status", choices=["completed", "fallback", "skipped"], default="completed")
    complete.add_argument("--at")
    complete.add_argument("--detail")
    complete.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    complete.set_defaults(func=complete_phase)

    fail = sub.add_parser("fail-phase", help="Validate, persist, and log a phase failure")
    fail.add_argument("--project-dir", default=".")
    fail.add_argument("--state-file")
    fail.add_argument("--phase", required=True)
    fail.add_argument("--error", required=True)
    fail.add_argument("--at")
    fail.add_argument("--detail")
    fail.add_argument("--retry-count", type=int)
    fail.add_argument("--increment-retry", action="store_true")
    fail.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    fail.set_defaults(func=fail_phase)

    gate_run = sub.add_parser("run-gate", help="Execute a gate, persist the result, and log it")
    gate_run.add_argument("--project-dir", default=".")
    gate_run.add_argument("--state-file")
    gate_run.add_argument("--gate", required=True)
    gate_run.add_argument("--app-name")
    gate_run.add_argument("--format", choices=["text", "json"], default="text")
    gate_run.add_argument("--at")
    gate_run.add_argument("--no-record", action="store_true")
    gate_run.set_defaults(func=run_gate_command)

    flag = sub.add_parser("set-flag", help="Atomically toggle a top-level state flag (e.g. backend_required)")
    flag.add_argument("--project-dir", default=".")
    flag.add_argument("--state-file")
    flag.add_argument("--key", required=True)
    flag.add_argument("--value", required=True, help="JSON-parsed (true/false/string/number)")
    flag.add_argument("--reason")
    flag.add_argument("--at")
    flag.set_defaults(func=set_flag)

    log_cmd = sub.add_parser("append-log", help="Append a validated event to .autobot/build-log.jsonl")
    log_cmd.add_argument("--project-dir", default=".")
    log_cmd.add_argument("--state-file")
    log_cmd.add_argument("--event", required=True)
    log_cmd.add_argument("--phase")
    log_cmd.add_argument("--agent")
    log_cmd.add_argument("--detail")
    log_cmd.add_argument("--detail-json")
    log_cmd.add_argument("--at")
    log_cmd.set_defaults(func=append_log)

    advance = sub.add_parser(
        "advance-phase",
        help="Run the phase's outgoing gate and mark the phase complete only if it passes",
    )
    advance.add_argument("--project-dir", default=".")
    advance.add_argument("--state-file")
    advance.add_argument("--phase", required=True)
    advance.add_argument("--status", choices=["completed", "fallback", "skipped"], default="completed")
    advance.add_argument("--app-name")
    advance.add_argument("--format", choices=["text", "json"], default="text")
    advance.add_argument("--at")
    advance.add_argument("--detail")
    advance.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    advance.set_defaults(func=advance_phase)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))
