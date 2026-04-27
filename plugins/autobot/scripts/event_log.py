#!/usr/bin/env python3
"""build-log.jsonl event validation + append.

The event taxonomy (event names and required/optional fields) is declared in
spec.logEvents and is the single SSOT. validate_log_event consults the spec;
append_build_log calls validate_log_event before writing. Callers that fail
to declare new events in the spec hit a FATAL here rather than producing
rows that no consumer can interpret.

Dependency rule:
  event_log may import spec_loader and state_store (one-way).
  state_store MUST NOT import event_log — see state_store docstring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spec_loader import load_spec
from state_store import utc_now

__all__ = ["validate_log_event", "append_build_log"]


_PRIMITIVE_TYPES = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "number": (int, float),
    "array": list,
    "object": dict,
}


def _check_detail_schema(schema: dict[str, Any], detail: Any, event: str) -> list[str]:
    """Minimal JSON-Schema-flavored validator for detail payloads.

    Supports: type (object/array/string/integer/number/boolean), required[],
    properties{} (recursive). Deliberately small — full JSON Schema would
    pull in a dependency. Anything not declared is allowed (additive
    forwards-compat).
    """
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        py_type = _PRIMITIVE_TYPES.get(expected)
        if py_type is None:
            errors.append(f"event '{event}' detailSchema declares unknown type '{expected}'")
            return errors
        # bool is a subclass of int; exclude bool from integer.
        if expected == "integer" and isinstance(detail, bool):
            errors.append(f"event '{event}' detail expected integer, got boolean")
            return errors
        if not isinstance(detail, py_type):
            errors.append(f"event '{event}' detail expected {expected}, got {type(detail).__name__}")
            return errors

    if expected == "object":
        for key in schema.get("required", []):
            if not isinstance(detail, dict) or key not in detail:
                errors.append(f"event '{event}' detail missing required key '{key}'")
        for key, sub_schema in schema.get("properties", {}).items():
            if isinstance(detail, dict) and key in detail:
                errors.extend(_check_detail_schema(sub_schema, detail[key], event))
    return errors


def validate_log_event(spec: dict[str, Any], event: str, fields: dict[str, Any]) -> list[str]:
    """Return a list of error messages; empty means the entry is well-formed."""
    log_events = spec.get("logEvents", {})
    if not log_events:
        return []  # spec did not declare events; skip validation
    descriptor = log_events.get(event)
    if descriptor is None:
        return [f"unknown event '{event}' (declare in spec.logEvents)"]
    errors: list[str] = []
    for required in descriptor.get("required", []):
        if fields.get(required) in (None, ""):
            errors.append(f"event '{event}' requires field '{required}'")
    allowed = set(descriptor.get("required", [])) | set(descriptor.get("optional", []))
    for present in ("phase", "agent", "detail"):
        if fields.get(present) not in (None, "") and present not in allowed:
            errors.append(f"event '{event}' does not allow field '{present}'")

    # Per-event detail structure check (only when detail is present and a
    # detailSchema was declared).
    detail_schema = descriptor.get("detailSchema")
    if detail_schema and fields.get("detail") not in (None, ""):
        errors.extend(_check_detail_schema(detail_schema, fields["detail"], event))
    return errors


def append_build_log(
    project_dir: Path,
    event: str,
    *,
    phase: str | None = None,
    detail: Any = None,
    agent: str | None = None,
    timestamp: str | None = None,
    spec: dict[str, Any] | None = None,
) -> None:
    # Always validate against the spec — never silently downgrade. If the spec
    # is unreadable we want callers to fail loudly rather than write
    # unvalidated rows.
    if spec is None:
        spec = load_spec()

    fields = {"phase": phase, "agent": agent, "detail": detail}
    errors = validate_log_event(spec, event, fields)
    if errors:
        raise SystemExit("FATAL: invalid build-log event: " + "; ".join(errors))

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
