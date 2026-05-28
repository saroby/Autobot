"""Final-build verification: build, runtime, visual contract, metadata.

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


def check_build_succeeded(proj: Path, app: str, state: dict) -> list[dict]:
    """Truth source: phases.5.metadata.build_succeeded only.

    The Phase 5 build flow (quality-engineer / autobot-integration-build skill)
    is required to record this via:
      pipeline.sh advance-phase --phase 5 --metadata build_succeeded=true
    build-log.jsonl is audit-only and must not influence gate decisions.
    """
    p5 = state.get("phases", {}).get("5", {})
    meta = p5.get("metadata", {})
    recorded = meta.get("build_succeeded")
    if recorded is True:
        return [_ok("build_result", True, "phases.5.metadata.build_succeeded=true")]
    if recorded is False:
        return [_ok("build_result", False, "phases.5.metadata.build_succeeded=false")]
    return [_ok(
        "build_result", False,
        "phases.5.metadata.build_succeeded missing — Phase 5 must record build outcome via metadata",
    )]


def check_visual_contract(proj: Path, app: str, state: dict) -> list[dict]:
    """Compare the runtime screenshot against the design-spec palette/anchors.

    Skipped when no screenshot is available yet (runtime_smoke also skipped) or
    when no palette can be derived. Otherwise it catches blank screens, broken
    root views, and "design said warm coral, app shipped system blue" regressions.
    """
    from visual_contract import evaluate

    result = evaluate(proj)
    status = result.get("status")
    if status == "skipped":
        return [_ok(
            "visual_contract", True,
            f"skipped: {result.get('skipReason', 'unknown')}",
            skipped=True,
        )]
    if status == "passed":
        match = result.get("paletteMatch")
        if match:
            extra = f" — dominant matches '{match['closestToken']}' (ΔE={match['deltaE']})"
        else:
            extra = " — no palette tokens declared, structural checks only"
        return [_ok(
            "visual_contract", True,
            f"screenshot OK{extra} ({result.get('notes')})",
        )]
    return [_ok(
        "visual_contract", False,
        f"visual contract violated: {result.get('reason', 'unknown')}",
    )]


def check_runtime_smoke(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 5→6 — boot a simulator, install the .app, launch it, confirm the
    process stays alive a few seconds, and capture a screenshot.

    `simctl_unavailable` / `app_artifact_missing` / `no_ios_simulator_available`
    are treated as `skipped` (the gate still records the check exists).
    Hard failures (boot/install/launch/process-death) fail the gate.
    """
    from sim_runtime import smoke

    result = smoke(proj, app)
    status = result.get("status")
    if status == "skipped":
        return [_ok(
            "runtime_smoke", True,
            f"skipped: {result.get('skipReason', 'unknown')}",
            skipped=True,
        )]
    if status == "passed":
        screenshot = result.get("screenshotPath") or "no screenshot"
        return [_ok(
            "runtime_smoke", True,
            f"app launched on {result.get('udidSource')} — {result.get('processDetail')} — screenshot: {screenshot}",
        )]
    return [_ok(
        "runtime_smoke", False,
        f"runtime smoke failed: {result.get('reason', 'unknown')}",
    )]


def check_metadata_readiness(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — App Store / TestFlight metadata is ready before archive.

    Skipped on the /autobot:mvp path (no ASC) so local builds aren't blocked;
    hard-required on the /autobot:testflight path (ascConfigured=true).
    """
    from metadata_validator import evaluate

    env = state.get("environment") or {}
    result = evaluate(proj, asc_configured=bool(env.get("ascConfigured")))
    status = result.get("status")
    if status == "skipped":
        return [_ok(
            "metadata_readiness", True,
            f"skipped: {result.get('skipReason', 'unknown')}",
            skipped=True,
        )]
    if status == "passed":
        counts = result.get("screenshotCounts") or {}
        total_shots = sum(counts.values())
        return [_ok(
            "metadata_readiness", True,
            f"locale={result.get('locale')} category={result.get('category')} "
            f"age={result.get('age_rating')} export={result.get('export_compliance')} "
            f"screenshots={total_shots}",
        )]
    return [_ok(
        "metadata_readiness", False,
        f"metadata not ready for upload: {result.get('reason', 'unknown')}",
    )]


def check_app_uses_real_repositories(proj: Path, app: str, state: dict) -> list[dict]:
    entry = proj / app / "App" / f"{app}App.swift"
    return [
        _file_grep(entry, r"Stub", "no_stubs_in_app", expect=False),
        _file_grep(entry, r"Repository|Service\(", "has_real_services"),
        _file_grep(entry, r"ModelContainer", "has_model_container"),
    ]


def check_service_stubs_preserved(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / "App" / "ServiceStubs.swift", "stubs_for_preview")]
