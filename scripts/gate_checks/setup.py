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
    _agent_writes_dirs,
    strip_swift_noncode,
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

    # Disk space > 1GB. Hermetic CI can skip the host-capacity probe just like
    # the Xcode/simulator probes; production keeps the fail-fast default.
    if os.environ.get("AUTOBOT_DISABLE_DISK_CHECK") == "1":
        results.append(_ok(
            "disk_space", False,
            "skipped (AUTOBOT_DISABLE_DISK_CHECK=1) — DEGRADED",
            skipped=True, degraded=True,
        ))
    else:
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
        "xcodegen", "fastlane", "ascConfigured", "axiom",
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
        # Signature Layout: the app-specific layout contract that prevents visual
        # homogeneity (every app looking like one of 4 molds). The architect must
        # emit it; ui-builder implements it over the 4-type starting hints.
        ("signature_layout_heading", r"Signature Layout"),
    ]
    return [
        _ok(label, _markdown_heading_present(content, pattern), pattern)
        for label, pattern in required
    ]


def _section_table_rows(content: str, heading_pattern: str) -> int:
    """Markdown table BODY rows inside the section under *heading_pattern*
    (header + separator rows excluded). 0 when the section/table is absent."""
    m = re.search(rf"(?im)^(#+)\s+{heading_pattern}\s*$", content)
    if not m:
        return 0
    level = len(m.group(1))
    rest = content[m.end():]
    stop = re.search(rf"(?m)^#{{1,{level}}}\s+", rest)
    section = rest[:stop.start()] if stop else rest
    pipe_rows = [
        line for line in section.splitlines() if line.strip().startswith("|")
    ]
    body = [
        line for line in pipe_rows
        if not re.match(r"^\|[\s:\-|]+\|?$", line.strip())
    ]
    return max(0, len(body) - 1)  # first non-separator row is the header


def check_market_context_present(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 1→2 — the plan must be grounded in category expectations.

    DEGRADED-only (never hard): requires the `## Market Context` heading plus
    either >=3 table body rows or noDirectCompetitors=true in
    .autobot/market-brief.json. Existence/structure is the enforceable part;
    research truth is owned by the architect self-check + /plan critique.
    """
    arch = proj / ".autobot" / "architecture.md"
    if not arch.is_file():
        return [_ok(
            "market_context_present", False,
            "architecture.md absent — market context unverifiable",
            skipped=True, degraded=True,
        )]
    try:
        content = arch.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [_ok(
            "market_context_present", False,
            f"architecture.md unreadable ({exc}) — market context unverifiable",
            skipped=True, degraded=True,
        )]
    if not _markdown_heading_present(content, r"Market Context"):
        return [_ok(
            "market_context_present", False,
            "'## Market Context' heading missing — category table-stakes were "
            "never researched/recorded (DEGRADED)",
            skipped=True, degraded=True,
        )]

    no_competitors = False
    brief_path = proj / ".autobot" / "market-brief.json"
    if brief_path.is_file():
        try:
            brief = load_json(brief_path)
            # Strict bool: the string "false" is truthy in Python, so a
            # `"noDirectCompetitors":"false"` config must NOT waive the row.
            no_competitors = isinstance(brief, dict) and (
                brief.get("noDirectCompetitors") is True
            )
        except (json.JSONDecodeError, OSError):
            pass

    rows = _section_table_rows(content, r"Market Context")
    if rows >= 3 or no_competitors:
        return [_ok(
            "market_context_present", True,
            f"Market Context present ({rows} table row(s)"
            + (", noDirectCompetitors" if no_competitors else "") + ")",
        )]
    return [_ok(
        "market_context_present", False,
        f"Market Context has only {rows} table row(s) (<3) and market-brief "
        f"does not declare noDirectCompetitors — DEGRADED",
        skipped=True, degraded=True,
    )]


def check_hook_retention_present(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 1→2 — planning-side siblings of design_direction_complete.

    DEGRADED-only heading checks: `### Hook & Retention` under Features, and —
    only when architecture.json declares firstRunPolicy == "primer" — the
    `## First-Run Experience` section. Heading presence is the enforceable
    part; content quality is the architect self-check + /plan critique.
    """
    arch = proj / ".autobot" / "architecture.md"
    try:
        content = arch.read_text(encoding="utf-8", errors="replace") if arch.is_file() else ""
    except OSError:
        content = ""  # unreadable → treated as missing headings (DEGRADED below)

    results: list[dict] = []
    if _markdown_heading_present(content, r"Hook\s*(?:&|and)\s*Retention"):
        results.append(_ok(
            "hook_retention_present", True, "'### Hook & Retention' present",
        ))
    else:
        results.append(_ok(
            "hook_retention_present", False,
            "'### Hook & Retention' heading missing — no declared "
            "download-reason / return-reason (DEGRADED)",
            skipped=True, degraded=True,
        ))

    policy = "direct"
    arch_json = proj / ".autobot" / "architecture.json"
    if arch_json.is_file():
        try:
            data = load_json(arch_json)
            if isinstance(data, dict) and data.get("firstRunPolicy"):
                policy = str(data["firstRunPolicy"])
        except (json.JSONDecodeError, OSError):
            pass
    if policy != "primer":
        results.append(_ok(
            "first_run_experience_present", True,
            f"firstRunPolicy={policy!r} — First-Run section not required",
            skipped=True,
        ))
    elif _markdown_heading_present(content, r"First[- ]Run Experience"):
        results.append(_ok(
            "first_run_experience_present", True,
            "'## First-Run Experience' present (firstRunPolicy=primer)",
        ))
    else:
        results.append(_ok(
            "first_run_experience_present", False,
            "firstRunPolicy='primer' but '## First-Run Experience' section "
            "missing — the primer was never designed (DEGRADED)",
            skipped=True, degraded=True,
        ))
    return results


_CRUD_METHOD_PREFIXES = ("fetch", "add", "delete", "update", "save", "get")


def check_service_protocol_depth(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 1→2 — the service contract must own >=1 derived/insight method.

    A protocol that only mirrors CRUD (fetch/add/delete/update/save/get)
    leaves nobody downstream owning computation, so the app can never show
    more than "store data, list data". Verb-prefix grep has known two-way
    error (a stub weeklySummary() passes; fetchWeeklyStats is misclassified
    as CRUD) — DEGRADED-only, never hard; quality is owned by the architect
    self-check.
    """
    sp = proj / app / "Models" / "ServiceProtocols.swift"
    if not sp.is_file():
        return [_ok(
            "service_protocol_depth", True,
            "ServiceProtocols.swift absent — existence is "
            "service_protocols_exist's call",
            skipped=True,
        )]
    try:
        text = sp.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [_ok(
            "service_protocol_depth", False,
            f"ServiceProtocols.swift unreadable ({exc}) — depth unverifiable",
            skipped=True, degraded=True,
        )]
    # Strip comments/strings so a `// func weeklySummary()` mention cannot pose
    # as a real derived method.
    funcs = re.findall(r"\bfunc\s+([A-Za-z_][A-Za-z0-9_]*)", strip_swift_noncode(text))
    non_crud = [n for n in funcs if not n.lower().startswith(_CRUD_METHOD_PREFIXES)]
    if non_crud:
        sample = ", ".join(sorted(set(non_crud))[:4])
        return [_ok(
            "service_protocol_depth", True,
            f"{len(non_crud)} non-CRUD method(s): {sample}",
        )]
    detail = (
        f"{len(funcs)} method(s), all CRUD verbs "
        f"({'/'.join(_CRUD_METHOD_PREFIXES)})"
        if funcs else "no protocol methods found"
    )
    return [_ok(
        "service_protocol_depth", False,
        f"{detail} — no derived/insight method (e.g. weeklySummary(), "
        f"currentStreak()) so no one owns computation; DEGRADED",
        skipped=True, degraded=True,
    )]


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
        results = [_ok("backend_skip", True, "backend_required=false", skipped=True)]
        if (proj / "backend").is_dir():
            # Reverse-direction guard: a backend/ tree on a backend_required=false
            # build means backend-engineer was misdispatched — surface it instead
            # of silently shipping dead artifacts. DEGRADED, never hard.
            results.append(_ok(
                "backend_not_required_but_present", False,
                "backend_required=false but backend/ exists — misdispatched "
                "backend-engineer output; DEGRADED (delete backend/ or set "
                "backend_required=true)",
                skipped=True, degraded=True,
            ))
        return results
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
