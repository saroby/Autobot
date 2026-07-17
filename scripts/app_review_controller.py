#!/usr/bin/env python3
"""Versioned, resumable controller for the App Review orchestration phases.

The controller owns ordering, state transitions, and artifact reconciliation.
Content-producing agents/skills remain executors: they ask ``next``, perform the
reported action, then call ``complete`` or ``fail`` with evidence.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from state_store import try_load_state, write_json

SCHEMA_VERSION = 1
PHASE_ORDER = ("0", "0b", "A", "B", "C", "D1", "D2", "H", "E", "F", "G")
DEPENDENCIES = {
    phase: (() if index == 0 else (PHASE_ORDER[index - 1],))
    for index, phase in enumerate(PHASE_ORDER)
}
ACTIONS = {
    "0": "validate_build_and_credentials",
    "0b": "ensure_app_registered",
    "A": "derive_marketing_context",
    "B": "generate_and_upload_metadata",
    "C": "write_screenshot_plan",
    "D1": "capture_raw_screenshots",
    "D2": "compose_store_screenshots",
    "H": "register_homepage_soft_failure",
    "E": "upload_screenshots",
    "F": "ensure_current_binary_uploaded",
    "G": "submit_for_review",
}
SUCCESS_RESULTS = {
    "0b": {"created", "already_exists"},
    "B": {"uploaded", "completed", "success"},
    "H": {
        "registered", "already_exists", "no_op", "skipped", "failed",
        "committed_no_push", "dry_run",
    },
    "E": {"uploaded", "already_uploaded", "success"},
    "F": {"uploaded", "already_uploaded"},
    "G": {"submitted", "already_in_review"},
}
MAX_PHASE_ATTEMPTS = 3
# Failures that retrying can never fix (SKILL.md failure matrix): halt at once.
NON_RETRYABLE_REASONS = {
    "name_collision",
    "bundle_id_taken",
    "asc_session_expired",
    "asc_permission_denied",
    # Bad/expired ASC API credentials — the deliver scripts (upload-metadata.sh,
    # submit-for-review.sh, upload-screenshots.sh) all emit reason=auth_failed;
    # retrying the same credentials only burns attempts.
    "auth_failed",
    # upload.sh: on the first attempt ASC already holds this bundle version, so
    # the binary must be bumped + re-archived — a retry of the same build cannot
    # resolve it.
    "build_number_conflict",
}
STATUS_FILES = {
    "0b": "register-status.json",
    "B": "metadata-upload-status.json",
    "H": "homepage-status.json",
    "E": "screenshot-upload-status.json",
    "F": "upload-status.json",
    "G": "review-submit-status.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(project: Path) -> Path:
    return project / ".autobot" / "app-review-state.json"


def _read_json(path: Path) -> dict:
    return try_load_state(path) or {}


def _write(project: Path, state: dict) -> None:
    write_json(_path(project), state)


@contextmanager
def _controller_lock(project: Path):
    path = project / ".autobot" / ".app-review-state.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _build_state(project: Path) -> dict:
    state = _read_json(project / ".autobot" / "build-state.json")
    if not state:
        raise ValueError(".autobot/build-state.json is missing or invalid; run /autobot:mvp first")
    phase5 = ((state.get("phases") or {}).get("5") or {}).get("status")
    if phase5 != "completed":
        raise ValueError(f"Phase 5 must be completed before App Review (status={phase5!r})")
    if not state.get("buildId") or not state.get("bundleId"):
        raise ValueError("buildId and bundleId are required in build-state.json")
    return state


def initialize(project: Path) -> dict:
    build = _build_state(project)
    existing = _read_json(_path(project))
    identity_matches = (
        existing.get("schemaVersion") == SCHEMA_VERSION
        and existing.get("buildId") == build.get("buildId")
        and existing.get("bundleId") == build.get("bundleId")
    )
    if identity_matches:
        return reconcile(project, existing)
    phases = {phase: {"status": "pending"} for phase in PHASE_ORDER}
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "buildId": build["buildId"],
        "bundleId": build["bundleId"],
        "appName": build.get("appName"),
        "displayName": build.get("displayName"),
        "createdAt": _now(),
        "updatedAt": _now(),
        "phases": phases,
    }
    _write(project, state)
    return state


def _dependencies_complete(state: dict, phase: str) -> bool:
    return all(
        ((state.get("phases") or {}).get(dependency) or {}).get("status") == "completed"
        for dependency in DEPENDENCIES[phase]
    )


def _content_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    for path in sorted(files, key=lambda item: str(item)):
        digest.update(str(path).encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _binary_identity_matches(project: Path, build: dict, status: dict) -> bool:
    if status.get("result") not in SUCCESS_RESULTS["F"]:
        return False
    if status.get("buildId") != build.get("buildId"):
        return False
    if status.get("bundleId") != build.get("bundleId"):
        return False
    input_hash = (((build.get("phases") or {}).get("5") or {}).get("inputHash"))
    if not input_hash or status.get("inputManifestHash") != input_hash:
        return False
    archive_status = _read_json(project / ".autobot" / "archive-status.json")
    return bool(
        archive_status.get("buildId") == build.get("buildId")
        and archive_status.get("bundleId") == build.get("bundleId")
        and archive_status.get("archiveSha256")
        and archive_status.get("archiveSha256") == status.get("archiveSha256")
    )


def _artifact_evidence(project: Path, phase: str, build: dict) -> dict | None:
    autobot = project / ".autobot"
    if phase in STATUS_FILES:
        path = autobot / STATUS_FILES[phase]
        status = _read_json(path)
        if phase == "F":
            valid = _binary_identity_matches(project, build, status)
        elif phase == "B":
            metadata = project / "fastlane" / "metadata"
            valid = (
                status.get("result") in SUCCESS_RESULTS[phase]
                and (metadata / "app_store_rating_config.json").is_file()
                and any(metadata.glob("*/*.txt"))
            )
        elif phase == "G":
            upload_status = _read_json(autobot / STATUS_FILES["F"])
            valid = (
                status.get("result") in SUCCESS_RESULTS[phase]
                and status.get("buildId") == build.get("buildId")
                and (status.get("bundleId") or status.get("bundle_id")) == build.get("bundleId")
                and status.get("artifactSha256")
                and status.get("artifactSha256") == upload_status.get("artifactSha256")
            )
        else:
            valid = status.get("result") in SUCCESS_RESULTS[phase]
        if not valid:
            return None
        evidence = {"path": str(path.relative_to(project)), "status": status}
        if phase == "B":
            evidence["contentDigest"] = _content_digest([project / "fastlane" / "metadata"])
        elif phase == "E":
            evidence["contentDigest"] = _content_digest([project / "fastlane" / "screenshots"])
        return evidence
    if phase == "A" and (project / "app-marketing-context.md").is_file():
        return {
            "path": "app-marketing-context.md",
            "contentDigest": _content_digest([project / "app-marketing-context.md"]),
        }
    if phase == "C" and (autobot / "screenshot-plan.md").is_file():
        return {
            "path": ".autobot/screenshot-plan.md",
            "contentDigest": _content_digest([autobot / "screenshot-plan.md"]),
        }
    if phase == "D1":
        files = list((project / "marketing").glob("*/*.png"))
        return {
            "path": "marketing",
            "pngCount": len(files),
            "contentDigest": _content_digest(files),
        } if len(files) >= 5 else None
    if phase == "D2":
        files = list((project / "fastlane" / "screenshots").glob("*/*.png"))
        return {
            "path": "fastlane/screenshots",
            "pngCount": len(files),
            "contentDigest": _content_digest(files),
        } if len(files) >= 20 else None
    return None


def reconcile(project: Path, state: dict) -> dict:
    build = _build_state(project)
    if state.get("buildId") != build.get("buildId"):
        raise ValueError("App Review state belongs to a different buildId; initialize a new run")
    dirty = False
    for phase in PHASE_ORDER[1:]:
        block = state["phases"][phase]
        if not _dependencies_complete(state, phase):
            continue
        evidence = _artifact_evidence(project, phase, build)
        if block.get("status") == "completed":
            if evidence == block.get("evidence"):
                continue
            start = PHASE_ORDER.index(phase)
            for invalidated in PHASE_ORDER[start:]:
                state["phases"][invalidated] = {"status": "pending"}
            dirty = True
            break
        if evidence is not None:
            block.update({"status": "completed", "completedAt": _now(), "evidence": evidence})
            dirty = True
    if dirty:
        state["updatedAt"] = _now()
        _write(project, state)
    return state


def next_phase(state: dict) -> dict:
    for phase in PHASE_ORDER:
        block = (state.get("phases") or {}).get(phase) or {}
        if block.get("status") == "completed" or not _dependencies_complete(state, phase):
            continue
        # Retry ceiling mirrors the main engine's circuit breaker (3 strikes).
        # A halted phase terminates the run; reconcile still promotes it to
        # completed if valid evidence appears (legitimate out-of-band recovery).
        if block.get("status") == "halted" or block.get("attempts", 0) >= MAX_PHASE_ATTEMPTS:
            return {
                "phase": phase,
                "action": "halted",
                "status": block.get("status", "failed"),
                "reason": block.get("reason"),
            }
        return {"phase": phase, "action": ACTIONS[phase], "status": block.get("status", "pending")}
    return {"phase": None, "action": "complete", "status": "completed"}


def claim_next_phase(project: Path, state: dict) -> dict:
    selected = next_phase(state)
    phase = selected.get("phase")
    if phase is None or selected.get("action") == "halted":
        return selected
    block = state["phases"][phase]
    lease = block.get("claimExpiresAt")
    if block.get("status") == "in_progress" and isinstance(lease, str):
        try:
            if datetime.fromisoformat(lease) > datetime.now(timezone.utc):
                return {"phase": phase, "action": "busy", "status": "in_progress"}
        except ValueError:
            pass
    token = uuid.uuid4().hex
    block.update({
        "status": "in_progress",
        "claimToken": token,
        "claimedAt": _now(),
        "claimExpiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    })
    state["updatedAt"] = _now()
    _write(project, state)
    return {**selected, "status": "in_progress", "claimToken": token}


def _require_claim(state: dict, phase: str, claim_token: str | None) -> None:
    block = (state.get("phases") or {}).get(phase) or {}
    if block.get("status") != "in_progress" or not claim_token:
        raise ValueError(f"phase {phase} is not claimed")
    if block.get("claimToken") != claim_token:
        raise ValueError(f"phase {phase} claim token does not match")


def complete_phase(
    project: Path,
    state: dict,
    phase: str,
    *,
    evidence: dict,
    claim_token: str | None = None,
) -> dict:
    if phase not in PHASE_ORDER:
        raise ValueError(f"unknown App Review phase: {phase}")
    if not _dependencies_complete(state, phase):
        raise ValueError(f"dependencies are not complete for phase {phase}")
    _require_claim(state, phase, claim_token)
    if phase == "0":
        from doctor import run_doctor

        doctor_result = run_doctor(project, "ship")
        if doctor_result.get("status") == "blocked":
            raise ValueError(
                "ship doctor is blocked: "
                + json.dumps(doctor_result, ensure_ascii=False, separators=(",", ":"))
            )
        evidence = {"doctor": doctor_result}
    else:
        build = _build_state(project)
        canonical_evidence = _artifact_evidence(project, phase, build)
        if canonical_evidence is None:
            raise ValueError(f"phase {phase} artifact contract is not satisfied")
        evidence = canonical_evidence
    state["phases"][phase] = {"status": "completed", "completedAt": _now(), "evidence": evidence}
    state["updatedAt"] = _now()
    _write(project, state)
    return state


def fail_phase(
    project: Path,
    state: dict,
    phase: str,
    *,
    reason: str,
    claim_token: str | None = None,
) -> dict:
    if phase not in PHASE_ORDER:
        raise ValueError(f"unknown App Review phase: {phase}")
    _require_claim(state, phase, claim_token)
    attempts = (state["phases"].get(phase) or {}).get("attempts", 0) + 1
    status = "failed"
    if reason in NON_RETRYABLE_REASONS or attempts >= MAX_PHASE_ATTEMPTS:
        status = "halted"
    state["phases"][phase] = {
        "status": status,
        "failedAt": _now(),
        "reason": reason,
        "attempts": attempts,
    }
    state["updatedAt"] = _now()
    _write(project, state)
    return state


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "status", "next", "complete", "fail", "reconcile"))
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--phase")
    parser.add_argument("--evidence", default="{}")
    parser.add_argument("--reason", default="unspecified failure")
    parser.add_argument("--claim-token")
    args = parser.parse_args()
    project = Path(args.project_dir).resolve()
    with _controller_lock(project):
        state = initialize(project) if args.command == "init" else _read_json(_path(project))
        if not state:
            raise SystemExit("ERROR: app-review state missing; run init")
        if args.command in {"status", "reconcile"}:
            result = reconcile(project, state)
        elif args.command == "next":
            state = reconcile(project, state)
            result = claim_next_phase(project, state)
        elif args.command == "complete":
            if not args.phase:
                parser.error("complete requires --phase")
            result = complete_phase(
                project,
                state,
                args.phase,
                evidence=json.loads(args.evidence),
                claim_token=args.claim_token,
            )
        elif args.command == "fail":
            if not args.phase:
                parser.error("fail requires --phase")
            result = fail_phase(
                project,
                state,
                args.phase,
                reason=args.reason,
                claim_token=args.claim_token,
            )
        else:
            result = state
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
