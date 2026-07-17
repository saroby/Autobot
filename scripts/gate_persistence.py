#!/usr/bin/env python3
"""Glue between gate execution (gate_runner.py) and durable state.

Three roles:
  1. record a standalone gate run into state.gates + build-log (run-gate CLI)
  2. helpers used by advance-phase (auto-recovery: schedule the always-run
     phase, find it by spec)
  3. circuit-breaker trip handling (handle_breaker_trip) shared by the
     advance-phase hard-gate failure path and the fail-phase command

advance-phase itself lives in phase_advance.py because it composes gate
execution + transition validation + state mutation + log emission. Keeping it
in its own module isolates that complexity from the rest of the gate-glue
helpers here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from event_log import append_build_log
from gate_runner import run_gate as execute_gate  # gate_runner has no in-tree deps
from state_store import load_json, mutate_state_with_validation

__all__ = [
    "build_gate_evidence",
    "execute_and_record_gate",
    "handle_breaker_trip",
    "phase_id_for_alwaysrun",
    "force_phase_in_progress",
    "skip_pending_phases_except",
]


def build_gate_evidence(
    spec: dict[str, Any], gate_id: str, gate_result: dict[str, Any], timestamp: str,
) -> dict[str, Any]:
    """Shape the dict that lands in state.gates[gate_id].

    Single source of truth for gate-evidence schema, used by both run-gate
    (standalone) and advance-phase (atomic gate+phase mutation).
    """
    passed = gate_result.get("passed", False)
    soft = gate_result.get("soft", False)
    status = (
        "failed" if (not passed and not soft)
        else "soft_failed" if (not passed)
        else "degraded" if gate_result.get("degraded")
        else "passed"
    )
    checks = {group["check"]: group["passed"] for group in gate_result.get("checks", [])}
    return {
        "status": status,
        "checkedAt": timestamp,
        "fromPhase": spec["gates"][gate_id].get("fromPhase"),
        "toPhase": spec["gates"][gate_id].get("toPhase"),
        "soft": bool(soft),
        "checks": checks,
        "detail": gate_result,
    }


def execute_and_record_gate(
    spec: dict[str, Any],
    state_path: Path,
    project_dir: Path,
    gate_id: str,
    app_name: str,
    *,
    timestamp: str,
    no_record: bool = False,
) -> dict[str, Any]:
    """Run the gate and record its evidence into state + build-log.

    Returns the raw gate result. Does not touch phase status — callers that
    want phase transitions tied to gate outcome use advance_phase in
    phase_advance.py.
    """
    state = load_json(state_path) if state_path.is_file() else {"phases": {}, "backend_required": False}
    result = execute_gate(gate_id, project_dir, app_name, state, spec)

    if no_record or "error" in result:
        return result

    evidence = build_gate_evidence(spec, gate_id, result, timestamp)

    def mutate(next_state: dict[str, Any]) -> None:
        next_state.setdefault("gates", {})[gate_id] = evidence

    mutate_state_with_validation(state_path, spec, mutate)
    append_build_log(
        project_dir,
        "gate_pass" if result["passed"] else "gate_fail",
        phase=spec["gates"][gate_id].get("fromPhase"),
        detail={"gate": gate_id, "checks": evidence["checks"], "soft": evidence["soft"]},
        timestamp=timestamp,
        spec=spec,
    )
    return result


def phase_id_for_alwaysrun(spec: dict[str, Any]) -> str | None:
    """Return the spec-declared always-run phase (typically Retrospective)."""
    for phase_id, phase_spec in spec.get("phases", {}).items():
        if phase_spec.get("alwaysRun"):
            return phase_id
    return None


def force_phase_in_progress(
    spec: dict[str, Any], state_path: Path, phase_id: str, timestamp: str,
) -> None:
    """Override transitions to start a phase regardless of dependency status.

    Used by circuit-breaker auto-recovery to schedule the retrospective even
    when prior phases are in failed/pending. Skips if the phase is already
    in_progress or has reached a terminal status.
    """

    def mutate(next_state: dict[str, Any]) -> None:
        phase_state = next_state.setdefault("phases", {}).setdefault(phase_id, {"status": "pending"})
        if phase_state.get("status") in {"in_progress", "completed", "fallback", "skipped"}:
            return
        phase_state["status"] = "in_progress"
        phase_state["startedAt"] = timestamp
        phase_state.pop("failedAt", None)
        phase_state.pop("error", None)

    mutate_state_with_validation(state_path, spec, mutate)


def handle_breaker_trip(
    spec: dict[str, Any],
    state_path: Path,
    project_dir: Path,
    phase: str,
    timestamp: str,
) -> str | None:
    """Circuit-breaker trip handling shared by every failure path.

    Checks the breaker against the CURRENT persisted state; if tripped, emits
    the `circuit_open` event and runs onTrip=skipToRetrospective auto-recovery
    (skip remaining phases, force the always-run phase in_progress). Returns a
    human-readable trip description, or None when the breaker is not tripped.

    Extracted from the advance-phase hard-gate failure path so fail-phase
    (the documented pre-gate failure command) trips identically — previously a
    fail-phase trip left no circuit_open marker and no scheduled retrospective.
    """
    # Local import: circuit_breaker_tripped is a pure (spec, state) function and
    # transitions depends only on state_store — no import cycle.
    from transitions import circuit_breaker_tripped

    state = load_json(state_path)
    tripped, failures, threshold, scope = circuit_breaker_tripped(spec, state)
    if not tripped:
        return None

    append_build_log(
        project_dir, "circuit_open", phase=phase,
        detail={
            "scope": scope, "failures": failures, "threshold": threshold,
            "trippedOnPhase": phase,
        },
        timestamp=timestamp, spec=spec,
    )
    trip_summary = f"circuit breaker tripped (failures={failures} ≥ {threshold}, scope={scope})"

    on_trip = spec.get("policies", {}).get("circuitBreaker", {}).get("onTrip")
    if on_trip == "skipToRetrospective":
        retro_id = phase_id_for_alwaysrun(spec)
        if retro_id is not None:
            skip_reason = f"circuit breaker tripped on phase {phase}"
            skipped_ids = skip_pending_phases_except(
                spec, state_path, {retro_id, phase}, timestamp, skip_reason,
            )
            for sid in skipped_ids:
                append_build_log(
                    project_dir, "skip", phase=sid,
                    detail=skip_reason, timestamp=timestamp, spec=spec,
                )
            # Force the always-run phase in_progress. Deliberately NO "skip"
            # event for it: skipping and scheduling the SAME phase would be a
            # contradictory audit trail. Its scheduling is recorded by the
            # circuit_open event + the in_progress state transition + the return
            # summary below.
            force_phase_in_progress(spec, state_path, retro_id, timestamp)
            skipped_msg = f", skipped phases={skipped_ids}" if skipped_ids else ""
            return f"{trip_summary}; phase {retro_id} auto-scheduled in_progress{skipped_msg}"
    return f"{trip_summary}; no auto-recovery configured"


def skip_pending_phases_except(
    spec: dict[str, Any], state_path: Path, exempt_phase_ids: set[str], timestamp: str,
    reason: str,
) -> list[str]:
    """Mark every pending/failed phase as skipped, except the exempt set.

    Used by circuit-breaker auto-recovery: after the breaker trips and the
    always-run phase is scheduled, the remaining incomplete phases should be
    explicitly skipped so resume logic does not try to re-enter them. Returns
    the list of phase IDs that were transitioned to skipped.
    """
    skipped: list[str] = []

    def mutate(next_state: dict[str, Any]) -> None:
        phases = next_state.setdefault("phases", {})
        for phase_id in spec.get("phases", {}):
            if phase_id in exempt_phase_ids:
                continue
            phase_state = phases.setdefault(phase_id, {"status": "pending"})
            current = phase_state.get("status")
            if current in {"completed", "fallback", "skipped", "in_progress"}:
                continue
            phase_state["status"] = "skipped"
            phase_state["skippedAt"] = timestamp
            phase_state["skipReason"] = reason
            phase_state.pop("error", None)
            skipped.append(phase_id)

    mutate_state_with_validation(state_path, spec, mutate)
    return skipped
