#!/usr/bin/env python3
"""Verify pipeline.json ↔ markdown documentation consistency.

Detects drift between the executable spec and documentation:
  1. Every gate in pipeline.json has a section in phase-gates.md
  2. Every procedural check name has an implementation in gate_checks.registry
  3. Hardcoded maxRetry values in markdown match pipeline.json
  4. Phase count matches across files
  5. spec/parts matches the executable pipeline bundle

Usage:
    python3 verify_spec_docs.py [--project-dir .]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
RENDER_SCRIPT = SCRIPT_DIR / "render_pipeline_docs.py"

from gate_checks.registry import GATE_CHECKS  # noqa: E402
from spec_loader import load_spec  # noqa: E402
from spec_bundle import diff_bundle  # noqa: E402

DOCS_TO_CHECK = [
    PLUGIN_DIR / "skills" / "autobot-orchestrator" / "SKILL.md",
    PLUGIN_DIR / "skills" / "autobot-orchestrator" / "references" / "phase-gates.md",
    PLUGIN_DIR / "commands" / "mvp.md",
    PLUGIN_DIR / "commands" / "testflight.md",
    PLUGIN_DIR / "commands" / "resume.md",
]


_DECLARATIVE_TYPES = {
    "file_exists", "dir_exists", "dir_has_swift", "file_grep",
    "command_success", "state_field_eq", "all",
}


def _iter_procedural_check_names(gate_spec: dict):
    """Yield the procedural impl names referenced by a gate.checks list.

    Accepts the v1 string form and the v2 descriptor form. Recurses into 'all'
    groups so nested procedural checks still surface.
    """
    for entry in gate_spec.get("checks", []):
        yield from _names_in_check(entry)


def _names_in_check(check):
    if isinstance(check, str):
        yield check
        return
    if not isinstance(check, dict):
        return
    dtype = check.get("type")
    if dtype == "procedural":
        name = check.get("name")
        if name:
            yield name
        return
    if dtype == "all":
        for child in check.get("checks", []):
            yield from _names_in_check(child)
    # declarative leaves (file_exists, dir_has_swift, ...) require no Python impl


def check_gate_sections(spec: dict) -> list[str]:
    """Every gate in pipeline.json should have a section in phase-gates.md."""
    gates_md = PLUGIN_DIR / "skills" / "autobot-orchestrator" / "references" / "phase-gates.md"
    if not gates_md.is_file():
        return [f"MISSING: {gates_md}"]

    content = gates_md.read_text(encoding="utf-8")
    errors = []
    for gate_id in spec.get("gates", {}):
        # Match "Gate 0→1" or "Gate 0->1" style headers
        normalized = gate_id.replace("->", "→")
        pattern = rf"Gate\s+{re.escape(gate_id)}|Gate\s+{re.escape(normalized)}"
        if not re.search(pattern, content):
            errors.append(f"Gate '{gate_id}' has no section in phase-gates.md")
    return errors


def check_implementations(spec: dict) -> list[str]:
    """Every procedural check referenced in pipeline.json should have a Python impl."""
    errors = []
    for gate_id, gate_spec in spec.get("gates", {}).items():
        for name in _iter_procedural_check_names(gate_spec):
            if name not in GATE_CHECKS:
                errors.append(
                    f"Gate {gate_id}: procedural check '{name}' has no impl in gate_checks.registry"
                )
    return errors


def check_retry_drift(spec: dict) -> list[str]:
    """Hardcoded maxRetry numbers in markdown should match pipeline.json."""
    errors = []
    phases = spec.get("phases", {})

    # Pattern: "최대 N회" or "(최대 N회)" or "max N" near a phase reference
    retry_pattern = re.compile(r"최대\s+(\d+)\s*회|max(?:imum)?\s+(\d+)\s+retr", re.IGNORECASE)

    for doc_path in DOCS_TO_CHECK:
        if not doc_path.is_file():
            continue
        content = doc_path.read_text(encoding="utf-8")

        for phase_id, phase_spec in phases.items():
            spec_retry = phase_spec.get("maxRetry", 0)
            phase_name = phase_spec.get("name", "")

            # Find lines mentioning this phase and a retry count
            for i, line in enumerate(content.splitlines(), 1):
                # Check if line references this phase
                refs_phase = (
                    f"Phase {phase_id}" in line
                    or phase_name.lower() in line.lower()
                )
                if not refs_phase:
                    continue

                match = retry_pattern.search(line)
                if match:
                    doc_retry = int(match.group(1) or match.group(2))
                    if doc_retry != spec_retry:
                        errors.append(
                            f"{doc_path.name}:{i}: Phase {phase_id} retry={doc_retry} "
                            f"but pipeline.json says maxRetry={spec_retry}"
                        )
    return errors


def check_phase_count(spec: dict) -> list[str]:
    """Phase count in pipeline.json should match tables in SKILL.md."""
    skill_md = PLUGIN_DIR / "skills" / "autobot-orchestrator" / "SKILL.md"
    if not skill_md.is_file():
        return []

    spec_count = len(spec.get("phases", {}))
    content = skill_md.read_text(encoding="utf-8")

    # Count table rows that start with "| N |" where N is an integer ("2") or
    # fractional ("2.5") phase id. Fractional ids arrived with Phase 2.5 in
    # 0.7.2; the prior \d+-only pattern silently under-counted by dropping the
    # "| 2.5 |" row, producing a spurious 8-vs-9 mismatch.
    table_rows = re.findall(r"^\|\s*\d+(?:\.\d+)?\s*\|", content, re.MULTILINE)
    if table_rows and len(table_rows) != spec_count:
        return [
            f"SKILL.md phase table has {len(table_rows)} rows "
            f"but pipeline.json defines {spec_count} phases"
        ]
    return []


def check_rendered_blocks_current() -> list[str]:
    """Generated markdown blocks should match pipeline.json."""
    if not RENDER_SCRIPT.is_file():
        return [f"MISSING: {RENDER_SCRIPT}"]

    result = subprocess.run(
        [sys.executable, str(RENDER_SCRIPT), "--check"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return []

    detail = result.stdout.strip() or result.stderr.strip() or "rendered docs are stale"
    return [f"Rendered pipeline doc blocks are outdated: {detail}"]


def check_spec_parts_current() -> list[str]:
    """The split spec parts must assemble to the checked-in bundle."""
    return diff_bundle()


_FACADE_SOURCE_MODULES = (
    "spec_loader",
    "state_store",
    "event_log",
    "transitions",
    "gate_persistence",
)


def check_facade_exports() -> list[str]:
    """runtime.py is a thin facade over the focused modules.

    Source of truth: each source module's ``__all__``. This check asserts that
    every name in those ``__all__`` lists is reachable via ``runtime.X`` and
    refers to the *same* object (not a shadow or stale rebinding). Adding a
    new public symbol in a source module automatically extends the contract.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import importlib

        runtime = importlib.import_module("runtime")
    except Exception as exc:  # pragma: no cover — defensive
        return [f"Cannot import runtime facade: {exc}"]

    errors: list[str] = []
    for source_module_name in _FACADE_SOURCE_MODULES:
        try:
            source_module = importlib.import_module(source_module_name)
        except Exception as exc:
            errors.append(f"Cannot import source module '{source_module_name}': {exc}")
            continue
        all_names = getattr(source_module, "__all__", None)
        if all_names is None:
            errors.append(f"{source_module_name} missing __all__ — facade contract is unverified")
            continue
        for name in all_names:
            if not hasattr(runtime, name):
                errors.append(f"runtime.{name} missing — facade did not re-export {source_module_name}.{name}")
                continue
            if getattr(runtime, name) is not getattr(source_module, name):
                errors.append(
                    f"runtime.{name} is not {source_module_name}.{name} — facade shadowed the symbol"
                )
    return errors


def _default_prose_docs() -> list[tuple[str, str]]:
    paths: list[Path] = [PLUGIN_DIR / "README.md"]
    for root in ("commands", "skills", "agents", "references"):
        base = PLUGIN_DIR / root
        if base.is_dir():
            paths.extend(sorted(base.rglob("*.md")))

    docs: list[tuple[str, str]] = []
    for path in paths:
        try:
            docs.append((str(path.relative_to(PLUGIN_DIR)), path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return docs


def check_prose_contract_drift(
    spec: dict,
    docs: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Catch non-rendered prose that names removed spec/runtime contracts."""
    docs = _default_prose_docs() if docs is None else docs
    errors: list[str] = []
    phases = spec.get("phases", {}) if isinstance(spec, dict) else {}
    has_agents_contract = any(
        isinstance(phase, dict) and "agents" in phase for phase in phases.values()
    )
    has_owner_contract = any(
        isinstance(phase, dict) and "owner" in phase for phase in phases.values()
    )

    for path, content in docs:
        if has_agents_contract and not has_owner_contract and "phases.<id>.owner" in content:
            errors.append(
                f"{path}: references removed spec path phases.<id>.owner; use phases.<id>.agents"
            )
        if "pipeline.sh\" complete-phase" in content or "pipeline.sh complete-phase" in content:
            errors.append(
                f"{path}: references removed pipeline.sh complete-phase; use advance-phase"
            )
        if "pipeline.sh\" set-phase-status" in content or "pipeline.sh set-phase-status" in content:
            errors.append(
                f"{path}: references non-public pipeline.sh set-phase-status; use start-phase/advance-phase/fail-phase"
            )
    return errors


def main() -> int:
    spec = load_spec()
    all_errors: list[str] = []
    all_warnings: list[str] = []

    print("Verifying pipeline.json ↔ documentation consistency...\n")

    # 1. Gate sections
    errs = check_gate_sections(spec)
    all_errors.extend(errs)
    print(f"  Gate sections in phase-gates.md: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 2. Check implementations
    errs = check_implementations(spec)
    all_errors.extend(errs)
    print(f"  Check implementations in gate_checks.registry: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 3. Retry drift
    errs = check_retry_drift(spec)
    all_warnings.extend(errs)
    print(f"  Retry value consistency: {'PASS' if not errs else f'{len(errs)} drift(s)'}")

    # 4. Phase count
    errs = check_phase_count(spec)
    all_warnings.extend(errs)
    print(f"  Phase count consistency: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 5. Split spec bundle
    errs = check_spec_parts_current()
    all_errors.extend(errs)
    print(f"  Split spec bundle current: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 6. Rendered markdown blocks
    errs = check_rendered_blocks_current()
    all_errors.extend(errs)
    print(f"  Rendered doc blocks current: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 7. runtime.py facade re-exports
    errs = check_facade_exports()
    all_errors.extend(errs)
    print(f"  runtime.py facade re-exports: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 8. Non-rendered prose contract drift
    errs = check_prose_contract_drift(spec)
    all_errors.extend(errs)
    print(f"  Prose contract drift: {'PASS' if not errs else f'{len(errs)} issues'}")

    if all_errors:
        print(f"\nERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")

    if all_warnings:
        print(f"\nWARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ⚠ {w}")

    if not all_errors and not all_warnings:
        print("\nAll checks passed.")

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
