#!/usr/bin/env python3
"""advance-phase command logic — gate run + atomic phase mutation + log.

Returns an AdvanceResult so the CLI wrapper owns all stdout. This makes the
function unit-testable without subprocess plumbing and keeps cli.py as the
single place that prints user-facing text.

Atomicity guarantee:
  pre-validate the transition BEFORE running mutate_state_with_validation. If
  the transition is rejected (terminal-state restart not allowed, retries
  exhausted, circuit-breaker tripped, etc.), no state or log row is written.
  Once the mutation function executes, the write is final — gate evidence
  and phase status land in the same atomic step.

Soft-gate semantics:
  Gate 6→7 is soft. When a soft gate fails, the phase still advances (so
  Phase 7 can run) but state.gates[gate_id].status is recorded as
  "soft_failed". Resume logic that needs to detect "the build deployed but
  upload failed" reads gates[gate_id].status — there is no separate marker
  on the phase itself.
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from event_log import append_build_log
from gate_persistence import (
    build_gate_evidence,
    force_phase_in_progress,
    phase_id_for_alwaysrun,
    skip_pending_phases_except,
)
from gate_runner import format_text as format_gate_text
from gate_runner import run_gate as execute_gate
from spec_loader import load_spec
from state_store import (
    load_json,
    load_state,
    mutate_state_with_validation,
    parse_key_value,
    state_file_from_args,
    utc_now,
)
from transitions import (
    circuit_breaker_tripped,
    update_phase_status,
    validate_transition_request,
)


__all__ = ["AdvanceResult", "advance_phase", "render_advance_result"]


@dataclass
class AdvanceResult:
    """Pure value object describing an advance-phase outcome.

    The function returning this never prints; the CLI wrapper renders it.
    """
    return_code: int
    messages: list[str] = field(default_factory=list)
    gate_text: str | None = None
    gate_json: dict | None = None


def render_advance_result(result: AdvanceResult, *, output_format: str = "text") -> None:
    """CLI-side rendering of an AdvanceResult."""
    if output_format == "json" and result.gate_json is not None:
        print(json.dumps(result.gate_json, ensure_ascii=False, indent=2))
    elif result.gate_text:
        print(result.gate_text)
    for message in result.messages:
        print(message)


def advance_phase(args: argparse.Namespace) -> int:
    """CLI entrypoint — runs the core logic and renders + returns its result."""
    result = _advance_phase_core(args)
    render_advance_result(result, output_format=getattr(args, "format", "text"))
    return result.return_code


def _advance_phase_core(args: argparse.Namespace) -> AdvanceResult:
    out = AdvanceResult(return_code=0)
    spec = load_spec()
    phase = str(args.phase)
    project_dir = Path(args.project_dir).resolve()
    state_path = state_file_from_args(args)

    if not state_path.is_file():
        raise SystemExit(f"FATAL: build-state.json not found at {state_path}")

    state = load_state(state_path)
    app_name = args.app_name or state.get("appName", "")
    if not app_name:
        raise SystemExit("FATAL: --app-name required (or appName must exist in build-state.json)")

    phase_spec = spec.get("phases", {}).get(phase)
    if phase_spec is None:
        raise SystemExit(f"FATAL: unknown phase {phase}")
    gate_id = phase_spec.get("gate")
    timestamp = args.at or utc_now()

    # ── Phase has no outgoing gate (Phase 7) — simple completion path ──
    if gate_id is None:
        ok, messages, completed_at = update_phase_status(
            spec, state_path,
            phase=phase, target_status=args.status, at=timestamp,
            metadata_items=args.metadata,
        )
        out.messages.extend(messages)
        if not ok:
            out.return_code = 1
            return out
        event = {"completed": "complete", "fallback": "fallback", "skipped": "skip"}[args.status]
        append_build_log(
            project_dir, event, phase=phase, detail=args.detail,
            timestamp=completed_at, spec=spec,
        )
        out.messages.append(f"OK: phase {phase} marked {args.status} (no gate)")
        return out

    # ── Run the gate ──
    # When the caller has signalled an intentional fallback (`--status fallback`),
    # gate checks that branch on the phase status (`_is_fallback`) must see the
    # fallback context BEFORE evaluation — otherwise they relax their requirement
    # only after the gate has already rejected the build. Build-20260526-solos
    # Phase 2 was trapped here: ux-designer produced a text-only spec, --status
    # fallback was passed, but design_assets_exist_or_fallback evaluated against
    # the still-in_progress state and required PNGs that fallback intentionally
    # omits.
    gate_state = state
    if args.status == "fallback" or args.metadata:
        gate_state = copy.deepcopy(state)
    if args.status == "fallback":
        gate_state.setdefault("phases", {}).setdefault(phase, {"status": "pending"})["status"] = "fallback"
    if args.metadata:
        metadata = gate_state.setdefault("phases", {}).setdefault(phase, {"status": "pending"}).setdefault("metadata", {})
        for raw in args.metadata:
            key, value = parse_key_value(raw)
            metadata[key] = value
    gate_result = execute_gate(gate_id, project_dir, app_name, gate_state, spec)

    if args.format == "json":
        out.gate_json = gate_result
    else:
        out.gate_text = format_gate_text(gate_result)

    if gate_result.get("error"):
        raise SystemExit(f"FATAL: {gate_result['error']}")

    gate_passed = gate_result.get("passed", False)
    gate_soft = gate_result.get("soft", False)
    success_path = gate_passed or gate_soft

    # ── Pre-validate the transition before any write or log emission ──
    next_target = args.status if success_path else "failed"
    pre_state = load_state(state_path)
    pre_ok, pre_msgs = validate_transition_request(
        spec, pre_state, phase, next_target, allow_terminal_restart=False,
    )
    if not pre_ok:
        out.messages.extend(pre_msgs)
        out.return_code = 1
        return out

    gate_evidence = build_gate_evidence(spec, gate_id, gate_result, timestamp)
    gate_checks = gate_evidence["checks"]
    metadata_items = args.metadata or []

    # Pre-compute the input hash when the phase is about to succeed so the
    # mutator can stash it without re-reading the (now-mutated) state.
    # Best-effort: any failure here is non-fatal — the rest of the pipeline
    # still works, idempotent-resume just won't fast-skip this phase.
    input_hash_result: tuple[str, dict] | None = None
    if success_path:
        try:
            from input_hash import compute_phase_input_hash
            input_hash_result = compute_phase_input_hash(
                project_dir, spec, pre_state, phase,
            )
        except Exception:  # noqa: BLE001 — best-effort, must not crash advance
            input_hash_result = None

    def mutate(next_state: dict[str, Any]) -> None:
        next_state.setdefault("gates", {})[gate_id] = gate_evidence

        phase_state = next_state.setdefault("phases", {}).setdefault(phase, {"status": "pending"})
        phase_state["status"] = next_target

        if success_path:
            phase_state["completedAt"] = timestamp
            phase_state.pop("failedAt", None)
            phase_state.pop("skippedAt", None)
            phase_state.pop("error", None)
            # Success resets the retry counter (consecutive-failure breaker
            # semantics — see transitions.update_phase_status).
            phase_state.pop("retryCount", None)
            # Soft-gate failure information lives in gates[gate_id].status
            # (already written above as "soft_failed"); no per-phase mirror.

            # Record the input hash so /autobot:resume can skip this phase
            # next time if nothing upstream has changed (LOOP 17/26).
            if input_hash_result is not None:
                try:
                    from input_hash import mark_inputs
                    mark_inputs(
                        next_state, phase,
                        hash_value=input_hash_result[0],
                        manifest=input_hash_result[1],
                    )
                except Exception:  # noqa: BLE001
                    pass
        else:
            phase_state["failedAt"] = timestamp
            phase_state["error"] = f"gate {gate_id} failed"
            phase_state["retryCount"] = int(phase_state.get("retryCount", 0)) + 1

        if metadata_items:
            metadata = phase_state.setdefault("metadata", {})
            for raw in metadata_items:
                key, value = parse_key_value(raw)
                metadata[key] = value

    mutate_state_with_validation(state_path, spec, mutate)
    out.messages.extend(pre_msgs)

    append_build_log(
        project_dir,
        "gate_pass" if gate_passed else "gate_fail",
        phase=phase,
        detail={"gate": gate_id, "checks": gate_checks, "soft": bool(gate_soft)},
        timestamp=timestamp, spec=spec,
    )

    if success_path:
        event = {"completed": "complete", "fallback": "fallback", "skipped": "skip"}[args.status]
        append_build_log(
            project_dir, event, phase=phase, detail=args.detail,
            timestamp=timestamp, spec=spec,
        )
        suffix = f" (soft gate {gate_id} failed; gates['{gate_id}'].status=soft_failed)" if gate_soft and not gate_passed else ""
        out.messages.append(f"OK: phase {phase} marked {args.status}{suffix}")
        return out

    # Hard gate failure path.
    append_build_log(
        project_dir, "fail", phase=phase,
        detail={"error": f"gate {gate_id} failed", "gate": gate_id},
        timestamp=timestamp, spec=spec,
    )

    refreshed_state = load_json(state_path)
    tripped, failures, threshold, scope = circuit_breaker_tripped(spec, refreshed_state)
    if tripped:
        breaker_detail = {
            "scope": scope, "failures": failures, "threshold": threshold,
            "trippedOnPhase": phase,
        }
        append_build_log(
            project_dir, "circuit_open", phase=phase,
            detail=breaker_detail, timestamp=timestamp, spec=spec,
        )
        on_trip = spec.get("policies", {}).get("circuitBreaker", {}).get("onTrip")
        if on_trip == "skipToRetrospective":
            retro_id = phase_id_for_alwaysrun(spec)
            if retro_id is not None:
                skip_reason = f"circuit breaker tripped on phase {phase}"
                exempt = {retro_id, phase}
                skipped_ids = skip_pending_phases_except(
                    spec, state_path, exempt, timestamp, skip_reason,
                )
                for sid in skipped_ids:
                    append_build_log(
                        project_dir, "skip", phase=sid,
                        detail=skip_reason, timestamp=timestamp, spec=spec,
                    )
                force_phase_in_progress(spec, state_path, retro_id, timestamp)
                append_build_log(
                    project_dir, "skip", phase=retro_id,
                    detail=f"circuit breaker tripped on phase {phase}; auto-scheduled retrospective",
                    timestamp=timestamp, spec=spec,
                )
                skipped_msg = f", skipped phases={skipped_ids}" if skipped_ids else ""
                out.messages.append(
                    f"FAIL: phase {phase} marked failed (gate {gate_id}); "
                    f"circuit breaker tripped (failures={failures} ≥ {threshold}, scope={scope}); "
                    f"phase {retro_id} auto-scheduled in_progress{skipped_msg}"
                )
                out.return_code = 2
                return out
        out.messages.append(
            f"FAIL: phase {phase} marked failed (gate {gate_id}); "
            f"circuit breaker tripped (failures={failures} ≥ {threshold}, scope={scope}); "
            f"no auto-recovery configured"
        )
        out.return_code = 2
        return out

    out.messages.append(f"FAIL: phase {phase} marked failed (gate {gate_id} did not pass)")
    out.return_code = 1
    return out
