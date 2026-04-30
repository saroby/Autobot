#!/usr/bin/env python3
"""Pipeline spec loading + structural validation.

The spec at spec/pipeline.json is the single source of truth
for phases, gates, transitions, retry policies, and event/ownership schemas.
Every other runtime module reads through load_spec() so that schema upgrades
land in one place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"

__all__ = [
    "SPEC_PATH", "load_spec", "validate_spec",
    "schema_keys", "phase_ids", "resolve_app_template",
]


def resolve_app_template(template: str, app_name: str) -> str:
    """Substitute the ``{appName}`` placeholder used by spec.fileOwnership.

    Centralizing this rule means new placeholders (or a switch to a different
    delimiter) only land in one place. All gate / sandbox / snapshot runners
    funnel through here.
    """
    return template.replace("{appName}", app_name)


def load_spec() -> dict[str, Any]:
    try:
        with SPEC_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
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
        if gates[gate_id].get("fromPhase") != phase_id:
            raise SystemExit(
                f"FATAL: gate '{gate_id}' fromPhase={gates[gate_id].get('fromPhase')} "
                f"does not match phase {phase_id}"
            )

    for gate_id, gate_spec in gates.items():
        from_phase = gate_spec.get("fromPhase")
        to_phase = gate_spec.get("toPhase")
        if from_phase not in phases:
            raise SystemExit(f"FATAL: gate '{gate_id}' references unknown fromPhase '{from_phase}'")
        if to_phase not in phases:
            raise SystemExit(f"FATAL: gate '{gate_id}' references unknown toPhase '{to_phase}'")


def schema_keys(spec: dict[str, Any], section: str) -> list[str]:
    return list(spec.get("stateSchema", {}).get(section, []))


def phase_ids(spec: dict[str, Any]) -> list[str]:
    return list(spec.get("phases", {}).keys())
