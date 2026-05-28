"""Generated-app body: views, services, smell checks, ownership.

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
        # Recursive: Views/Components/, Views/Screens/ etc. are allowed
        # organization. The Phase 4 sandbox guard ensures the files all land
        # under the agent's owned root, so recursive .swift counting is safe.
        results.append(_dir_has_swift(proj / rel.rstrip("/"), label, recursive=True))
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
