"""Design spec, design assets, app-icon source, design-system tokens.

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
    _agent_writes_dirs,
    strip_swift_noncode,
)


def _is_fallback(state: dict, phase: str) -> bool:
    return state.get("phases", {}).get(phase, {}).get("status") == "fallback"


def check_design_assets_exist_or_fallback(proj: Path, app: str, state: dict) -> list[dict]:
    designs = proj / ".autobot" / "designs"
    matches = sorted(designs.glob("*.png")) if designs.is_dir() else []
    if _is_fallback(state, "2"):
        # quality-max: even a Stitch fallback must carry ≥1 real mockup, else
        # DEGRADED (NOT hard fail — keeps the autonomous build moving, flags the gap).
        if bool(state.get("qualityMax")) and not matches:
            return [_ok("design_assets_fallback", True,
                        "Phase 2 fallback with 0 mockups — quality-max requires ≥1 real "
                        "mockup PNG; generate one or run /autobot:plan to review",
                        skipped=True, degraded=True)]
        return [_ok("design_assets_fallback", True,
                    f"Phase 2 fallback ({len(matches)} mockup png)", skipped=True)]
    return [_ok("design_png_files", len(matches) > 0, f"{len(matches)} .png in designs/")]


def check_app_icon_source_present(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 2 must produce a 1024×1024 app-icon PNG.

    The orchestrator is expected to invoke the ``autobot-app-icon`` skill at
    the tail of Phase 2 — imagegen → Pillow fallback → placeholder. If even the
    placeholder is missing, the AppIcon.appiconset will end up empty and the
    user gets a faceless app. Past incident: BookMemo (2026-05) shipped with no
    icon because orchestrator skipped this implicit step.
    """
    icon = proj / ".autobot" / "app-icon-1024.png"
    if not icon.is_file():
        return [_ok(
            "app_icon_source_present", False,
            f"MISSING: {icon} — invoke autobot-app-icon skill (imagegen → Pillow fallback)",
        )]
    size = icon.stat().st_size
    return [_ok("app_icon_source_present", size > 0, f"{icon.name} ({size} bytes)")]


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


def _resolve_design_system_module(proj: Path, state: dict) -> tuple[str | None, str | None]:
    """Return (module_name, error_message). module_name is None when unresolved.

    Resolution order:
    1. state["architecture"]["designSystemModule"] (test/runtime injection)
    2. .autobot/architecture.json -> designSystemModule

    The architecture.json read is wrapped in try/except so a malformed file
    surfaces as an actionable gate failure rather than a stack trace.
    """
    arch = (state or {}).get("architecture") or {}
    module = arch.get("designSystemModule") if isinstance(arch, dict) else None
    if module:
        return module, None

    arch_path = proj / ".autobot" / "architecture.json"
    if not arch_path.is_file():
        return None, "designSystemModule not set: missing .autobot/architecture.json"
    try:
        data = json.loads(arch_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "designSystemModule unreadable: .autobot/architecture.json is malformed"
    module = data.get("designSystemModule") if isinstance(data, dict) else None
    if not module:
        return None, "designSystemModule key absent in .autobot/architecture.json"
    return module, None


def check_design_system_package_exists(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify Packages/<Module>/Package.swift exists and declares the expected name."""
    module, err = _resolve_design_system_module(proj, state)
    if err is not None:
        return [_ok("design_system_module_resolved", False, err)]

    pkg_swift = proj / "Packages" / module / "Package.swift"
    if not pkg_swift.is_file():
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift not found at {pkg_swift.relative_to(proj) if pkg_swift.is_relative_to(proj) else pkg_swift}",
        )]

    content = pkg_swift.read_text(encoding="utf-8", errors="replace")
    # Match `name: "<module>"` exactly; reject sibling DS packages parked at the
    # same path with a different declared name.
    if not re.search(rf'name:\s*"{re.escape(module)}"', content):
        return [_ok(
            "design_system_package_exists", False,
            f"Package.swift name does not match expected module '{module}'",
        )]
    return [_ok("design_system_package_exists", True, f"Package.swift OK for module '{module}'")]


def check_design_system_tokens_exist(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify required token source files exist and are non-empty.

    Tokens live at Packages/<Module>/Sources/<Module>/Tokens/{Color,Typography,
    Spacing,Radius}.swift. Empty files are treated as missing so a half-written
    scaffold doesn't slip past the gate.
    """
    module, err = _resolve_design_system_module(proj, state)
    if err is not None:
        return [_ok("design_system_tokens_module", False, err)]

    tokens_dir = proj / "Packages" / module / "Sources" / module / "Tokens"
    required = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]

    missing: list[str] = []
    empty: list[str] = []
    for name in required:
        f = tokens_dir / name
        if not f.is_file():
            missing.append(name)
        elif f.stat().st_size == 0:
            empty.append(name)

    if missing:
        return [_ok(
            "design_system_tokens_exist", False,
            f"missing token files: {', '.join(missing)}",
        )]
    if empty:
        return [_ok(
            "design_system_tokens_exist", False,
            f"token files are empty: {', '.join(empty)}",
        )]
    return [_ok("design_system_tokens_exist", True, f"all {len(required)} token files present")]


_DS_COMPONENTS = ("PrimaryButton", "Card", "SectionHeader", "EmptyStateView", "ListRow")


def check_design_system_components_exist(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 3→4 — the 5 fixed-name DS component files must exist and declare
    ``public struct <Module><Name>``.

    ui-builder imports these EXACT names (design-system.md contract); until
    now the contract lived only in prose, so a missing/renamed component
    surfaced first as a Phase 5 xcodebuild failure — the most expensive
    detection point (hard-fail, burns the circuit breaker). Hard check, same
    level as design_system_tokens_exist: it verifies the producer's own
    mandatory output, not a new quality bar.
    """
    module, err = _resolve_design_system_module(proj, state)
    if err is not None:
        return [_ok("design_system_components_module", False, err)]

    comp_dir = proj / "Packages" / module / "Sources" / module / "Components"
    problems: list[str] = []
    for name in _DS_COMPONENTS:
        f = comp_dir / f"{name}.swift"
        if not f.is_file():
            problems.append(f"{name}.swift missing")
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            problems.append(f"{name}.swift empty")
            continue
        # Strip comments/strings so a `// public struct <Module><Name>` mention
        # cannot satisfy this HARD contract — only a real declaration counts.
        if not re.search(
            rf"public\s+struct\s+{re.escape(module)}{name}\b",
            strip_swift_noncode(content),
        ):
            problems.append(f"{name}.swift lacks `public struct {module}{name}`")
    if problems:
        return [_ok(
            "design_system_components_exist", False,
            f"DS component contract broken: {'; '.join(problems[:5])}",
        )]
    return [_ok(
        "design_system_components_exist", True,
        f"all {len(_DS_COMPONENTS)} components declare public struct {module}* primitives",
    )]


def check_ds_primitives_used(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 4→5 — Views/ should import the DS module and use ≥1 of the 5
    shared primitives.

    Otherwise the whole DS component layer is invisible dead code (happened
    once — CHANGELOG records ui-builder importing only tokens and
    re-implementing every primitive; the fix was prose-only). DEGRADED-only,
    NEVER a hard fail: primitive usage is a quality signal, and a false
    positive must not consume the circuit breaker.
    """
    module, err = _resolve_design_system_module(proj, state)
    if err is not None:
        # Legacy builds without designSystemModule must not degrade forever.
        return [_ok("ds_primitives_used", True, f"skipped: {err}", skipped=True)]
    views = proj / app / "Views"
    if not views.is_dir():
        return [_ok("ds_primitives_used", True, "no Views/ dir", skipped=True)]

    sources: list[str] = []
    for swift in sorted(views.rglob("*.swift")):
        try:
            sources.append(swift.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    combined = "\n".join(sources)
    has_import = bool(re.search(rf"\bimport\s+{re.escape(module)}\b", combined))
    used = [n for n in _DS_COMPONENTS if re.search(rf"\b{re.escape(module)}{n}\b", combined)]
    if has_import and used:
        return [_ok(
            "ds_primitives_used", True,
            f"Views/ imports {module} and uses {len(used)} primitive(s): {', '.join(used)}",
        )]
    reason = []
    if not has_import:
        reason.append(f"no `import {module}` in Views/")
    if not used:
        reason.append(f"none of the 5 {module}* primitives referenced")
    return [_ok(
        "ds_primitives_used", False,
        f"{'; '.join(reason)} — DS component layer is dead code "
        f"(re-implemented primitives lose the app-wide style lever). "
        f"DEGRADED (not a hard fail).",
        skipped=True, degraded=True,
    )]
