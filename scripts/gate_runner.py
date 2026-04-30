#!/usr/bin/env python3
"""Autobot gate runner — executes pipeline gate checks programmatically.

Usage:
    python3 gate_runner.py run-gate --gate "4->5" --app-name MyApp [--project-dir .]
    python3 gate_runner.py run-gate --gate "4->5" --app-name MyApp --format json
    python3 gate_runner.py list-checks
    python3 gate_runner.py list-checks --gate "1->2"
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from spec_loader import resolve_app_template  # noqa: E402


# ── JSON / Spec helpers ──


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_spec() -> dict[str, Any]:
    try:
        return load_json(SPEC_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FATAL: cannot load pipeline spec: {exc}") from exc


# ── Check primitives ──


def _ok(check: str, passed: bool, message: str, *, skipped: bool = False) -> dict[str, Any]:
    r: dict[str, Any] = {"check": check, "passed": passed, "message": message}
    if skipped:
        r["skipped"] = True
    return r


def _file_exists(path: Path, label: str) -> dict[str, Any]:
    return _ok(label, path.is_file(), f"{path}")


def _dir_exists(path: Path, label: str) -> dict[str, Any]:
    return _ok(label, path.is_dir(), f"{path}/")


def _dir_has_swift(directory: Path, label: str, *, min_count: int = 1) -> dict[str, Any]:
    matches = sorted(directory.glob("*.swift")) if directory.is_dir() else []
    return _ok(label, len(matches) >= min_count, f"{len(matches)} .swift in {directory.name}/")


def _file_nonempty(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        return _ok(label, False, f"MISSING: {path}")
    return _ok(label, path.stat().st_size > 0, f"{path.name} ({path.stat().st_size} bytes)")


def _file_grep(
    path: Path, pattern: str, label: str, *, expect: bool = True,
) -> dict[str, Any]:
    if not path.is_file():
        return _ok(label, False, f"MISSING: {path.name}")
    content = path.read_text(encoding="utf-8", errors="replace")
    found = bool(re.search(pattern, content, re.IGNORECASE))
    passed = found if expect else not found
    verb = "matched" if found else "no match"
    return _ok(label, passed, f"{verb} /{pattern}/ in {path.name}")


# ── Gate 0→1 checks ──


def _run_cmd(cmd: list[str], *, timeout: int = 10) -> tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except FileNotFoundError:
        return False, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"


def check_environment_ready(proj: Path, app: str, state: dict) -> list[dict]:
    results = [
        _dir_exists(proj, "project_dir"),
        _dir_exists(proj / ".autobot", "autobot_dir"),
        _file_exists(proj / ".autobot" / "build-state.json", "build_state_file"),
    ]

    # Xcode CLI Tools
    ok, out = _run_cmd(["xcode-select", "-p"])
    results.append(_ok("xcode_cli_tools", ok, out if ok else "Xcode CLI Tools not installed"))

    # iOS Simulator runtime
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
    for key in ("xcodegen", "fastlane", "ascConfigured", "stitch"):
        present = key in env
        results.append(_ok(f"env_{key}", present,
                           f"{key}={env[key]}" if present else f"{key} not recorded"))
    return results


# ── Gate 1→2 checks ──


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


def _agent_writes_dirs(spec: dict, agent: str, app: str) -> list[str]:
    """Return the directories (paths ending '/') that the agent owns per spec."""
    cfg = spec.get("fileOwnership", {}).get("agents", {}).get(agent, {})
    return [resolve_app_template(p, app) for p in cfg.get("writes", []) if p.endswith("/")]


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
        results.append(_ok("docker_available", False, "docker NOT available"))
    return results


def check_codex_review_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify a codex architecture review has been performed (or explicitly skipped).

    Reads phases.1.metadata.codexReview written by scripts/codex-architecture-review.sh.
    Acceptable verdicts:
      - "PASS"     → review passed
      - "skipped"  → codex CLI unavailable, or review explicitly disabled
      - missing    → if policy.codexArchitectureReview.enabled == false (backward compat)
    Rejected:
      - "FAIL"     → architect must re-run with hardViolations addressed
    """
    spec = load_spec()
    review_policy = spec.get("policies", {}).get("codexArchitectureReview", {})
    enabled = bool(review_policy.get("enabled", False))

    review = (
        state.get("phases", {})
             .get("1", {})
             .get("metadata", {})
             .get("codexReview")
    )

    if review is None:
        if not enabled:
            return [_ok("codex_review_disabled", True,
                        "codexArchitectureReview.enabled=false (backward compat skip)",
                        skipped=True)]
        return [_ok("codex_review_missing", False,
                    "codex review not run; invoke scripts/codex-architecture-review.sh after architect dispatch")]

    verdict = str(review.get("verdict", ""))
    attempt = review.get("attempt")
    skip_reason = review.get("skipReason")

    if verdict == "PASS":
        return [_ok("codex_review_pass", True,
                    f"verdict=PASS (attempt {attempt})")]
    if verdict == "skipped":
        return [_ok("codex_review_skipped", True,
                    f"skipped: {skip_reason or 'no reason recorded'}",
                    skipped=True)]
    hard_count = len(review.get("hardViolations", []) or [])
    return [_ok("codex_review_failed", False,
                f"verdict={verdict or 'unknown'} (attempt {attempt}, "
                f"{hard_count} hard violations) — fix and re-run")]


# ── Gate 2→3 checks ──


def _is_fallback(state: dict, phase: str) -> bool:
    return state.get("phases", {}).get(phase, {}).get("status") == "fallback"


def check_design_spec_exists_or_fallback(proj: Path, app: str, state: dict) -> list[dict]:
    if _is_fallback(state, "2"):
        return [_ok("design_spec_fallback", True, "Phase 2 fallback", skipped=True)]
    return [_file_exists(proj / ".autobot" / "design-spec.md", "design_spec")]


def check_design_assets_exist_or_fallback(proj: Path, app: str, state: dict) -> list[dict]:
    if _is_fallback(state, "2"):
        return [_ok("design_assets_fallback", True, "Phase 2 fallback", skipped=True)]
    designs = proj / ".autobot" / "designs"
    matches = sorted(designs.glob("*.png")) if designs.is_dir() else []
    return [_ok("design_png_files", len(matches) > 0, f"{len(matches)} .png in designs/")]


# ── Gate 3→4 checks ──


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


def check_entitlements_exists(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / f"{app}.entitlements", "entitlements")]


def check_gitignore_exists(proj: Path, app: str, state: dict) -> list[dict]:
    results = [_file_exists(proj / ".gitignore", "gitignore")]
    if state.get("backend_required"):
        results.extend([
            _file_grep(proj / "Debug.xcconfig", r"API_BASE_URL", "debug_xcconfig"),
            _file_grep(proj / "Release.xcconfig", r"API_BASE_URL", "release_xcconfig"),
            _file_grep(proj / ".gitignore", r"backend/\.env", "gitignore_backend_env"),
        ])
    return results


# ── Gate 4→5 checks ──


def check_views_exist(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify ui-builder produced the directories spec marks as its writes.

    Iterates over fileOwnership.agents.ui-builder.writes that end with '/' so
    the check follows whatever the spec declares (Views/, ViewModels/, App/
    today; trivially extensible).
    """
    spec = load_spec()
    dirs = _agent_writes_dirs(spec, "ui-builder", app)
    swift_dirs = [d for d in dirs if d.split("/")[-2] in {"Views", "ViewModels"}]
    results: list[dict] = []
    for rel in swift_dirs:
        label = rel.split("/")[-2].lower() + "_files"
        results.append(_dir_has_swift(proj / rel.rstrip("/"), label))
    # App entrypoint is part of ui-builder's writes too.
    results.append(_file_grep(proj / app / "App" / f"{app}App.swift",
                              r"\.modelContainer", "app_model_container"))
    return results


def check_services_exist(proj: Path, app: str, state: dict) -> list[dict]:
    spec = load_spec()
    dirs = _agent_writes_dirs(spec, "data-engineer", app)
    services_dir_rel = next((d for d in dirs if d.endswith("/Services/")), f"{app}/Services/")
    return [_dir_has_swift(proj / services_dir_rel.rstrip("/"), "services_files")]


def check_models_checksum_matches(proj: Path, app: str, state: dict) -> list[dict]:
    script = SCRIPT_DIR / "snapshot-contracts.sh"
    try:
        result = subprocess.run(
            ["bash", str(script), "verify", "--app-name", app, "--project-dir", str(proj)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return [_ok("models_checksum", True, "Models/ integrity verified")]
        if result.returncode == 2:
            return [_ok("models_checksum", False, "Models/ snapshot missing")]
        if result.returncode == 3:
            return [_ok("models_checksum", False, "Models/ checksum MISMATCH — restore needed")]
        return [_ok("models_checksum", False, f"verify exit {result.returncode}: {result.stderr.strip()}")]
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return [_ok("models_checksum", False, f"cannot run verify: {exc}")]


def check_backend_artifacts_exist_if_required(proj: Path, app: str, state: dict) -> list[dict]:
    if not state.get("backend_required"):
        return [_ok("backend_artifacts_skip", True, "backend not required", skipped=True)]
    backend = proj / "backend"
    return [
        _dir_exists(backend, "backend_dir"),
        _file_exists(backend / "Dockerfile", "dockerfile"),
        _file_exists(backend / "docker-compose.yml", "docker_compose"),
        _file_exists(backend / "app" / "main.py", "backend_main"),
    ]


# ── Gate 5→6 checks ──


def check_build_succeeded(proj: Path, app: str, state: dict) -> list[dict]:
    """Truth source: phases.5.metadata.build_succeeded only.

    The Phase 5 build flow (quality-engineer / autobot-integration-build skill)
    is required to record this via:
      pipeline.sh advance-phase --phase 5 --metadata build_succeeded=true
    or the equivalent set-phase-status call. build-log.jsonl is audit-only and
    must not influence gate decisions.
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


def check_app_uses_real_repositories(proj: Path, app: str, state: dict) -> list[dict]:
    entry = proj / app / "App" / f"{app}App.swift"
    return [
        _file_grep(entry, r"Stub", "no_stubs_in_app", expect=False),
        _file_grep(entry, r"Repository|Service\(", "has_real_services"),
        _file_grep(entry, r"ModelContainer", "has_model_container"),
    ]


def check_service_stubs_preserved(proj: Path, app: str, state: dict) -> list[dict]:
    return [_file_exists(proj / app / "App" / "ServiceStubs.swift", "stubs_for_preview")]


# ── Gate 6→7 checks ──


def check_deployment_attempt_recorded(proj: Path, app: str, state: dict) -> list[dict]:
    deploy = proj / ".autobot" / "deploy-status.json"
    results = [_file_exists(deploy, "deploy_status_file")]
    if deploy.is_file():
        try:
            data = load_json(deploy)
            has_result = "archive_path" in data or "upload_success" in data
            results.append(_ok("deploy_has_result", has_result, "has archive_path or upload_success" if has_result else "missing result fields"))
        except (json.JSONDecodeError, OSError):
            results.append(_ok("deploy_has_result", False, "deploy-status.json parse error"))
    return results


# ── Sandbox enforcement (Gate 4→5) ──


def check_sandbox_clean(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify Phase 4 finished with zero sandbox violations across all agents."""
    phase_state = state.get("phases", {}).get("4", {})
    sandbox = phase_state.get("sandbox", {})
    violations = sandbox.get("violations", [])
    agents_seen = sandbox.get("agentsVerified", [])

    results: list[dict] = []
    if not agents_seen:
        results.append(_ok(
            "sandbox_recorded", False,
            "No sandbox.agentsVerified — agent-sandbox.sh after must run for each Phase 4 agent",
        ))
        return results

    results.append(_ok(
        "sandbox_recorded", True,
        f"agents verified: {', '.join(sorted(agents_seen))}",
    ))
    if violations:
        sample = violations[0] if isinstance(violations[0], str) else json.dumps(violations[0], ensure_ascii=False)
        results.append(_ok(
            "sandbox_violations", False,
            f"{len(violations)} violation(s); first: {sample}",
        ))
    else:
        results.append(_ok("sandbox_violations", True, "0 violations"))
    return results


# ── Registry ──

GATE_CHECKS: dict[str, Any] = {
    # Gate 0→1
    "environment_ready": check_environment_ready,
    "project_name_resolved": check_project_name_resolved,
    "build_state_initialized": check_build_state_initialized,
    "environment_recorded": check_environment_recorded,
    # Gate 1→2
    "architecture_document_exists": check_architecture_document_exists,
    "models_exist": check_models_exist,
    "service_protocols_exist": check_service_protocols_exist,
    "contracts_snapshot_saved": check_contracts_snapshot_saved,
    "backend_required_consistent": check_backend_required_consistent,
    "codex_review_acceptable": check_codex_review_acceptable,
    # Gate 2→3
    "design_spec_exists_or_fallback": check_design_spec_exists_or_fallback,
    "design_assets_exist_or_fallback": check_design_assets_exist_or_fallback,
    # Gate 3→4
    "xcodeproj_exists": check_xcodeproj_exists,
    "privacy_manifest_exists": check_privacy_manifest_exists,
    "entitlements_exists": check_entitlements_exists,
    "gitignore_exists": check_gitignore_exists,
    # Gate 4→5
    "views_exist": check_views_exist,
    "services_exist": check_services_exist,
    "models_checksum_matches": check_models_checksum_matches,
    "backend_artifacts_exist_if_required": check_backend_artifacts_exist_if_required,
    # Gate 5→6
    "build_succeeded": check_build_succeeded,
    "app_uses_real_repositories": check_app_uses_real_repositories,
    "service_stubs_preserved": check_service_stubs_preserved,
    # Gate 6→7
    "deployment_attempt_recorded": check_deployment_attempt_recorded,
    # Gate 4→5 (added with fileOwnership SSOT)
    "sandbox_clean": check_sandbox_clean,
}


# ── Declarative descriptor evaluation ──


def _get_state_path(state: dict, dotted: str) -> tuple[bool, Any]:
    """Walk a dotted path through state. Returns (found, value)."""
    cursor: Any = state
    for part in dotted.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return False, None
    return True, cursor


def _evaluate_when(when: dict | None, state: dict) -> tuple[bool, str]:
    """Returns (should_run, skip_reason). Empty/None when always runs."""
    if not when:
        return True, ""

    if "backend_required" in when:
        expected = bool(when["backend_required"])
        actual = bool(state.get("backend_required", False))
        if actual != expected:
            return False, f"backend_required={actual}"

    if "phase_status_in" in when:
        cfg = when["phase_status_in"]
        phase_id = str(cfg.get("phase"))
        allowed = set(cfg.get("values", []))
        actual = state.get("phases", {}).get(phase_id, {}).get("status", "pending")
        if actual not in allowed:
            return False, f"phase {phase_id} status={actual} not in {sorted(allowed)}"

    if "phase_status_not_in" in when:
        cfg = when["phase_status_not_in"]
        phase_id = str(cfg.get("phase"))
        denied = set(cfg.get("values", []))
        actual = state.get("phases", {}).get(phase_id, {}).get("status", "pending")
        if actual in denied:
            return False, f"phase {phase_id} status={actual} is in skip set {sorted(denied)}"

    return True, ""


def _evaluate_descriptor(
    desc: dict, project_dir: Path, app: str, state: dict,
) -> list[dict]:
    """Convert a declarative descriptor into a list of sub-check results.

    Recognized types: file_exists, dir_exists, dir_has_swift, file_grep,
    command_success, state_field_eq, all (group), procedural (registry hook).
    """
    label = desc.get("label", desc.get("type", "unnamed"))
    when = desc.get("when")
    should_run, skip_reason = _evaluate_when(when, state)
    if not should_run:
        return [_ok(label, True, f"skipped ({skip_reason})", skipped=True)]

    dtype = desc.get("type")

    if dtype == "file_exists":
        path = project_dir / resolve_app_template(desc["path"], app)
        return [_file_exists(path, label)]

    if dtype == "dir_exists":
        path = project_dir / resolve_app_template(desc["path"], app)
        return [_dir_exists(path, label)]

    if dtype == "dir_has_swift":
        path = project_dir / resolve_app_template(desc["dir"], app)
        return [_dir_has_swift(path, label, min_count=int(desc.get("min_count", 1)))]

    if dtype == "file_grep":
        path = project_dir / resolve_app_template(desc["path"], app)
        return [_file_grep(path, desc["pattern"], label, expect=bool(desc.get("expect", True)))]

    if dtype == "command_success":
        cmd_template = desc.get("cmd") or []
        cmd = [resolve_app_template(part, app) for part in cmd_template]
        ok, out = _run_cmd(cmd, timeout=int(desc.get("timeout", 10)))
        return [_ok(label, ok, out if out else ("ok" if ok else "command failed"))]

    if dtype == "state_field_eq":
        field = desc["field"]
        expected = desc["equals"]
        found, value = _get_state_path(state, field)
        if not found:
            msg = desc.get("missing_message", f"{field} not found")
            return [_ok(label, False, msg)]
        if value == expected:
            return [_ok(label, True, f"{field}={value}")]
        return [_ok(label, False, f"{field}={value} expected={expected}")]

    if dtype == "state_field_contains":
        field = desc["field"]
        required_values = desc.get("contains", [])
        found, value = _get_state_path(state, field)
        if not found or not isinstance(value, list):
            return [_ok(label, False, desc.get("missing_message",
                f"{field} not found or not a list"))]
        missing = [v for v in required_values if v not in value]
        if missing:
            return [_ok(label, False, f"{field} missing entries: {missing}")]
        return [_ok(label, True, f"{field} contains all of {required_values}")]

    if dtype == "all":
        children = desc.get("checks", [])
        results: list[dict] = []
        for child in children:
            results.extend(_evaluate_descriptor(child, project_dir, app, state))
        return results

    if dtype == "procedural":
        name = desc.get("name", label)
        fn = GATE_CHECKS.get(name)
        if fn is None:
            return [_ok(label, False, f"No procedural impl for '{name}'")]
        return fn(project_dir, app, state)

    return [_ok(label, False, f"Unknown descriptor type: {dtype}")]


def _normalize_check(check: Any) -> dict:
    """Accept legacy string form or descriptor object."""
    if isinstance(check, str):
        return {"type": "procedural", "name": check, "label": check}
    if isinstance(check, dict):
        return check
    raise ValueError(f"unsupported check entry: {check!r}")


def _check_label(check: Any) -> str:
    if isinstance(check, str):
        return check
    if isinstance(check, dict):
        return check.get("label") or check.get("name") or check.get("type", "unnamed")
    return str(check)


# ── Gate execution engine ──


def run_gate(
    gate_id: str, project_dir: Path, app_name: str, state: dict, spec: dict,
) -> dict[str, Any]:
    gates = spec.get("gates", {})
    if gate_id not in gates:
        return {"gate": gate_id, "passed": False, "error": f"Unknown gate: {gate_id}", "checks": []}

    gate_spec = gates[gate_id]
    raw_checks = gate_spec.get("checks", [])
    soft = gate_spec.get("soft", False)

    all_results: list[dict] = []
    all_passed = True

    for raw in raw_checks:
        descriptor = _normalize_check(raw)
        label = descriptor.get("label") or descriptor.get("name") or descriptor.get("type", "unnamed")
        sub_checks = _evaluate_descriptor(descriptor, project_dir, app_name, state)
        group_passed = all(r["passed"] or r.get("skipped", False) for r in sub_checks)
        if not group_passed:
            all_passed = False
        all_results.append({"check": label, "passed": group_passed, "sub_checks": sub_checks})

    return {"gate": gate_id, "passed": all_passed, "soft": soft, "checks": all_results}


# ── Output formatting ──


def format_text(result: dict) -> str:
    lines: list[str] = []
    status = "PASS" if result["passed"] else ("SOFT FAIL" if result.get("soft") else "FAIL")
    lines.append(f"Gate {result['gate']}: {status}")
    lines.append("")

    for group in result.get("checks", []):
        mark = "PASS" if group["passed"] else "FAIL"
        lines.append(f"  [{mark}] {group['check']}")
        for sub in group.get("sub_checks", []):
            if sub.get("skipped"):
                icon = "⊘"
            elif sub["passed"]:
                icon = "✓"
            else:
                icon = "✗"
            lines.append(f"    {icon} {sub['check']}: {sub['message']}")

    if "error" in result:
        lines.append(f"\n  ERROR: {result['error']}")
    return "\n".join(lines)


# ── CLI ──


def cmd_run_gate(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()

    state_path = project_dir / ".autobot" / "build-state.json"
    if state_path.is_file():
        state = load_json(state_path)
    else:
        state = {"phases": {}, "backend_required": False}

    app_name = args.app_name or state.get("appName", "")
    if not app_name:
        raise SystemExit("FATAL: --app-name required (or appName must exist in build-state.json)")

    result = run_gate(args.gate, project_dir, app_name, state, spec)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))

    return 0 if result["passed"] else (0 if result.get("soft") else 1)


_DECLARATIVE_TYPES = {
    "file_exists", "dir_exists", "dir_has_swift", "file_grep",
    "command_success", "state_field_eq", "all",
}


def _check_status(check: Any) -> str:
    desc = _normalize_check(check)
    dtype = desc.get("type")
    if dtype in _DECLARATIVE_TYPES:
        return "✓"
    if dtype == "procedural":
        return "✓" if desc.get("name") in GATE_CHECKS else "✗ (no impl)"
    return f"? ({dtype})"


def cmd_list_checks(args: argparse.Namespace) -> int:
    spec = load_spec()

    target_gates = (
        {args.gate: spec["gates"][args.gate]}
        if args.gate
        else dict(sorted(spec.get("gates", {}).items()))
    )
    if args.gate and args.gate not in spec.get("gates", {}):
        raise SystemExit(f"Unknown gate: {args.gate}")

    for gate_id, gate_spec in target_gates.items():
        soft = " [soft]" if gate_spec.get("soft") else ""
        if not args.gate:
            print(f"Gate {gate_id}{soft}:")
        for check in gate_spec.get("checks", []):
            status = _check_status(check)
            label = _check_label(check)
            print(f"  {status} {label}")
        if not args.gate:
            print()

    missing = []
    for gate_spec in spec.get("gates", {}).values():
        for check in gate_spec.get("checks", []):
            desc = _normalize_check(check)
            if desc.get("type") == "procedural" and desc.get("name") not in GATE_CHECKS:
                missing.append(desc["name"])
    if missing:
        print(f"WARNING: {len(missing)} unimplemented procedural checks: {sorted(set(missing))}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autobot gate runner")
    sub = parser.add_subparsers(dest="command", required=True)

    rg = sub.add_parser("run-gate", help="Execute all checks for a gate")
    rg.add_argument("--gate", required=True, help='Gate ID, e.g. "4->5"')
    rg.add_argument("--app-name", help="App name (reads from build-state.json if omitted)")
    rg.add_argument("--project-dir", default=".")
    rg.add_argument("--format", choices=["text", "json"], default="text")
    rg.set_defaults(func=cmd_run_gate)

    lc = sub.add_parser("list-checks", help="List gate checks and their implementation status")
    lc.add_argument("--gate", help="Show checks for a specific gate only")
    lc.set_defaults(func=cmd_list_checks)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
