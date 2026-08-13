#!/usr/bin/env python3
"""build-state.json I/O + schema-validated mutation.

Every write to .autobot/build-state.json funnels through
mutate_state_with_validation here so that no caller can bypass schema checks
or atomic-write guarantees. Pure-IO helpers (load_json, write_json, time/parse
utilities) live here too because state_store is the lowest stable layer above
the filesystem.

Dependency rule (do not break):
  state_store may import from spec_loader only.
  state_store MUST NOT import event_log — logging is a higher-level concern.
  If a future feature wants to log inside a mutation, pass a callback in
  through the caller; do not introduce the reverse edge.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from spec_loader import phase_ids, schema_keys

__all__ = [
    "load_json", "write_json", "utc_now",
    "parse_json_value", "parse_key_value",
    "state_file_from_args", "state_file_for",
    "load_state", "try_load_state", "save_state",
    "default_phases", "collect_schema_issues",
    "mutate_state_with_validation",
]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(raw_tmp_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


@contextmanager
def _state_write_lock(path: Path):
    """Hold a per-state advisory lock across the full read/modify/write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def state_file_from_args(args: argparse.Namespace) -> Path:
    if args.state_file:
        return Path(args.state_file)
    return Path(args.project_dir) / ".autobot" / "build-state.json"


def state_file_for(project_root: Path) -> Path:
    """Canonical .autobot/build-state.json path for a given project root.

    Companion to state_file_from_args() for callers that don't have an
    argparse.Namespace (learning_impact, sandbox_guard, ad-hoc tools).
    """
    return Path(project_root) / ".autobot" / "build-state.json"


# Historical alias — kept because cli.py and phase_advance.py reach in via the
# facade. New call sites should use state_file_from_args directly.
state_path_for_args = state_file_from_args


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


def try_load_state(path: Path) -> dict[str, Any] | None:
    """Soft variant of load_state: returns None on any read/parse failure.

    Used by tools (learning_impact, sandbox_guard) that must function before
    the pipeline has initialised state. Production gate paths should use
    load_state() so missing/corrupt state fails loudly.
    """
    if not path.is_file():
        return None
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_state(path: Path, state: dict[str, Any]) -> None:
    write_json(path, state)


def default_phases(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {phase_id: {"status": "pending"} for phase_id in phase_ids(spec)}


def collect_schema_issues(
    spec: dict[str, Any], state: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # schemaVersion compatibility: state files written under an older spec
    # version are accepted with a WARN; future versions are blocked so we
    # don't silently corrupt them.
    spec_version = spec.get("schemaVersion")
    state_version = state.get("schemaVersion")
    if isinstance(spec_version, int) and isinstance(state_version, int):
        if state_version > spec_version:
            errors.append(
                f"build-state.schemaVersion={state_version} is newer than "
                f"spec.schemaVersion={spec_version} — refusing to write"
            )
        elif state_version < spec_version:
            warnings.append(
                f"build-state.schemaVersion={state_version} predates "
                f"spec.schemaVersion={spec_version}; running in legacy compat mode"
            )

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
                # WARN, not ERROR: a phase the spec grew after this state was
                # written (e.g. "2.5") is legitimate history, and
                # mutate_state_with_validation backfills it as pending before
                # every write. Erroring here bricked every pre-existing build.
                warnings.append(f"Missing phase {phase_id} in phases")
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
        for key in [
            "xcodegen", "fastlane", "ascConfigured", "axiom",
            "runtimeHost", "peerAi", "peerReviewAvailable",
        ]:
            if key not in environment:
                warnings.append(f"environment.{key} not set")

    return errors, warnings


def mutate_state_with_validation(
    path: Path,
    spec: dict[str, Any],
    mutator: Callable[[dict[str, Any]], None],
    *,
    validator: Callable[[dict[str, Any]], tuple[bool, list[str]]] | None = None,
) -> tuple[bool, list[str]]:
    """Read → (validate) → mutate → schema-check → write, all under the lock.

    `validator` re-checks transition preconditions against the FRESH state
    inside the write lock — a pre-validation done outside the lock can be
    invalidated by a concurrent writer between check and write (TOCTOU). On
    validator failure nothing is written and (False, messages) is returned;
    a successful write returns (True, []).
    """
    with _state_write_lock(path):
        state = load_state(path)
        if validator is not None:
            ok, messages = validator(state)
            if not ok:
                return False, messages
        next_state = copy.deepcopy(state)
        # Backfill phases the spec added after this state was written (e.g. phase
        # "2.5" landed without a schemaVersion bump): a newly-specced, never-run
        # phase is exactly "pending". Without this, every mutation on an older
        # build-state was rejected and there was no migration path.
        phases = next_state.get("phases")
        if isinstance(phases, dict):
            for phase_id in phase_ids(spec):
                phases.setdefault(phase_id, {"status": "pending"})
        mutator(next_state)
        errors, warnings = collect_schema_issues(spec, next_state)
        if errors:
            joined = "; ".join(errors)
            raise SystemExit(f"FATAL: refusing to write invalid build state: {joined}")
        # Promote a legacy schemaVersion in the same write: a state that was
        # backfilled and passed the current spec's validation is by definition
        # valid current schema — without this every mutation re-emits the
        # "legacy compat mode" WARN forever.
        spec_version = spec.get("schemaVersion")
        state_version = next_state.get("schemaVersion")
        if (
            isinstance(spec_version, int)
            and isinstance(state_version, int)
            and state_version < spec_version
        ):
            next_state["schemaVersion"] = spec_version
        save_state(path, next_state)
    for warning in warnings:
        print(f"WARN: {warning}")
    return True, []
