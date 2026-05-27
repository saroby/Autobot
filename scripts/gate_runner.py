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
    for key in (
        "xcodegen", "fastlane", "ascConfigured", "axiom", "stitch",
        "runtimeHost", "peerAi", "peerReviewAvailable",
    ):
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


def _markdown_heading_present(content: str, title_pattern: str) -> bool:
    return bool(re.search(rf"(?im)^#+\s+{title_pattern}\s*$", content))


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


_IOS26_SYMBOLS = (
    (re.compile(r"\bimport\s+FoundationModels\b"), "FoundationModels framework"),
    (re.compile(r"\b@Generable\b"), "@Generable macro"),
    (re.compile(r"\bLanguageModelSession\b"), "LanguageModelSession"),
    (re.compile(r"\bSystemLanguageModel\b"), "SystemLanguageModel"),
    (re.compile(r"\.glassEffect\("), "Liquid Glass .glassEffect()"),
    (re.compile(r"\bGlassEffectContainer\b"), "GlassEffectContainer"),
    (re.compile(r"\bWritingToolsCoordinator\b"), "WritingToolsCoordinator"),
    (re.compile(r"\bAlarmKit\b"), "AlarmKit"),
)


def _parse_ios_major(target: str | None) -> int | None:
    """Extract the major version number from a deployment target like '26.0'."""
    if not isinstance(target, str):
        return None
    match = re.match(r"\s*(\d+)", target)
    return int(match.group(1)) if match else None


def _has_available_guard_above(lines: list[str], hit_line: int, *, window: int = 6) -> bool:
    """Return True if any of the `window` lines above contains an iOS 26 `#available` guard."""
    start = max(0, hit_line - window)
    for line in lines[start:hit_line]:
        if re.search(r"#available\([^)]*iOS\s+26", line):
            return True
        if re.search(r"@available\([^)]*iOS\s+26", line):
            return True
    return False


def check_app_intent_declared(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 1→2 — architect must promise something concrete enough to test.

    Soft when `app-intent.json` is absent (legacy build), strict when present
    but missing required fields.
    """
    from intent_spec import load_app_intent, validate_manifest

    intent = load_app_intent(proj)
    if intent is None:
        return [_ok(
            "app_intent_declared", True,
            ".autobot/app-intent.json absent — skipping (legacy build)",
            skipped=True,
        )]
    ok, problems = validate_manifest(proj)
    if ok:
        return [_ok(
            "app_intent_declared", True,
            f"promise='{intent.promise[:60]}', primaryCTA='{intent.primary_cta}', "
            f"{len(intent.required_anchors)} anchors",
        )]
    return [_ok(
        "app_intent_declared", False,
        f"app-intent.json invalid: {'; '.join(problems)}",
    )]


def check_intent_anchors_in_ui(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 4→5 — every anchor the architect promised must appear in the UI tree.

    Without this, the UI test target launched at Phase 5 cannot find the views
    it is supposed to assert against, and runtime-smoke can pass while the
    actual happy path is broken.
    """
    from intent_spec import find_unused_anchors, load_app_intent

    intent = load_app_intent(proj)
    if intent is None:
        return [_ok(
            "intent_anchors_in_ui", True,
            "app-intent.json absent — skipping",
            skipped=True,
        )]
    missing, present = find_unused_anchors(proj, app)
    if not missing:
        return [_ok(
            "intent_anchors_in_ui", True,
            f"all {len(present)} required anchors present in UI tree",
        )]
    return [_ok(
        "intent_anchors_in_ui", False,
        f"missing accessibility identifiers in UI: {', '.join(missing)} "
        f"(present: {', '.join(present) or 'none'})",
    )]


def check_ios_capability_safe(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify iOS 26+ APIs are either supported by the deployment target or
    properly `#available(iOS 26, *)` guarded.

    Soft when `architecture.json` is absent — Phase 1 may pre-date the
    capability manifest contract.
    """
    arch_json = proj / ".autobot" / "architecture.json"
    deployment_major: int | None = None
    if arch_json.is_file():
        try:
            data = load_json(arch_json)
            caps = data.get("iosCapabilities") if isinstance(data, dict) else None
            if isinstance(caps, dict):
                deployment_major = _parse_ios_major(caps.get("deploymentTarget"))
        except (json.JSONDecodeError, OSError):
            pass

    # No manifest → skip (architect output predates this gate).
    if deployment_major is None:
        return [_ok(
            "ios_capability_safe", True,
            "architecture.json missing iosCapabilities — skipping (legacy build)",
            skipped=True,
        )]

    # Deployment target already covers iOS 26 → no guards required.
    if deployment_major >= 26:
        return [_ok(
            "ios_capability_safe", True,
            f"deploymentTarget=iOS {deployment_major} — modern APIs always available",
        )]

    # Lower deployment target → every iOS 26+ symbol must be guarded.
    app_root = proj / app
    if not app_root.is_dir():
        return [_ok("ios_capability_safe", True, "no app source tree yet", skipped=True)]

    unguarded: list[str] = []
    for swift in app_root.rglob("*.swift"):
        try:
            text = swift.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            for pattern, label in _IOS26_SYMBOLS:
                if pattern.search(line) and not _has_available_guard_above(lines, idx):
                    unguarded.append(
                        f"{swift.relative_to(proj)}:{idx+1}: {label} unguarded "
                        f"(deploymentTarget=iOS {deployment_major})"
                    )
                    break  # one finding per line is enough

    if unguarded:
        sample = "; ".join(unguarded[:3])
        more = f" (+{len(unguarded)-3} more)" if len(unguarded) > 3 else ""
        return [_ok("ios_capability_safe", False, f"{sample}{more}")]
    return [_ok(
        "ios_capability_safe", True,
        f"all iOS 26+ symbol usages are #available-guarded (target=iOS {deployment_major})",
    )]


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


# Legacy alias retained so external forks of spec/pipeline.json that still
# reference codex_review_acceptable continue to work.
check_codex_review_acceptable = check_architecture_peer_review_acceptable


# ── Gate 2→3 checks ──


def _is_fallback(state: dict, phase: str) -> bool:
    return state.get("phases", {}).get(phase, {}).get("status") == "fallback"


def check_design_assets_exist_or_fallback(proj: Path, app: str, state: dict) -> list[dict]:
    if _is_fallback(state, "2"):
        return [_ok("design_assets_fallback", True, "Phase 2 fallback", skipped=True)]
    designs = proj / ".autobot" / "designs"
    matches = sorted(designs.glob("*.png")) if designs.is_dir() else []
    return [_ok("design_png_files", len(matches) > 0, f"{len(matches)} .png in designs/")]


def check_design_spec_sections_complete(proj: Path, app: str, state: dict) -> list[dict]:
    spec_path = proj / ".autobot" / "design-spec.md"
    if not spec_path.is_file():
        return [_ok("design_spec_file", False, f"{spec_path}")]
    content = spec_path.read_text(encoding="utf-8", errors="replace")
    required = [
        ("visual_concept_section", r"Visual Concept"),
        ("color_tokens_section", r"Color Tokens|Design Tokens.*Colors|Colors"),
        ("typography_section", r"Typography"),
        ("spacing_radius_section", r"Spacing\s*(?:&|and|/)?\s*(?:Radius|Layout)"),
        ("screen_layout_section", r"Screen[- ]by[- ]Screen Layout|Screen Designs|Screen Details"),
        ("interaction_feel_section", r"Interaction Feel|Interactions"),
        ("states_section", r"Empty(?:\s*[,/·&]\s*|\s+)Loading(?:\s*[,/·&]\s*|\s+)Error States|Empty States"),
    ]
    return [
        _ok(label, _markdown_heading_present(content, pattern), pattern)
        for label, pattern in required
    ]


# ── Gate 3→4 checks ──


def check_design_spec_json_valid(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 2→3 — the schema'd design-spec.json must be present (synthesized
    on the fly when absent) and pass validation.

    Synthesis path means the gate self-heals: if Phase 2 only produced prose
    (Stitch unavailable, no manual JSON), this check derives a deterministic
    palette + typography from architecture.md and writes design-spec.json so
    visual_contract / ui-builder have a reliable contract.
    """
    from design_spec_validator import ensure

    _path, payload, problems = ensure(proj, app_name=app, idea=state.get("idea", ""))
    if problems:
        return [_ok(
            "design_spec_json_valid", False,
            f"design-spec.json invalid: {'; '.join(problems[:3])}",
        )]
    info = (payload.get("_synthesizedFrom") or {}) if isinstance(payload, dict) else {}
    notes = []
    if info.get("fallbackPalette"):
        notes.append("fallback-palette")
    if info.get("architecture_md") or info.get("design_spec_md"):
        notes.append("derived-from-text")
    label = f" ({', '.join(notes)})" if notes else ""
    return [_ok(
        "design_spec_json_valid", True,
        f"category={payload.get('appCategory')} primary={payload.get('colorTokens',{}).get('primary')}{label}",
    )]


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


def _load_design_system_module(proj: Path, state: dict) -> str | None:
    """state 우선, 그 다음 architecture.json 에서 designSystemModule 을 읽는다."""
    arch_state = (state or {}).get("architecture") or {}
    mod = arch_state.get("designSystemModule")
    if mod:
        return mod
    arch_path = proj / ".autobot" / "architecture.json"
    if not arch_path.is_file():
        return None
    try:
        return json.loads(arch_path.read_text(encoding="utf-8")).get("designSystemModule")
    except (OSError, ValueError):
        return None


def check_design_system_package_exists(proj: Path, app: str, state: dict) -> list[dict]:
    module = _load_design_system_module(proj, state)
    if not module:
        return [_ok(
            "design_system_package_exists", False,
            "architecture.json.designSystemModule 누락 (architect 가 emit 해야 함)",
        )]
    pkg_root = proj / "Packages" / module
    pkg_swift = pkg_root / "Package.swift"
    if not pkg_swift.is_file():
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift 없음: {pkg_swift.relative_to(proj)}",
        )]
    content = pkg_swift.read_text(encoding="utf-8", errors="replace")
    if f'name: "{module}"' not in content:
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift 의 name 이 '{module}' 가 아님",
        )]
    return [_ok("design_system_package_exists", True, str(pkg_swift.relative_to(proj)))]


def check_design_system_tokens_exist(proj: Path, app: str, state: dict) -> list[dict]:
    module = _load_design_system_module(proj, state)
    if not module:
        return [_ok(
            "design_system_tokens_exist", False,
            "architecture.json.designSystemModule 누락",
        )]
    tokens_dir = proj / "Packages" / module / "Sources" / module / "Tokens"
    required = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]
    missing: list[str] = []
    empty: list[str] = []
    for name in required:
        p = tokens_dir / name
        if not p.is_file():
            missing.append(name)
            continue
        if p.stat().st_size == 0:
            empty.append(name)
    if missing:
        return [_ok(
            "design_system_tokens_exist", False,
            f"missing token files: {', '.join(missing)}",
        )]
    if empty:
        return [_ok(
            "design_system_tokens_exist", False,
            f"empty token files: {', '.join(empty)}",
        )]
    return [_ok(
        "design_system_tokens_exist", True,
        f"{len(required)} tokens present under {tokens_dir.relative_to(proj)}",
    )]


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


def check_no_tabbar_safearea_smells(proj: Path, app: str, state: dict) -> list[dict]:
    """Detect known tab-bar overlap regressions in SwiftUI Views.

    Past incidents (recurred twice): floating UI / scroll content gets covered
    by the system tab bar because a child view ignores the bottom safe area
    or uses hardcoded bottom padding to compensate for the tab bar height.

    Hits — flagged as violations:
      - `ignoresSafeArea(... .bottom ...)`               # bottom edge ignored
      - `ignoresSafeArea(.all)` / `ignoresSafeArea(.all, ...)`  # all edges
      - `.padding(.bottom, N)` where N >= 40            # likely tab-bar fudge

    The plain background pattern `.ignoresSafeArea()` (no args) is allowed.
    """
    views = proj / app / "Views"
    if not views.is_dir():
        return [_ok("tabbar_safearea_smell", True, "no Views/ dir", skipped=True)]

    pattern_bottom = re.compile(r"ignoresSafeArea\b[^)]*\.bottom")
    pattern_all = re.compile(r"ignoresSafeArea\(\s*\.all\b")
    pattern_padding = re.compile(r"\.padding\(\.bottom,\s*(\d+)\b")

    violations: list[str] = []
    for swift in views.rglob("*.swift"):
        try:
            for lineno, line in enumerate(swift.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                if pattern_bottom.search(line) or pattern_all.search(line):
                    violations.append(f"{swift.relative_to(proj)}:{lineno}: ignoresSafeArea bottom/all — use .safeAreaInset")
                m = pattern_padding.search(line)
                if m and int(m.group(1)) >= 40:
                    violations.append(f"{swift.relative_to(proj)}:{lineno}: .padding(.bottom, {m.group(1)}) — likely tab-bar fudge, use .safeAreaInset")
        except (OSError, UnicodeDecodeError):
            continue

    if violations:
        detail = "; ".join(violations[:5])
        if len(violations) > 5:
            detail += f"; (+{len(violations) - 5} more)"
        return [_ok("tabbar_safearea_smell", False, detail)]
    return [_ok("tabbar_safearea_smell", True, "no bottom-safearea anti-patterns found")]


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


def check_axiom_critical_audit_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """4-way branch over environment.axiom x phases.5.metadata.axiom_critical_audit.

    - axiom NOT installed + metadata absent -> PASS (skipped).
    - axiom installed     + metadata absent -> FAIL (bridge call missing).
    - axiom installed     + ran=true + criticalCount==0 + findingsPath exists -> PASS.
    - axiom installed     + ran=true + criticalCount>0                        -> FAIL (return to fix loop).
    - axiom installed     + ran=false                                         -> FAIL (broken bridge).
    """
    env = state.get("environment", {})
    axiom_installed = env.get("axiom") is True
    audit = (
        state.get("phases", {})
             .get("5", {})
             .get("metadata", {})
             .get("axiom_critical_audit")
    )

    if not axiom_installed:
        if audit is None:
            return [_ok("axiom_audit_skipped_env", True,
                        "environment.axiom=false; critical audit not required", skipped=True)]
        return [_ok("axiom_audit_recorded_without_env", True,
                    "metadata present though environment.axiom=false; trusting metadata", skipped=True)]

    if audit is None:
        return [_ok("axiom_audit_missing", False,
                    "environment.axiom=true but phases.5.metadata.axiom_critical_audit absent — "
                    "run autobot-axiom-bridge Mode 1 before Gate 5->6")]

    ran = audit.get("ran")
    if ran is not True:
        return [_ok("axiom_audit_not_run", False,
                    "axiom_critical_audit.ran is not true; bridge invocation failed or was skipped")]

    findings_path_str = audit.get("findings_path") or audit.get("findingsPath")
    if findings_path_str:
        findings_path = proj / findings_path_str
        if not findings_path.exists():
            return [_ok("axiom_findings_missing", False,
                        f"axiom_critical_audit.findings_path={findings_path_str} does not exist on disk")]

    critical = audit.get("critical_count")
    if critical is None:
        critical = audit.get("criticalCount", 0)
    try:
        critical_int = int(critical)
    except (TypeError, ValueError):
        return [_ok("axiom_critical_count_invalid", False,
                    f"axiom_critical_audit.critical_count is not an integer: {critical!r}")]

    if critical_int > 0:
        return [_ok("axiom_critical_present", False,
                    f"axiom critical findings count={critical_int}; return to build-fix loop")]

    return [_ok("axiom_critical_clean", True,
                f"axiom critical findings count=0 (auditors={audit.get('auditors', [])})")]


# Allowed skipReasons when peer tooling was advertised as available in environment.
# These reflect legitimate runtime failures rather than refusal to invoke the bridge.
_PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE = {
    "peer_invocation_failed",
    "peer_timeout",
    "peer_runtime_error",
    "peer_returned_invalid_output",
}


def check_peer_review_acceptable(proj: Path, app: str, state: dict) -> list[dict]:
    """Require Phase 5 to attempt the opposite-runtime peer review.

    Accepted verdicts:
      - PASS: peer reviewed and found no blocking issue (findingsPath must exist on disk).
      - skipped: peer tool unavailable or invocation failed; build remains standalone.
        skipReason is REQUIRED. When environment.peerReviewAvailable=true, skipReason
        must be in the allowed runtime-failure allowlist.
    Rejected:
      - missing: quality-engineer did not run the bridge.
      - FAIL: peer found blocking issues that must return to the build-fix loop.
      - skipped without skipReason: implicit skip — not auditable.
      - skipped with non-allowlist reason while peerReviewAvailable=true: contradiction.
    """
    review = (
        state.get("phases", {})
             .get("5", {})
             .get("metadata", {})
             .get("peerReview")
    )
    if review is None:
        return [_ok("peer_review_missing", False,
                    "peer review not recorded; run autobot-peer-review-bridge before Gate 5->6")]

    verdict = str(review.get("verdict", ""))
    host = str(review.get("host", "unknown"))
    peer = str(review.get("peer", "unknown"))

    if verdict == "PASS":
        findings_path_str = review.get("findingsPath") or review.get("findings_path")
        if findings_path_str:
            findings_path = proj / findings_path_str
            if not findings_path.exists():
                return [_ok("peer_review_findings_missing", False,
                            f"peerReview.findingsPath={findings_path_str} does not exist on disk — "
                            "PASS verdict without artifact is not auditable")]
        return [_ok("peer_review_pass", True, f"{host}->{peer} verdict=PASS")]

    if verdict == "skipped":
        reason = review.get("skipReason")
        if not reason:
            return [_ok("peer_review_skipped_without_reason", False,
                        f"{host}->{peer} verdict=skipped but skipReason missing — "
                        "explicit skipReason required for audit")]
        env_available = state.get("environment", {}).get("peerReviewAvailable") is True
        if env_available and reason not in _PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE:
            return [_ok("peer_review_skip_contradicts_env", False,
                        f"environment.peerReviewAvailable=true but skipReason={reason!r} "
                        f"is not a runtime failure. Allowed when available: "
                        f"{sorted(_PEER_REVIEW_ALLOWED_SKIP_WHEN_AVAILABLE)}")]
        return [_ok("peer_review_skipped", True,
                    f"{host}->{peer} skipped: {reason}", skipped=True)]

    blocking = review.get("blockingFindingsCount")
    if blocking is None:
        blocking = len(review.get("blockingFindings", []) or [])
    return [_ok("peer_review_failed", False,
                f"{host}->{peer} verdict={verdict or 'unknown'} ({blocking} blocking findings)")]


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


def check_composition_seam_intact(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify the Phase 3 composition seam (single @main, stubs, root) is intact
    before Phase 5 wires real repositories.

    Hard checks:
      - exactly one `@main` annotation across the app source tree (duplicates
        crash Phase 5 with "multiple files match the @main attribute")
      - `<AppName>/App/ServiceStubs.swift` exists (Preview seam)

    Soft check (skipped when artifact is missing — emitted by architect once
    `architecture.json` becomes the SSOT for Phase 3+5):
      - `.autobot/architecture.json` parses and has required fields
      - if `<AppName>/App/CompositionRoot.swift` exists, it is free of
        `fatalError(` and unfilled `// TODO:` markers in production paths
    """
    app_root = proj / app
    results: list[dict] = []

    # @main uniqueness — count occurrences across the app source tree.
    main_files: list[str] = []
    if app_root.is_dir():
        main_pattern = re.compile(r"^\s*@main\b")
        for swift in app_root.rglob("*.swift"):
            try:
                content = swift.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in content.splitlines():
                if main_pattern.match(line):
                    main_files.append(str(swift.relative_to(proj)))
                    break
    if len(main_files) == 1:
        results.append(_ok("single_main_entry", True, f"@main in {main_files[0]}"))
    elif len(main_files) == 0:
        results.append(_ok("single_main_entry", False, "no @main found in app source tree"))
    else:
        results.append(_ok(
            "single_main_entry", False,
            f"multiple @main entries: {', '.join(main_files)} — composition seam is broken",
        ))

    # ServiceStubs.swift presence (Preview seam — also re-checked at Gate 5→6).
    results.append(_file_exists(app_root / "App" / "ServiceStubs.swift", "service_stubs_present"))

    # architecture.json — soft until architect always emits it.
    arch_json = proj / ".autobot" / "architecture.json"
    if arch_json.is_file():
        try:
            data = load_json(arch_json)
            required = ("appName", "models", "serviceProtocols", "rootScreens")
            missing = [k for k in required if k not in data]
            if missing:
                results.append(_ok(
                    "architecture_json_schema", False,
                    f"architecture.json missing required keys: {', '.join(missing)}",
                ))
            else:
                results.append(_ok(
                    "architecture_json_schema", True,
                    f"architecture.json declares {len(data.get('models', []))} models, "
                    f"{len(data.get('serviceProtocols', []))} protocols",
                ))
        except (json.JSONDecodeError, OSError) as exc:
            results.append(_ok("architecture_json_schema", False, f"parse error: {exc}"))
    else:
        results.append(_ok(
            "architecture_json_schema", True,
            "architecture.json absent (legacy build — skipping schema check)",
            skipped=True,
        ))

    # CompositionRoot.swift — soft check, only when present.
    comp_root = app_root / "App" / "CompositionRoot.swift"
    if comp_root.is_file():
        content = comp_root.read_text(encoding="utf-8")
        offenders = []
        if re.search(r"\bfatalError\s*\(", content):
            offenders.append("fatalError(")
        if re.search(r"//\s*TODO\b", content):
            offenders.append("// TODO")
        if offenders:
            results.append(_ok(
                "composition_root_clean", False,
                f"CompositionRoot.swift contains {', '.join(offenders)} — production path must be filled",
            ))
        else:
            results.append(_ok("composition_root_clean", True, "no fatalError/TODO"))
    else:
        results.append(_ok(
            "composition_root_clean", True,
            "CompositionRoot.swift absent (legacy build — skipping)",
            skipped=True,
        ))
    return results


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
    "design_direction_complete": check_design_direction_complete,
    "models_exist": check_models_exist,
    "service_protocols_exist": check_service_protocols_exist,
    "contracts_snapshot_saved": check_contracts_snapshot_saved,
    "backend_required_consistent": check_backend_required_consistent,
    "codex_review_acceptable": check_codex_review_acceptable,
    "architecture_peer_review_acceptable": check_architecture_peer_review_acceptable,
    "ios_capability_safe": check_ios_capability_safe,
    "app_intent_declared": check_app_intent_declared,
    "intent_anchors_in_ui": check_intent_anchors_in_ui,
    # Gate 2→3
    "design_spec_sections_complete": check_design_spec_sections_complete,
    "design_assets_exist_or_fallback": check_design_assets_exist_or_fallback,
    "design_spec_json_valid": check_design_spec_json_valid,
    # Gate 3→4
    "xcodeproj_exists": check_xcodeproj_exists,
    "privacy_manifest_exists": check_privacy_manifest_exists,
    "entitlements_exists": check_entitlements_exists,
    "gitignore_exists": check_gitignore_exists,
    "scaffold_build_succeeded": check_scaffold_build_succeeded,
    "design_system_package_exists": check_design_system_package_exists,
    "design_system_tokens_exist": check_design_system_tokens_exist,
    # Gate 4→5
    "views_exist": check_views_exist,
    "services_exist": check_services_exist,
    "models_checksum_matches": check_models_checksum_matches,
    "backend_artifacts_exist_if_required": check_backend_artifacts_exist_if_required,
    "composition_seam_intact": check_composition_seam_intact,
    # Gate 5→6
    "build_succeeded": check_build_succeeded,
    "peer_review_acceptable": check_peer_review_acceptable,
    "axiom_critical_audit_acceptable": check_axiom_critical_audit_acceptable,
    "app_uses_real_repositories": check_app_uses_real_repositories,
    "runtime_smoke": check_runtime_smoke,
    "visual_contract": check_visual_contract,
    "metadata_readiness": check_metadata_readiness,
    "service_stubs_preserved": check_service_stubs_preserved,
    # Gate 6→7
    "deployment_attempt_recorded": check_deployment_attempt_recorded,
    # Gate 4→5 (added with fileOwnership SSOT)
    "sandbox_clean": check_sandbox_clean,
    "no_tabbar_safearea_smells": check_no_tabbar_safearea_smells,
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
    "command_success", "state_field_eq", "state_field_contains", "all",
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
