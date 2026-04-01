#!/usr/bin/env python3
"""Autobot pipeline runtime backed by a machine-readable pipeline spec."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from gate_runner import format_text as format_gate_text
from gate_runner import run_gate as execute_gate

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp_path.replace(path)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_build_log(
    project_dir: Path,
    event: str,
    *,
    phase: str | None = None,
    detail: Any = None,
    agent: str | None = None,
    timestamp: str | None = None,
) -> None:
    log_dir = project_dir / ".autobot"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "build-log.jsonl"

    entry: dict[str, Any] = {"ts": timestamp or utc_now(), "event": event}
    if phase is not None:
        entry["phase"] = int(phase)
    if agent:
        entry["agent"] = agent
    if detail is not None:
        entry["detail"] = detail

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
        handle.write("\n")


def parse_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_key_value(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise SystemExit(f"FATAL: expected KEY=VALUE, got '{raw}'")
    key, value = raw.split("=", 1)
    if not key:
        raise SystemExit(f"FATAL: expected non-empty KEY in '{raw}'")
    return key, parse_json_value(value)


def load_spec() -> dict[str, Any]:
    try:
        data = load_json(SPEC_PATH)
    except FileNotFoundError as exc:
        raise SystemExit(f"FATAL: pipeline spec not found at {SPEC_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FATAL: invalid pipeline spec JSON at {SPEC_PATH} — {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit("FATAL: pipeline spec root must be an object")
    validate_spec(data)
    return data


def validate_spec(spec: dict[str, Any]) -> None:
    statuses = set(spec.get("statuses", []))
    if not statuses:
        raise SystemExit("FATAL: pipeline spec must define statuses")

    phases = spec.get("phases", {})
    gates = spec.get("gates", {})
    if not isinstance(phases, dict) or not phases:
        raise SystemExit("FATAL: pipeline spec must define phases")
    if not isinstance(gates, dict):
        raise SystemExit("FATAL: pipeline spec gates must be an object")

    for source_status, targets in spec.get("transitions", {}).get("default", {}).items():
        if source_status not in statuses:
            raise SystemExit(f"FATAL: transition source status '{source_status}' is not declared in statuses")
        for target in targets:
            if target not in statuses:
                raise SystemExit(f"FATAL: transition target status '{target}' is not declared in statuses")

    for phase_id, phase_spec in phases.items():
        gate_id = phase_spec.get("gate")
        if gate_id is None:
            continue
        if gate_id not in gates:
            raise SystemExit(f"FATAL: phase {phase_id} references missing gate '{gate_id}'")

        gate_spec = gates[gate_id]
        if gate_spec.get("fromPhase") != phase_id:
            raise SystemExit(
                f"FATAL: gate '{gate_id}' fromPhase={gate_spec.get('fromPhase')} does not match phase {phase_id}"
            )

    for gate_id, gate_spec in gates.items():
        from_phase = gate_spec.get("fromPhase")
        to_phase = gate_spec.get("toPhase")
        if from_phase not in phases:
            raise SystemExit(f"FATAL: gate '{gate_id}' references unknown fromPhase '{from_phase}'")
        if to_phase not in phases:
            raise SystemExit(f"FATAL: gate '{gate_id}' references unknown toPhase '{to_phase}'")


def state_file_from_args(args: argparse.Namespace) -> Path:
    if args.state_file:
        return Path(args.state_file)
    return Path(args.project_dir) / ".autobot" / "build-state.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"error: build-state.json not found at {path}")

    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FATAL: Invalid JSON — {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit("FATAL: build-state.json root must be an object")
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json(path, state)


def state_path_for_args(args: argparse.Namespace) -> Path:
    return state_file_from_args(args)


def schema_keys(spec: dict[str, Any], section: str) -> list[str]:
    return list(spec.get("stateSchema", {}).get(section, []))


def phase_ids(spec: dict[str, Any]) -> list[str]:
    return list(spec.get("phases", {}).keys())


def collect_schema_issues(spec: dict[str, Any], state: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in schema_keys(spec, "required"):
        if key not in state:
            errors.append(f"Missing required field: {key}")

    app_name = state.get("appName")
    if app_name and not re.match(r"^[A-Z][a-zA-Z0-9]*$", app_name):
        errors.append(f'appName "{app_name}" does not match /^[A-Z][a-zA-Z0-9]*$/')

    valid_statuses = set(spec.get("statuses", []))
    phases = state.get("phases")
    if isinstance(phases, dict):
        for phase_id in phase_ids(spec):
            if phase_id not in phases:
                errors.append(f"Missing phase {phase_id} in phases")
                continue

            phase_state = phases[phase_id]
            if not isinstance(phase_state, dict):
                errors.append(f"Phase {phase_id} is not an object")
                continue

            for required_key in schema_keys(spec, "phaseRequired"):
                if required_key not in phase_state:
                    errors.append(f"Phase {phase_id} missing {required_key}")

            status = phase_state.get("status")
            if status is not None and status not in valid_statuses:
                errors.append(f"Phase {phase_id} has invalid status: {status}")
    else:
        errors.append("Field phases must be an object")

    for key in schema_keys(spec, "recommended"):
        if key not in state:
            warnings.append(f"Missing recommended field: {key}")

    environment = state.get("environment")
    if isinstance(environment, dict):
        for key in ["xcodegen", "fastlane", "ascConfigured", "axiom", "stitch"]:
            if key not in environment:
                warnings.append(f"environment.{key} not set")

    return errors, warnings


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


def transition_map(spec: dict[str, Any], phase: str) -> dict[str, list[str]]:
    mapping = {
        status: list(targets) for status, targets in spec.get("transitions", {}).get("default", {}).items()
    }
    for status, targets in spec.get("transitions", {}).get("overrides", {}).get(phase, {}).items():
        mapping[status] = list(targets)
    return mapping


def validate_transition_request(
    spec: dict[str, Any],
    state: dict[str, Any],
    phase: str,
    target_status: str,
    *,
    allow_terminal_restart: bool = False,
) -> tuple[bool, list[str]]:
    phases = state.get("phases", {})
    current_status = phases.get(phase, {}).get("status", "pending")

    if phase not in spec.get("phases", {}):
        return False, [f"REJECTED: Unknown phase {phase}"]

    valid_statuses = set(spec.get("statuses", []))
    if target_status not in valid_statuses:
        return False, [f"REJECTED: Invalid target status {target_status}"]

    allowed = set(transition_map(spec, phase).get(current_status, []))
    allow_explicit_restart = (
        allow_terminal_restart
        and spec.get("policies", {}).get("resume", {}).get("allowExplicitRestartFromTerminal", False)
        and target_status == "in_progress"
        and current_status in set(spec.get("terminalStatuses", []))
    )

    if target_status not in allowed and not allow_explicit_restart:
        printable = sorted(allowed)
        return False, [
            f"REJECTED: Phase {phase} cannot transition {current_status} → {target_status}",
            f"  Allowed from {current_status}: {printable or '(none — terminal state)'}",
        ]

    if target_status == "in_progress":
        allowed_dependency_statuses = tuple(
            spec.get("policies", {})
            .get("dependency", {})
            .get("resumeAllowedPreviousStatuses", ["completed", "fallback"])
        )
        for dependency in spec.get("phases", {}).get(phase, {}).get("dependencies", []):
            dependency_status = phases.get(dependency, {}).get("status", "pending")
            if dependency_status not in allowed_dependency_statuses:
                joined = "/".join(allowed_dependency_statuses)
                return False, [
                    f"REJECTED: Phase {phase} requires Phase {dependency} to be "
                    f"{joined} (current: {dependency_status})"
                ]

    if target_status == "in_progress" and current_status == "failed":
        retry_count = phases.get(phase, {}).get("retryCount", 0)
        max_retry = spec.get("phases", {}).get(phase, {}).get("maxRetry", 0)
        if retry_count >= max_retry:
            return False, [f"REJECTED: Phase {phase} has exhausted retries ({retry_count}/{max_retry})"]

    suffix = " (explicit restart)" if allow_explicit_restart else ""
    return True, [f"OK: Phase {phase} {current_status} → {target_status}{suffix}"]


def validate_transition(args: argparse.Namespace) -> int:
    spec = load_spec()
    state = load_state(state_file_from_args(args))
    ok, messages = validate_transition_request(
        spec,
        state,
        str(args.phase),
        args.to,
        allow_terminal_restart=args.allow_terminal_restart,
    )
    for message in messages:
        print(message)
    return 0 if ok else 1


def default_phases(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {phase_id: {"status": "pending"} for phase_id in phase_ids(spec)}


def mutate_state_with_validation(
    path: Path,
    spec: dict[str, Any],
    mutator: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    state = load_state(path)
    next_state = copy.deepcopy(state)
    mutator(next_state)
    errors, warnings = collect_schema_issues(spec, next_state)
    if errors:
        joined = "; ".join(errors)
        raise SystemExit(f"FATAL: refusing to write invalid build state: {joined}")
    save_state(path, next_state)
    for warning in warnings:
        print(f"WARN: {warning}")
    return next_state


def update_phase_status(
    spec: dict[str, Any],
    state_path: Path,
    *,
    phase: str,
    target_status: str,
    at: str | None = None,
    error: str | None = None,
    retry_count: int | None = None,
    increment_retry: bool = False,
    allow_terminal_restart: bool = False,
    metadata_items: list[str] | None = None,
) -> tuple[bool, list[str], str]:
    state = load_state(state_path)
    ok, messages = validate_transition_request(
        spec,
        state,
        phase,
        target_status,
        allow_terminal_restart=allow_terminal_restart,
    )
    if not ok:
        return False, messages, at or utc_now()

    timestamp = at or utc_now()
    metadata_items = metadata_items or []

    def mutate(next_state: dict[str, Any]) -> None:
        phase_state = next_state.setdefault("phases", {}).setdefault(phase, {"status": "pending"})
        phase_state["status"] = target_status

        if target_status == "in_progress":
            phase_state["startedAt"] = timestamp
            phase_state.pop("completedAt", None)
            phase_state.pop("failedAt", None)
            phase_state.pop("skippedAt", None)
            phase_state.pop("error", None)
        elif target_status in {"completed", "fallback"}:
            phase_state["completedAt"] = timestamp
            phase_state.pop("failedAt", None)
            phase_state.pop("skippedAt", None)
            phase_state.pop("error", None)
        elif target_status == "failed":
            phase_state["failedAt"] = timestamp
            if error:
                phase_state["error"] = error
            if retry_count is not None:
                phase_state["retryCount"] = retry_count
            elif increment_retry:
                phase_state["retryCount"] = int(phase_state.get("retryCount", 0)) + 1
        elif target_status == "skipped":
            phase_state["skippedAt"] = timestamp

        if metadata_items:
            metadata = phase_state.setdefault("metadata", {})
            for raw in metadata_items:
                key, value = parse_key_value(raw)
                metadata[key] = value

    mutate_state_with_validation(state_path, spec, mutate)
    return True, messages, timestamp


def init_state(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_file_from_args(args)
    if state_path.exists() and not args.force:
        raise SystemExit(f"FATAL: build-state.json already exists at {state_path}")

    timestamp = args.started_at or utc_now()
    state: dict[str, Any] = {
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
        joined = "; ".join(errors)
        raise SystemExit(f"FATAL: refusing to initialize invalid build state: {joined}")

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
        state_path,
        spec,
        lambda next_state: next_state.setdefault("environment", {}).update(updates),
    )
    print(f"OK: recorded environment fields {sorted(updates)}")
    return 0


def set_phase_status(args: argparse.Namespace) -> int:
    spec = load_spec()
    phase = str(args.phase)
    target_status = args.to
    ok, messages, _timestamp = update_phase_status(
        spec,
        state_path_for_args(args),
        phase=phase,
        target_status=target_status,
        at=args.at,
        error=args.error,
        retry_count=args.retry_count,
        increment_retry=args.increment_retry,
        allow_terminal_restart=args.allow_terminal_restart,
        metadata_items=args.metadata,
    )
    if not ok:
        for message in messages:
            print(message)
        return 1

    for message in messages:
        print(message)
    print(f"OK: wrote phase {phase} status={target_status}")
    return 0


def record_gate_result(args: argparse.Namespace) -> int:
    spec = load_spec()
    state_path = state_path_for_args(args)
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


def start_phase(args: argparse.Namespace) -> int:
    spec = load_spec()
    phase = str(args.phase)
    ok, messages, timestamp = update_phase_status(
        spec,
        state_path_for_args(args),
        phase=phase,
        target_status="in_progress",
        at=args.at,
        allow_terminal_restart=args.allow_terminal_restart,
        metadata_items=args.metadata,
    )
    for message in messages:
        print(message)
    if not ok:
        return 1

    append_build_log(
        Path(args.project_dir).resolve(),
        "start",
        phase=phase,
        detail=args.detail,
        timestamp=timestamp,
    )
    print(f"OK: phase {phase} started")
    return 0


def complete_phase(args: argparse.Namespace) -> int:
    spec = load_spec()
    phase = str(args.phase)
    ok, messages, timestamp = update_phase_status(
        spec,
        state_path_for_args(args),
        phase=phase,
        target_status=args.status,
        at=args.at,
        metadata_items=args.metadata,
    )
    for message in messages:
        print(message)
    if not ok:
        return 1

    event = {"completed": "complete", "fallback": "fallback", "skipped": "skip"}[args.status]
    append_build_log(
        Path(args.project_dir).resolve(),
        event,
        phase=phase,
        detail=args.detail,
        timestamp=timestamp,
    )
    print(f"OK: phase {phase} marked {args.status}")
    return 0


def fail_phase(args: argparse.Namespace) -> int:
    spec = load_spec()
    phase = str(args.phase)
    ok, messages, timestamp = update_phase_status(
        spec,
        state_path_for_args(args),
        phase=phase,
        target_status="failed",
        at=args.at,
        error=args.error,
        retry_count=args.retry_count,
        increment_retry=args.increment_retry,
        metadata_items=args.metadata,
    )
    for message in messages:
        print(message)
    if not ok:
        return 1

    detail: dict[str, Any] = {"error": args.error}
    if args.detail:
        detail["context"] = args.detail
    append_build_log(
        Path(args.project_dir).resolve(),
        "fail",
        phase=phase,
        detail=detail,
        timestamp=timestamp,
    )
    print(f"OK: phase {phase} marked failed")
    return 0


def run_gate_command(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()
    state_path = state_path_for_args(args)
    if not args.no_record and not state_path.is_file():
        raise SystemExit(f"FATAL: build-state.json not found at {state_path}")
    if state_path.is_file():
        state = load_json(state_path)
    else:
        state = {"phases": {}, "backend_required": False}

    app_name = args.app_name or state.get("appName", "")
    if not app_name:
        raise SystemExit("FATAL: --app-name required (or appName must exist in build-state.json)")

    result = execute_gate(args.gate, project_dir, app_name, state, spec)
    if not args.no_record and "error" not in result:
        checks = {group["check"]: group["passed"] for group in result.get("checks", [])}
        gate_status = "passed" if result["passed"] else ("soft_failed" if result.get("soft") else "failed")
        timestamp = args.at or utc_now()

        def mutate(next_state: dict[str, Any]) -> None:
            gates = next_state.setdefault("gates", {})
            gates[args.gate] = {
                "status": gate_status,
                "checkedAt": timestamp,
                "fromPhase": spec["gates"][args.gate].get("fromPhase"),
                "toPhase": spec["gates"][args.gate].get("toPhase"),
                "soft": bool(result.get("soft", False)),
                "checks": checks,
                "detail": result,
            }

        mutate_state_with_validation(state_path, spec, mutate)
        append_build_log(
            project_dir,
            "gate_pass" if result["passed"] else "gate_fail",
            phase=spec["gates"][args.gate].get("fromPhase"),
            detail={"gate": args.gate, "checks": checks, "soft": bool(result.get("soft", False))},
            timestamp=timestamp,
        )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_gate_text(result))

    return 0 if result["passed"] else (0 if result.get("soft") else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autobot pipeline runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema = subparsers.add_parser("validate-schema", help="Validate build-state.json against the pipeline spec")
    schema.add_argument("--project-dir", default=".")
    schema.add_argument("--state-file")
    schema.set_defaults(func=validate_schema)

    transition = subparsers.add_parser("validate-transition", help="Validate a phase status transition")
    transition.add_argument("--phase", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--project-dir", default=".")
    transition.add_argument("--state-file")
    transition.add_argument("--allow-terminal-restart", action="store_true")
    transition.set_defaults(func=validate_transition)

    init = subparsers.add_parser("init-state", help="Initialize build-state.json from the pipeline spec")
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

    phase = subparsers.add_parser("set-phase-status", help="Write a validated phase status update")
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

    environment = subparsers.add_parser("record-environment", help="Write environment detection fields")
    environment.add_argument("--project-dir", default=".")
    environment.add_argument("--state-file")
    environment.add_argument("--xcodegen")
    environment.add_argument("--fastlane")
    environment.add_argument("--ascConfigured")
    environment.add_argument("--axiom")
    environment.add_argument("--stitch")
    environment.add_argument("--field", action="append", default=[], metavar="KEY=VALUE")
    environment.set_defaults(func=record_environment)

    gate = subparsers.add_parser("record-gate-result", help="Write gate execution results")
    gate.add_argument("--project-dir", default=".")
    gate.add_argument("--state-file")
    gate.add_argument("--gate", required=True)
    gate.add_argument("--status", required=True)
    gate.add_argument("--at")
    gate.add_argument("--check", action="append", default=[], metavar="CHECK=VALUE")
    gate.add_argument("--detail")
    gate.add_argument("--detail-json")
    gate.set_defaults(func=record_gate_result)

    start = subparsers.add_parser("start-phase", help="Validate, persist, and log a phase start")
    start.add_argument("--project-dir", default=".")
    start.add_argument("--state-file")
    start.add_argument("--phase", required=True)
    start.add_argument("--at")
    start.add_argument("--detail")
    start.add_argument("--allow-terminal-restart", action="store_true")
    start.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    start.set_defaults(func=start_phase)

    complete = subparsers.add_parser("complete-phase", help="Validate, persist, and log phase completion")
    complete.add_argument("--project-dir", default=".")
    complete.add_argument("--state-file")
    complete.add_argument("--phase", required=True)
    complete.add_argument("--status", choices=["completed", "fallback", "skipped"], default="completed")
    complete.add_argument("--at")
    complete.add_argument("--detail")
    complete.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")
    complete.set_defaults(func=complete_phase)

    fail = subparsers.add_parser("fail-phase", help="Validate, persist, and log a phase failure")
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

    gate_run = subparsers.add_parser("run-gate", help="Execute a gate, persist the result, and log it")
    gate_run.add_argument("--project-dir", default=".")
    gate_run.add_argument("--state-file")
    gate_run.add_argument("--gate", required=True)
    gate_run.add_argument("--app-name")
    gate_run.add_argument("--format", choices=["text", "json"], default="text")
    gate_run.add_argument("--at")
    gate_run.add_argument("--no-record", action="store_true")
    gate_run.set_defaults(func=run_gate_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
