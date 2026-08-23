"""Xcode project scaffolding + scaffold-build verification.

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


def check_xcodeproj_exists(proj: Path, app: str, state: dict) -> list[dict]:
    xcodeprojs = sorted(proj.glob("*.xcodeproj"))
    results = [_ok("xcodeproj_dir", len(xcodeprojs) > 0, f"{len(xcodeprojs)} .xcodeproj")]
    if xcodeprojs:
        results.append(_file_nonempty(xcodeprojs[0] / "project.pbxproj", "pbxproj"))
    results.extend([
        _file_exists(proj / app / "App" / f"{app}App.swift", "app_entry_point"),
        _dir_exists(proj / app / "Assets.xcassets", "assets_catalog"),
    ])
    return results


def check_privacy_manifest_exists(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / "PrivacyInfo.xcprivacy", "privacy_manifest")]


def check_app_icon_applied(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 3 must apply the source icon into the AppIcon.appiconset.

    The scaffold creates ``Contents.json`` automatically but it points at zero
    PNGs unless ``scripts/app-icon.sh apply`` has run. Past incident: BookMemo
    shipped with a faceless icon because the scaffold step skipped apply.
    """
    iconset = proj / app / "Assets.xcassets" / "AppIcon.appiconset"
    if not iconset.is_dir():
        return [_ok("app_icon_iconset_dir", False, f"MISSING: {iconset}")]
    pngs = sorted(iconset.glob("*.png"))
    if not pngs:
        return [_ok(
            "app_icon_applied", False,
            "AppIcon.appiconset has 0 PNGs — run scripts/app-icon.sh apply",
        )]
    return [_ok("app_icon_applied", True, f"{len(pngs)} icon PNG(s) in AppIcon.appiconset/")]


def check_entitlements_exists(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / f"{app}.entitlements", "entitlements")]


def check_scaffold_build_succeeded(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 3→4 — verify the empty scaffold app actually compiles.

    Skips silently when xcodebuild is unavailable (CI / non-macOS) so the gate
    still exists as a contract even when this machine cannot run it. The
    structured result is also stashed in `phases.3.metadata.scaffoldBuild` by
    the orchestrator so the run summary can show duration / log path.
    """
    # Local import avoids importing subprocess machinery for every gate run.
    from xcodebuild_runner import scaffold_build

    result = scaffold_build(proj, app)
    status = result.get("status")
    if status == "skipped":
        reason = result.get("skipReason", "unknown")
        return [_ok("scaffold_build", True, f"skipped: {reason}", skipped=True)]
    if status == "passed":
        return [_ok(
            "scaffold_build", True,
            f"xcodebuild build succeeded in {result.get('durationSeconds')}s",
        )]
    first_error = next((d for d in result.get("diagnostics") or [] if d["severity"] == "error"), None)
    if first_error:
        sig = f"{first_error['file']}:{first_error['line']}: {first_error['message']}"
    else:
        sig = (result.get("errorSignature") or "").splitlines()[0] if result.get("errorSignature") else "no stderr"
    return [_ok(
        "scaffold_build", False,
        f"xcodebuild build failed (exit {result.get('exitCode')}): {sig[:160]} — log: {result.get('logPath')}",
    )]


def check_gitignore_exists(proj: Path, app: str, state: dict) -> list[dict]:
    results = [_file_exists(proj / ".gitignore", "gitignore")]
    if state.get("backend_required"):
        results.extend([
            _file_grep(proj / "Debug.xcconfig", r"API_BASE_URL", "debug_xcconfig"),
            _file_grep(proj / "Release.xcconfig", r"API_BASE_URL", "release_xcconfig"),
            _file_grep(proj / ".gitignore", r"backend/\.env", "gitignore_backend_env"),
        ])
    return results
