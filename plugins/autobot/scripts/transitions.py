#!/usr/bin/env python3
"""Phase status transitions, retry policy, and circuit breaker enforcement.

This module is the single place that decides whether a phase may move from
one status to another. The rules consume spec.transitions, spec.policies, and
the live build state; callers never re-implement them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from state_store import (
    load_state,
    mutate_state_with_validation,
    parse_key_value,
    utc_now,
)

__all__ = [
    "transition_map",
    "validate_transition_request",
    "circuit_breaker_tripped",
    "update_phase_status",
]


def transition_map(spec: dict[str, Any], phase: str) -> dict[str, list[str]]:
    mapping = {
        status: list(targets)
        for status, targets in spec.get("transitions", {}).get("default", {}).items()
    }
    for status, targets in spec.get("transitions", {}).get("overrides", {}).get(phase, {}).items():
        mapping[status] = list(targets)
    return mapping


def circuit_breaker_tripped(
    spec: dict[str, Any], state: dict[str, Any],
) -> tuple[bool, int, int, str]:
    """Return (tripped, current_failures, threshold, scope).

    'global' scope sums retryCount across all phases; 'perPhase' picks the max
    retryCount of any single phase. threshold ≤ 0 disables the breaker.
    """
    breaker = spec.get("policies", {}).get("circuitBreaker", {})
    threshold = int(breaker.get("maxConsecutivePhaseFailures", 0))
    scope = breaker.get("scope", "perPhase")
    if threshold <= 0:
        return False, 0, 0, scope
    phases = state.get("phases", {})
    if scope == "global":
        failures = sum(int(p.get("retryCount", 0)) for p in phases.values() if isinstance(p, dict))
    else:
        failures = max(
            (int(p.get("retryCount", 0)) for p in phases.values() if isinstance(p, dict)),
            default=0,
        )
    return failures >= threshold, failures, threshold, scope


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

    if target_status == "in_progress":
        tripped, failures, threshold, scope = circuit_breaker_tripped(spec, state)
        if tripped:
            return False, [
                f"REJECTED: circuit breaker tripped — {scope} retryCount={failures} ≥ {threshold}",
            ]

    suffix = " (explicit restart)" if allow_explicit_restart else ""
    return True, [f"OK: Phase {phase} {current_status} → {target_status}{suffix}"]


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
        spec, state, phase, target_status,
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
