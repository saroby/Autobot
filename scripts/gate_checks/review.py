"""Peer-review + Axiom-audit acceptance checks.

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from spec_loader import resolve_app_template  # noqa: E402

from ._helpers import (
    load_json,
    load_spec,
    _ok,
    _file_exists,
    _dir_exists,
    _dir_has_swift,
    _file_nonempty,
    _file_grep,
    _run_cmd,
    _markdown_heading_present,
    _agent_writes_dirs
)


def check_architecture_peer_review_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify a Phase-1 peer architecture review has been performed (or explicitly skipped).

    Bi-directional: the review runs whichever runtime is opposite the host.
    Reads phases.1.metadata.peerReview first (new generic format), falls back to
    phases.1.metadata.codexReview (legacy, codex-only).

    Policy lookup: policies.peerArchitectureReview, falling back to
    policies.codexArchitectureReview (deprecated alias).

    Acceptable verdicts:
      - "PASS"     → review passed
      - "skipped"  → peer CLI unavailable, or review explicitly disabled
      - missing    → if policy.enabled == false (backward compat)
    Rejected:
      - "FAIL"     → architect must re-run with hardViolations / blockingFindings addressed
      - "skipped" without skipReason → not auditable
    """
    spec = load_spec()
    policies = spec.get("policies", {})
    review_policy = policies.get("peerArchitectureReview") or policies.get("codexArchitectureReview", {})
    enabled = bool(review_policy.get("enabled", False))

    p1_metadata = state.get("phases", {}).get("1", {}).get("metadata", {})
    review = p1_metadata.get("peerReview") or p1_metadata.get("codexReview")

    if review is None:
        if not enabled:
            return [_ok("architecture_peer_review_disabled", True,
                        "peerArchitectureReview.enabled=false (backward compat skip)",
                        skipped=True)]
        return [_ok("architecture_peer_review_missing", False,
                    "Phase 1 peer review not run; invoke autobot-peer-review-bridge "
                    "(host=claude → codex-architecture-review.sh; host=codex → claude review)")]

    verdict = str(review.get("verdict", ""))
    attempt = review.get("attempt")
    skip_reason = review.get("skipReason")
    host = review.get("host", "unknown")
    peer = review.get("peer", "unknown")

    if verdict == "PASS":
        return [_ok("architecture_peer_review_pass", True,
                    f"{host}->{peer} verdict=PASS (attempt {attempt})")]
    if verdict == "skipped":
        if not skip_reason:
            return [_ok("architecture_peer_review_skipped_without_reason", False,
                        f"{host}->{peer} verdict=skipped but skipReason missing — "
                        "explicit skipReason required for audit")]
        return [_ok("architecture_peer_review_skipped", True,
                    f"{host}->{peer} skipped: {skip_reason}",
                    skipped=True)]
    blocking = review.get("blockingFindingsCount")
    if blocking is None:
        blocking = len(review.get("hardViolations", []) or review.get("blockingFindings", []) or [])
    return [_ok("architecture_peer_review_failed", False,
                f"{host}->{peer} verdict={verdict or 'unknown'} (attempt {attempt}, "
                f"{blocking} blocking findings) — fix and re-run")]


check_codex_review_acceptable = check_architecture_peer_review_acceptable


def check_axiom_critical_audit_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """Quality sidecar: read the Phase-5 Axiom critical audit if it ran.

    The local MVP path must finish when the app builds. Axiom improves
    confidence, but absent/broken/failing Axiom evidence is reported as
    DEGRADED instead of hard-failing Phase 5. Upload paths still reject a
    degraded Gate 5->6 verdict.
    """
    env = state.get("environment", {})
    axiom_installed = env.get("axiom") is True
    audit = (
        state.get("phases", {})
             .get("5", {})
             .get("metadata", {})
             .get("axiom_critical_audit")
    )

    qmax = bool(state.get("qualityMax"))

    def _degraded(check: str, message: str) -> list[dict]:
        return [_ok(
            check,
            False,
            message + " — quality sidecar DEGRADED (MVP build continues; shipping blocked)",
            skipped=True,
            degraded=True,
        )]

    if not axiom_installed:
        qnote = " — quality-max: install axiom for the critical audit" if qmax else ""
        if audit is None:
            return [_ok("axiom_audit_skipped_env", True,
                        f"environment.axiom=false; critical audit not required{qnote}",
                        skipped=True, degraded=qmax)]
        return [_ok("axiom_audit_recorded_without_env", True,
                    "metadata present though environment.axiom=false; trusting metadata",
                    skipped=True, degraded=qmax)]

    if audit is None:
        return _degraded(
            "axiom_audit_missing",
            "environment.axiom=true but phases.5.metadata.axiom_critical_audit absent",
        )

    ran = audit.get("ran")
    if ran is not True:
        return _degraded(
            "axiom_audit_not_run",
            "axiom_critical_audit.ran is not true; bridge invocation failed or was skipped",
        )

    findings_path_str = audit.get("findings_path") or audit.get("findingsPath")
    if findings_path_str:
        findings_path = proj / findings_path_str
        if not findings_path.exists():
            return _degraded(
                "axiom_findings_missing",
                f"axiom_critical_audit.findings_path={findings_path_str} does not exist on disk",
            )

    critical = audit.get("critical_count")
    if critical is None:
        critical = audit.get("criticalCount", 0)
    try:
        critical_int = int(critical)
    except (TypeError, ValueError):
        return _degraded(
            "axiom_critical_count_invalid",
            f"axiom_critical_audit.critical_count is not an integer: {critical!r}",
        )

    if critical_int > 0:
        return _degraded(
            "axiom_critical_present",
            f"axiom critical findings count={critical_int}; return to build-fix loop",
        )

    return [_ok("axiom_critical_clean", True,
                f"axiom critical findings count=0 (auditors={audit.get('auditors', [])})")]


_PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE = {
    "peer_invocation_failed",
    "peer_timeout",
    "peer_runtime_error",
    "peer_returned_invalid_output",
}


def check_peer_review_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """Quality sidecar: read Phase-5 opposite-runtime peer review if it ran.

    Accepted verdicts:
      - PASS: peer reviewed and found no blocking issue (findingsPath must exist on disk).
      - skipped: peer tool unavailable or invocation failed; build remains standalone.
        skipReason is REQUIRED. When environment.peerReviewAvailable=true, skipReason
        must be in the allowed runtime-failure allowlist.

    Invalid/missing/failing evidence is DEGRADED, not a hard fail. That keeps
    /autobot:mvp focused on producing a local app while upload paths still
    reject non-passed Gate 5->6 evidence.
    """
    review = (
        state.get("phases", {})
             .get("5", {})
             .get("metadata", {})
             .get("peerReview")
    )
    qmax = bool(state.get("qualityMax"))

    def _degraded(check: str, message: str) -> list[dict]:
        return [_ok(
            check,
            False,
            message + " — quality sidecar DEGRADED (MVP build continues; shipping blocked)",
            skipped=True,
            degraded=True,
        )]

    if review is None:
        env_available = state.get("environment", {}).get("peerReviewAvailable") is True
        if env_available or qmax:
            return _degraded(
                "peer_review_missing",
                "peer review not recorded; run autobot-peer-review-bridge before Gate 5->6",
            )
        return [_ok(
            "peer_review_not_available",
            True,
            "peer review not recorded and peer runtime not available; quality sidecar skipped",
            skipped=True,
        )]

    verdict = str(review.get("verdict", ""))
    host = str(review.get("host", "unknown"))
    peer = str(review.get("peer", "unknown"))

    if verdict == "PASS":
        findings_path_str = review.get("findingsPath") or review.get("findings_path")
        if findings_path_str:
            findings_path = proj / findings_path_str
            if not findings_path.exists():
                return _degraded(
                    "peer_review_findings_missing",
                    f"peerReview.findingsPath={findings_path_str} does not exist on disk — "
                    "PASS verdict without artifact is not auditable",
                )
        return [_ok("peer_review_pass", True, f"{host}->{peer} verdict=PASS")]

    if verdict == "skipped":
        reason = review.get("skipReason")
        if not reason:
            return _degraded(
                "peer_review_skipped_without_reason",
                f"{host}->{peer} verdict=skipped but skipReason missing — "
                "explicit skipReason required for audit",
            )
        env_available = state.get("environment", {}).get("peerReviewAvailable") is True
        if env_available and reason not in _PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE:
            return _degraded(
                "peer_review_skip_contradicts_env",
                f"environment.peerReviewAvailable=true but skipReason={reason!r} "
                f"is not a runtime failure. Allowed when available: "
                f"{sorted(_PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE)}",
            )
        # quality-max: a skipped peer review (tool unavailable or runtime failure)
        # is recorded DEGRADED so the build is not shippable until a real review ran.
        return [_ok("peer_review_skipped", True,
                    f"{host}->{peer} skipped: {reason}"
                    + (" — quality-max: peer review did not actually run" if qmax else ""),
                    skipped=True, degraded=qmax)]

    blocking = review.get("blockingFindingsCount")
    if blocking is None:
        blocking = len(review.get("blockingFindings", []) or [])
    return _degraded(
        "peer_review_failed",
        f"{host}->{peer} verdict={verdict or 'unknown'} ({blocking} blocking findings)",
    )
