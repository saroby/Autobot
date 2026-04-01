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


def check_environment_ready(proj: Path, app: str, state: dict) -> list[dict]:
    return [
        _dir_exists(proj / ".autobot", "autobot_dir"),
        _file_exists(proj / ".autobot" / "build-state.json", "build_state_file"),
    ]


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


def check_models_exist(proj: Path, app: str, state: dict) -> list[dict]:
    models_dir = proj / app / "Models"
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
    src = proj / app
    return [
        _dir_has_swift(src / "Views", "views_files"),
        _dir_has_swift(src / "ViewModels", "viewmodels_files"),
        _file_grep(src / "App" / f"{app}App.swift", r"\.modelContainer", "app_model_container"),
    ]


def check_services_exist(proj: Path, app: str, state: dict) -> list[dict]:
    return [_dir_has_swift(proj / app / "Services", "services_files")]


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
    # Check phase 5 metadata for build result
    p5 = state.get("phases", {}).get("5", {})
    meta = p5.get("metadata", {})
    recorded = meta.get("build_succeeded")
    if recorded is True:
        return [_ok("build_result", True, "Phase 5 metadata: build_succeeded=true")]
    # Fallback: scan build-log.jsonl for last build_attempt
    log_file = proj / ".autobot" / "build-log.jsonl"
    if log_file.is_file():
        last_event: dict | None = None
        for line in log_file.read_text(encoding="utf-8").strip().splitlines():
            try:
                ev = json.loads(line)
                if ev.get("event") == "build_attempt":
                    last_event = ev
            except json.JSONDecodeError:
                continue
        if last_event:
            detail = last_event.get("detail", "")
            ok = (isinstance(detail, dict) and detail.get("succeeded")) or (
                isinstance(detail, str) and "succeed" in detail.lower()
            )
            return [_ok("build_log_result", bool(ok), f"Last build_attempt: {detail}")]
    return [_ok("build_result", False, "No build success evidence found — record metadata.build_succeeded=true in Phase 5")]


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


# ── Registry ──

GATE_CHECKS: dict[str, Any] = {
    # Gate 0→1
    "environment_ready": check_environment_ready,
    "project_name_resolved": check_project_name_resolved,
    "build_state_initialized": check_build_state_initialized,
    # Gate 1→2
    "architecture_document_exists": check_architecture_document_exists,
    "models_exist": check_models_exist,
    "service_protocols_exist": check_service_protocols_exist,
    "contracts_snapshot_saved": check_contracts_snapshot_saved,
    "backend_required_consistent": check_backend_required_consistent,
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
}


# ── Gate execution engine ──


def run_gate(
    gate_id: str, project_dir: Path, app_name: str, state: dict, spec: dict,
) -> dict[str, Any]:
    gates = spec.get("gates", {})
    if gate_id not in gates:
        return {"gate": gate_id, "passed": False, "error": f"Unknown gate: {gate_id}", "checks": []}

    gate_spec = gates[gate_id]
    check_names = gate_spec.get("checks", [])
    soft = gate_spec.get("soft", False)

    all_results: list[dict] = []
    all_passed = True

    for name in check_names:
        fn = GATE_CHECKS.get(name)
        if fn is None:
            all_results.append({"check": name, "passed": False, "sub_checks": [],
                                "message": f"No implementation for '{name}'"})
            all_passed = False
            continue

        sub_checks = fn(project_dir, app_name, state)
        group_passed = all(r["passed"] or r.get("skipped", False) for r in sub_checks)
        if not group_passed:
            all_passed = False
        all_results.append({"check": name, "passed": group_passed, "sub_checks": sub_checks})

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


def cmd_list_checks(args: argparse.Namespace) -> int:
    spec = load_spec()

    if args.gate:
        gates = spec.get("gates", {})
        if args.gate not in gates:
            raise SystemExit(f"Unknown gate: {args.gate}")
        checks = gates[args.gate].get("checks", [])
        for name in checks:
            impl = "✓" if name in GATE_CHECKS else "✗ (no impl)"
            print(f"  {impl} {name}")
    else:
        for gate_id, gate_spec in sorted(spec.get("gates", {}).items()):
            soft = " [soft]" if gate_spec.get("soft") else ""
            print(f"Gate {gate_id}{soft}:")
            for name in gate_spec.get("checks", []):
                impl = "✓" if name in GATE_CHECKS else "✗"
                print(f"  {impl} {name}")
            print()

    missing = set()
    for gate_spec in spec.get("gates", {}).values():
        for name in gate_spec.get("checks", []):
            if name not in GATE_CHECKS:
                missing.add(name)
    if missing:
        print(f"WARNING: {len(missing)} unimplemented checks: {sorted(missing)}")
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
