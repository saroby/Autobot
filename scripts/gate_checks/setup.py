"""Phase 0 → 2 setup gates: environment, architecture, models, contracts.

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
import os
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


def check_environment_ready(proj: Path, app: str, state: dict) -> list[dict]:
    results = [
        _dir_exists(proj, "project_dir"),
        _dir_exists(proj / ".autobot", "autobot_dir"),
        _file_exists(proj / ".autobot" / "build-state.json", "build_state_file"),
    ]

    # Xcode CLI Tools — honor AUTOBOT_DISABLE_XCODEBUILD (CI / no-Xcode envs),
    # consistent with xcodebuild_runner.py. Degraded skip, not a hard fail.
    if os.environ.get("AUTOBOT_DISABLE_XCODEBUILD") == "1":
        results.append(_ok("xcode_cli_tools", False,
                           "skipped (AUTOBOT_DISABLE_XCODEBUILD=1) — DEGRADED",
                           skipped=True, degraded=True))
    else:
        ok, out = _run_cmd(["xcode-select", "-p"])
        results.append(_ok("xcode_cli_tools", ok, out if ok else "Xcode CLI Tools not installed"))

    # iOS Simulator runtime — honor AUTOBOT_DISABLE_SIMULATOR (CI / no-Xcode envs),
    # consistent with sim_runtime.py. Degraded skip so the gate still advances;
    # production (flag unset) keeps the live fail-fast probe.
    if os.environ.get("AUTOBOT_DISABLE_SIMULATOR") == "1":
        results.append(_ok("ios_simulator_runtime", False,
                           "skipped (AUTOBOT_DISABLE_SIMULATOR=1) — DEGRADED",
                           skipped=True, degraded=True))
    else:
        ok, out = _run_cmd(["xcrun", "simctl", "list", "runtimes"])
        has_ios = ok and "iOS" in out
        results.append(_ok("ios_simulator_runtime", has_ios,
                           "iOS runtime found" if has_ios else "No iOS Simulator runtime"))

    # python3
    ok, out = _run_cmd(["python3", "--version"])
    results.append(_ok("python3_available", ok, out if ok else "python3 not found"))

    # Disk space > 1GB
    try:
        import shutil
        usage = shutil.disk_usage(str(proj))
        free_gb = usage.free / (1024 ** 3)
        results.append(_ok("disk_space", free_gb > 1.0, f"{free_gb:.1f} GB free"))
    except OSError as exc:
        results.append(_ok("disk_space", False, f"cannot check: {exc}"))

    return results


def check_project_name_resolved(proj: Path, app: str, state: dict) -> list[dict]:
    ok = bool(re.match(r"^[A-Z][a-zA-Z0-9]*$", app))
    return [_ok("app_name_pattern", ok, f"appName='{app}'")]


def check_build_state_initialized(proj: Path, app: str, state: dict) -> list[dict]:
    bsf = proj / ".autobot" / "build-state.json"
    results = [_file_exists(bsf, "build_state_exists")]
    if bsf.is_file():
        try:
            data = load_json(bsf)
            has_keys = isinstance(data, dict) and "buildId" in data and "appName" in data
            results.append(_ok("build_state_schema", has_keys, "required fields present" if has_keys else "missing buildId/appName"))
        except (json.JSONDecodeError, OSError) as exc:
            results.append(_ok("build_state_schema", False, f"parse error: {exc}"))
    return results


def check_environment_recorded(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify that environment detection results are recorded in build-state.json."""
    env = state.get("environment", {})
    if not env:
        return [_ok("env_recorded", False, "environment object missing from build-state.json")]

    results = []
    for key in (
        "xcodegen", "fastlane", "ascConfigured", "axiom", "stitch",
        "runtimeHost", "peerAi", "peerReviewAvailable",
    ):
        present = key in env
        results.append(_ok(f"env_{key}", present,
                           f"{key}={env[key]}" if present else f"{key} not recorded"))
    return results


def check_architecture_document_exists(proj: Path, app: str, state: dict) -> list[dict]:
    arch = proj / ".autobot" / "architecture.md"
    results = [
        _file_nonempty(arch, "architecture_file"),
        _file_grep(arch, r"screen", "arch_screens"),
        _file_grep(arch, r"design.*direction|color.*palette|palette.*role", "arch_design_direction"),
        _file_grep(arch, r"layout.*personality|layout.*pattern", "arch_layout"),
        _file_grep(arch, r"integration|service.*layer|service.*protocol", "arch_services"),
        _file_grep(arch, r"privacy|file.timestamp|C617", "arch_privacy"),
    ]
    if state.get("backend_required"):
        results.extend([
            _file_grep(arch, r"backend.*require", "arch_backend"),
            _file_grep(arch, r"api.*contract", "arch_api_contract"),
            _file_grep(arch, r"ios.*config|xcconfig", "arch_ios_config"),
        ])
    return results


def check_design_direction_complete(proj: Path, app: str, state: dict) -> list[dict]:
    """Require the architect's look-and-feel contract, not just a mention."""
    arch = proj / ".autobot" / "architecture.md"
    if not arch.is_file():
        return [_ok("design_direction_architecture_file", False, f"{arch}")]
    content = arch.read_text(encoding="utf-8", errors="replace")
    required = [
        ("design_direction_heading", r"Design Direction"),
        ("app_personality_heading", r"App Personality"),
        ("color_palette_heading", r"Color Palette"),
        ("typography_heading", r"Typography(?: Style)?"),
        ("component_patterns_heading", r"Component Patterns"),
    ]
    return [
        _ok(label, _markdown_heading_present(content, pattern), pattern)
        for label, pattern in required
    ]


def check_models_exist(proj: Path, app: str, state: dict) -> list[dict]:
    # Models/ path is derived from the architect's writes in spec.fileOwnership,
    # so changing the spec moves this check automatically.
    spec = load_spec()
    architect_dirs = _agent_writes_dirs(spec, "architect", app)
    models_dir_rel = next((d for d in architect_dirs if d.endswith("/Models/")), f"{app}/Models/")
    models_dir = proj / models_dir_rel.rstrip("/")

    results = [_dir_has_swift(models_dir, "models_swift_files")]
    if models_dir.is_dir():
        for f in sorted(models_dir.glob("*.swift")):
            content = f.read_text(encoding="utf-8", errors="replace")
            has_import = bool(re.search(r"import\s+(SwiftData|Foundation)", content))
            results.append(_ok(f"import_{f.name}", has_import, f"{f.name} import"))
    return results


def check_service_protocols_exist(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / "Models" / "ServiceProtocols.swift", "service_protocols")]


def check_contracts_snapshot_saved(proj: Path, app: str, state: dict) -> list[dict]:
    snap = proj / ".autobot" / "contracts" / "phase-1-models"
    return [
        _dir_exists(snap, "snapshot_dir"),
        _dir_has_swift(snap, "snapshot_files"),
        _file_exists(proj / ".autobot" / "contracts" / "models.sha256", "checksum_file"),
    ]


def check_backend_required_consistent(proj: Path, app: str, state: dict) -> list[dict]:
    if not state.get("backend_required"):
        return [_ok("backend_skip", True, "backend_required=false", skipped=True)]
    results = [_file_exists(proj / app / "Models" / "APIContracts.swift", "api_contracts")]
    try:
        subprocess.run(["docker", "--version"], capture_output=True, timeout=5, check=True)
        results.append(_ok("docker_available", True, "docker installed"))
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        # Docker missing must NOT abort the whole build (the old hard fail meant
        # a backend_required idea produced nothing). Degrade instead: the iOS app
        # and the backend/ code are still generated; only the backend container is
        # left unverified. Capability Coverage tells the user it is pending.
        results.append(_ok(
            "docker_available", False,
            "docker NOT available — backend code is still generated but its container "
            "is unverified (DEGRADED). Install Docker Desktop to build/run the backend "
            "locally.",
            skipped=True, degraded=True,
        ))
    return results
