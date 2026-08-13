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
import subprocess
import sys
from pathlib import Path
from typing import Any

from event_log import append_build_log, validate_log_event
from gate_persistence import execute_and_record_gate, handle_breaker_trip
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

    # Build + validate the state BEFORE acquiring the lock: a schema failure
    # here (e.g. bad app-name) must not exit while holding the lock, or the
    # corrected retry with the same build-id stays BLOCKED for the whole lease.
    state: dict[str, Any] = {
        "schemaVersion": spec.get("schemaVersion"),
        "buildId": args.build_id,
        "appName": args.app_name,
        "displayName": args.display_name,
        "projectPath": args.project_path or str(Path(args.project_dir).resolve()),
        "startedAt": utc_now(),
        "contracts": {
            "modelsSnapshotPath": ".autobot/contracts/phase-1-models",
            "modelsChecksumFile": ".autobot/contracts/models.sha256",
        },
        "environment": {},
        "phases": default_phases(spec),
        "backend_required": False,
        "backend": None,
    }
    if args.bundle_id:
        state["bundleId"] = args.bundle_id
    if args.idea:
        state["idea"] = args.idea

    errors, warnings = collect_schema_issues(spec, state)
    if errors:
        raise SystemExit("FATAL: refusing to initialize invalid build state: " + "; ".join(errors))

    # Acquire the build lock BEFORE writing any state, so a second concurrent
    # build cannot clobber an in-flight `.autobot/`. A stale lock (dead holder
    # PID) is reclaimed automatically; re-init of the same build is idempotent.
    import build_lock
    project_root = state_path.parent.parent
    expected_token = None
    if args.force:
        current_lock = build_lock.status(project_root)
        if current_lock.get("buildId") == args.build_id and current_lock.get("holderAlive"):
            expected_token = current_lock.get("lockToken")
    locked, lock_reason, lock_token = build_lock.acquire_with_token(
        project_root,
        args.build_id,
        takeover_same_build=bool(args.force),
        expected_token=expected_token,
    )
    if not locked:
        raise SystemExit(f"FATAL: cannot start build — {lock_reason}")
    print(f"OK: build lock — {lock_reason}")
    print(f"LOCK_TOKEN={lock_token}")

    save_state(state_path, state)

    # Seed the host-wide learnings store into this project now that it is a real
    # Autobot project. The SessionStart hook only refreshes projects that already
    # have `.autobot/` — seeding there would create the dir in every unrelated
    # repo the user opens. Render immediately too: the hook renders at
    # SessionStart, which for a brand-new project already ran BEFORE `.autobot/`
    # existed — without this the whole first build reads no active-learnings.md.
    # Best-effort: never fail a build init over learnings.
    try:
        import learning_impact
        learning_impact.merge_global_into_project(project_root)
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "render-active-learnings.py"),
             "--project-dir", str(project_root)],
            check=False, capture_output=True,
        )
    except Exception as exc:  # noqa: BLE001 - advisory only
        print(f"WARN: could not seed global learnings — {exc}")

    for warning in warnings:
        print(f"WARN: {warning}")
    print(f"OK: initialized build state at {state_path}")
    return 0


def record_environment(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)

    updates: dict[str, Any] = {}
    known_keys = [
        "xcodegen", "fastlane", "ascConfigured", "axiom",
        "runtimeHost", "peerAi", "peerReviewAvailable",
    ]
    for key in known_keys:
        value = getattr(args, key)
        if value is not None:
            updates[key] = parse_json_value(value)

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

    project_dir = Path(args.project_dir).resolve()
    detail = detail_builder(args) if detail_builder else getattr(args, "detail", None)
    if target_status == "in_progress" and getattr(args, "allow_terminal_restart", False):
        resume_policy = spec.get("policies", {}).get("resume", {})
        if resume_policy.get("allowExplicitRestartFromTerminal", False):
            # Operator override must be visible in build-log forensics too,
            # not only in state (transitions records phases.<N>.operatorOverrides).
            detail = (
                {"operatorOverride": True, "context": detail}
                if detail is not None else {"operatorOverride": True}
            )
    append_build_log(
        project_dir,
        _STATUS_TO_EVENT[target_status],
        phase=phase, detail=detail, timestamp=timestamp, spec=spec,
    )
    if target_status == "in_progress":
        # Lease heartbeat: a long build must not outlive its build.lock lease.
        import build_lock
        build_lock.renew_from_state(project_dir)
    print(success_message.format(phase=phase) if success_message else f"OK: phase {phase}")
    if target_status == "failed":
        # fail-phase is the documented pre-gate failure path — it must trip the
        # breaker identically to advance-phase's hard-gate failure path.
        trip_message = handle_breaker_trip(
            spec, state_file_from_args(args), project_dir, phase, timestamp,
        )
        if trip_message is not None:
            print(f"WARN: {trip_message}")
    return 0


def start_phase(args: argparse.Namespace) -> int:
    return _run_lifecycle_command(
        args, target_status="in_progress",
        success_message="OK: phase {phase} started",
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


def run_gate_command(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()
    state_path = state_file_from_args(args)
    if not state_path.is_file():
        raise SystemExit(f"FATAL: build-state.json not found at {state_path}")

    state = load_json(state_path)
    app_name = args.app_name or state.get("appName", "")
    if not app_name:
        raise SystemExit("FATAL: --app-name required (or appName must exist in build-state.json)")

    timestamp = args.at or utc_now()
    result = execute_and_record_gate(
        spec, state_path, project_dir, args.gate, app_name,
        timestamp=timestamp,
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

    # Validate the event BEFORE any state mutation. learning_applied mutates
    # phases.<id>.learningsConsumed (which gates require); if the event/detail
    # were only validated inside append_build_log AFTER the mutation, a bad
    # detail would leave gate-satisfying state behind with no audit log row.
    log_errors = validate_log_event(
        spec, args.event, {"phase": args.phase, "agent": args.agent, "detail": detail},
    )
    if log_errors:
        raise SystemExit("FATAL: invalid build-log event: " + "; ".join(log_errors))

    # learning_applied has a side-effect on state: phases.<id>.learningsConsumed
    # accumulates the agent name so gates can require it. The event is already
    # validated above, so the mutation and the log append below cannot diverge
    # on a validation failure.
    if args.event == "learning_applied" and args.phase and args.agent:
        state_path = state_file_from_args(args)
        if state_path.is_file():
            from learning_impact import stable_id  # import-light, no spec dep
            rules = [r for r in (getattr(args, "rule", None) or []) if r and r.strip()]

            def mutate(next_state: dict[str, Any]) -> None:
                phases = next_state.setdefault("phases", {})
                phase_state = phases.setdefault(str(args.phase), {"status": "pending"})
                consumed = phase_state.setdefault("learningsConsumed", [])
                # Always keep the agent NAME as a bare string: Gate
                # `*_consumed_learnings` (state_field_contains) asserts the agent
                # name is present, and grading falls back to it for legacy builds.
                if args.agent not in consumed:
                    consumed.append(args.agent)
                # Additionally record one structured entry PER applied rule so
                # effect-score grading + quarantine operate at rule granularity —
                # a single bad rule can be quarantined without nuking everything
                # the agent applied (the per-agent-only bucket was the W4 defect).
                existing_ids = {c.get("id") for c in consumed if isinstance(c, dict)}
                for rule in rules:
                    rid = stable_id(str(args.phase), rule)
                    if rid not in existing_ids:
                        consumed.append({"id": rid, "rule": rule, "agent": args.agent})
                        existing_ids.add(rid)
                # Mixed str/dict list: sort by a string key so str↔dict never compare.
                consumed.sort(key=lambda c: c if isinstance(c, str) else c.get("id", ""))

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
    init.add_argument("--idea", help="Raw app idea; consumed from state by input-hash / capability / intent checks")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=init_state)

    environment = sub.add_parser("record-environment", help="Write environment detection fields")
    environment.add_argument("--project-dir", default=".")
    environment.add_argument("--state-file")
    environment.add_argument("--xcodegen")
    environment.add_argument("--fastlane")
    environment.add_argument("--ascConfigured")
    environment.add_argument("--axiom")
    environment.add_argument("--runtimeHost")
    environment.add_argument("--peerAi")
    environment.add_argument("--peerReviewAvailable")
    environment.set_defaults(func=record_environment)

    start = sub.add_parser("start-phase", help="Validate, persist, and log a phase start")
    start.add_argument("--project-dir", default=".")
    start.add_argument("--state-file")
    start.add_argument("--phase", required=True)
    start.add_argument("--at")
    start.add_argument("--detail")
    start.add_argument("--allow-terminal-restart", action="store_true")
    start.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    start.set_defaults(func=start_phase)

    fail = sub.add_parser("fail-phase", help="Validate, persist, and log a phase failure")
    fail.add_argument("--project-dir", default=".")
    fail.add_argument("--state-file")
    fail.add_argument("--phase", required=True)
    fail.add_argument("--error", required=True)
    fail.add_argument("--at")
    fail.add_argument("--detail")
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
    log_cmd.add_argument(
        "--rule", action="append", default=None,
        help="A specific learning/prevention rule that was applied (repeatable). "
             "On a learning_applied event each --rule records a per-rule entry in "
             "phases.<N>.learningsConsumed so effect-score grading can quarantine "
             "one bad rule instead of the whole agent bucket.",
    )
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
