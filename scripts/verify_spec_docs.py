#!/usr/bin/env python3
"""Verify pipeline.json ↔ markdown documentation consistency.

Detects drift between the executable spec and documentation:
  1. Every gate in pipeline.json has a section in phase-gates.md
  2. Every procedural check name has an implementation in gate_checks.registry
  3. Hardcoded maxRetry values in markdown match pipeline.json
  4. Phase count matches across files
  5. spec/parts matches the executable pipeline bundle
  6. AUTOBOT_* env vars referenced in docs are known to some script
  7. The 3 prose copies of the Phase → phase-learning-file mapping agree

Usage:
    python3 verify_spec_docs.py [--project-dir .]
"""

from __future__ import annotations

import json
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


def check_gate_structure(spec: dict) -> list[str]:
    """Every gate must declare a non-empty `checks` array.

    A gate with no checks passes vacuously — a silent hole where a phase
    transition looks gated but enforces nothing. (Registry existence of the
    named procedural checks is covered by check_implementations.)
    """
    errors = []
    for gate_id, gate_spec in spec.get("gates", {}).items():
        checks = gate_spec.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"Gate '{gate_id}' has an empty or missing checks array")
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
    for root in ("commands", "skills", "agents", "references", "docs"):
        base = PLUGIN_DIR / root
        if base.is_dir():
            paths.extend(sorted(base.rglob("*.md")))

    # docs/superpowers/ is a historical spec/plan archive — intentionally stale,
    # not a live operational doc, so it's excluded from drift scanning.
    paths = [p for p in paths if "superpowers" not in p.relative_to(PLUGIN_DIR).parts]

    docs: list[tuple[str, str]] = []
    for path in paths:
        try:
            docs.append((str(path.relative_to(PLUGIN_DIR)), path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return docs


# --- Generic prose contract drift (rename-proof, unlike the blocklist below) ---

# `--event <name>` invocations (build-log.sh command lines in docs).
_EVENT_REF_RE = re.compile(r"--event\s+([a-z][a-z0-9_]*)")
# `pipeline.sh <sub>` invocations — checked inside code spans only, so English
# prose like "pipeline.sh is ..." cannot false-positive as a subcommand.
_PIPELINE_SUB_RE = re.compile(r"pipeline\.sh\"?\s+([a-z][a-z0-9-]*)")
# `$CLAUDE_PLUGIN_ROOT/scripts/...` path references (both ${...} and $... forms).
_PLUGIN_SCRIPT_RE = re.compile(
    r"\$\{?CLAUDE_PLUGIN_ROOT\}?/(scripts/[A-Za-z0-9_\-./]*[A-Za-z0-9_\-])"
)
# AUTOBOT_* env var name references.
_AUTOBOT_VAR_RE = re.compile(r"\bAUTOBOT_[A-Z][A-Z0-9_]*\b")
# A doc-local knob: the var is declared right there with a shell default
# (`${AUTOBOT_X:-default}`), so it's self-contained and not a reference to a
# name the scripts are expected to already know about.
_AUTOBOT_VAR_DEFAULT_RE = re.compile(r"\$\{(AUTOBOT_[A-Z][A-Z0-9_]*):-")
# Fenced code blocks and inline backtick spans.
_CODE_SPAN_RE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)


def _pipeline_subcommands() -> set[str]:
    """Case labels of scripts/pipeline.sh's dispatch (`  <label>)` lines)."""
    pipeline_sh = SCRIPT_DIR / "pipeline.sh"
    if not pipeline_sh.is_file():
        return set()
    content = pipeline_sh.read_text(encoding="utf-8")
    return set(re.findall(r"^\s{2}([a-z][a-z0-9-]*)\)", content, re.MULTILINE))


def _known_autobot_vars() -> set[str]:
    """AUTOBOT_* names referenced anywhere in scripts/ and skills/*/scripts/
    (.sh + .py) — the set of vars the shell scripts actually know about."""
    known: set[str] = set()
    for root in ("scripts", "skills"):
        base = PLUGIN_DIR / root
        if not base.is_dir():
            continue
        for pattern in ("*.sh", "*.py"):
            for path in base.rglob(pattern):
                known |= set(_AUTOBOT_VAR_RE.findall(path.read_text(encoding="utf-8")))
    return known


def check_prose_generic_drift(
    spec: dict,
    docs: list[tuple[str, str]] | None = None,
    pipeline_subs: set[str] | None = None,
    known_autobot_vars: set[str] | None = None,
) -> list[str]:
    """Generic drift scan over all prose docs (auto-detects renames, unlike the
    hardcoded blocklist in check_prose_contract_drift):

      - `--event <name>`   must be a key in spec logEvents (build-log.sh rejects
                           unknown events mid-build otherwise)
      - `pipeline.sh <sub>` (in code spans) must be a pipeline.sh case label
      - `$CLAUDE_PLUGIN_ROOT/scripts/...` referenced paths must exist
      - `AUTOBOT_*` names (in code spans) must be read/set by some script, or
        declared locally in the doc via `${AUTOBOT_X:-default}`
    """
    docs = _default_prose_docs() if docs is None else docs
    pipeline_subs = _pipeline_subcommands() if pipeline_subs is None else pipeline_subs
    known_autobot_vars = (
        _known_autobot_vars() if known_autobot_vars is None else known_autobot_vars
    )
    known_events = set((spec.get("logEvents") or {}).keys()) if isinstance(spec, dict) else set()
    errors: list[str] = []

    for path, content in docs:
        for event in sorted(set(_EVENT_REF_RE.findall(content))):
            if known_events and event not in known_events:
                errors.append(
                    f"{path}: references unknown log event '--event {event}' "
                    f"(not in spec logEvents — build-log.sh will reject it)"
                )

        code_text = "\n".join(m.group(0) for m in _CODE_SPAN_RE.finditer(content))
        for sub in sorted(set(_PIPELINE_SUB_RE.findall(code_text))):
            if pipeline_subs and sub not in pipeline_subs:
                errors.append(
                    f"{path}: references unknown pipeline.sh subcommand '{sub}' "
                    f"(no such case label in scripts/pipeline.sh)"
                )

        for rel in sorted(set(_PLUGIN_SCRIPT_RE.findall(content))):
            if not (PLUGIN_DIR / rel).exists():
                errors.append(
                    f"{path}: references $CLAUDE_PLUGIN_ROOT/{rel} which does not exist"
                )

        doc_local_vars = set(_AUTOBOT_VAR_DEFAULT_RE.findall(code_text))
        if known_autobot_vars:
            for var in sorted(set(_AUTOBOT_VAR_RE.findall(code_text))):
                if var not in known_autobot_vars and var not in doc_local_vars:
                    errors.append(
                        f"{path}: references unknown env var '{var}' "
                        f"(no script reads/sets it, and it's not a doc-local "
                        f"${{{var}:-default}} knob)"
                    )
    return errors


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


def check_release_metadata_consistency(
    manifest_text: str | None = None,
    pyproject_text: str | None = None,
) -> list[str]:
    """Keep package metadata aligned with the plugin manifest release SSOT."""
    manifest_path = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    pyproject_path = PLUGIN_DIR / "pyproject.toml"
    if manifest_text is None:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    if pyproject_text is None:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")

    try:
        manifest = json.loads(manifest_text)
    except (json.JSONDecodeError, TypeError) as exc:
        return [f"{manifest_path.relative_to(PLUGIN_DIR)}: invalid JSON: {exc}"]

    project_match = re.search(
        r"(?ms)^\[project\]\s*$\n(.*?)(?=^\[|\Z)",
        pyproject_text,
    )
    if project_match is None:
        return ["pyproject.toml: missing [project] table"]

    project_block = project_match.group(1)
    errors: list[str] = []
    for key in ("version", "description"):
        value_match = re.search(
            rf'(?m)^{key}\s*=\s*"([^"\n]*)"\s*$',
            project_block,
        )
        if value_match is None:
            errors.append(f"pyproject.toml: missing project.{key}")
            continue
        manifest_value = manifest.get(key)
        if value_match.group(1) != manifest_value:
            errors.append(
                f"pyproject.toml project.{key} does not match "
                f".claude-plugin/plugin.json {key}"
            )
    return errors


# --- Phase → phase-learning file mapping (3 prose copies, spec/parts has no
# learningFile field — see scripts/render-active-learnings.py PHASE_FILE_ALIASES) ---

_RESUME_PHASE_FILE_RE = re.compile(
    r"Phase\s+(\d+)\s*→\s*`\.autobot/phase-learnings/([\w.\-]+\.md)`"
)
_SKILL_PHASE_FILE_RE = re.compile(r"(\d+)→`([\w.\-]+\.md)`")
_BOOTSTRAP_PHASE_FILE_RE = re.compile(
    r"^\|\s*(\d+)\s*\|[^|]*\|\s*`phase-learnings/([\w.\-]+\.md)`\s*\|", re.MULTILINE
)


def _phase_file_aliases() -> dict[str, list[str]]:
    """Parse PHASE_FILE_ALIASES out of render-active-learnings.py without
    importing it (hyphenated filename isn't a valid module name)."""
    import ast

    path = SCRIPT_DIR / "render-active-learnings.py"
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # PHASE_FILE_ALIASES is a module-level annotated assignment
        # (`NAME: type = {...}`), which is ast.AnnAssign, not ast.Assign.
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PHASE_FILE_ALIASES"
            and node.value is not None
        ):
            return ast.literal_eval(node.value)
    return {}


def check_phase_learning_mapping(
    resume_text: str | None = None,
    skill_text: str | None = None,
    bootstrap_text: str | None = None,
    known_filenames: set[str] | None = None,
) -> list[str]:
    """The Phase → phase-learning-file mapping is duplicated prose (no spec
    field backs it) in commands/resume.md, SKILL.md and learning-bootstrap.md.
    Cross-check the 3 copies agree, and that every filename they name is one
    render-active-learnings.py's PHASE_FILE_ALIASES actually knows about.
    """
    resume_path = PLUGIN_DIR / "commands" / "resume.md"
    skill_path = PLUGIN_DIR / "skills" / "autobot-orchestrator" / "SKILL.md"
    bootstrap_path = (
        PLUGIN_DIR / "skills" / "autobot-orchestrator" / "references" / "learning-bootstrap.md"
    )
    if resume_text is None:
        if not resume_path.is_file():
            return []
        resume_text = resume_path.read_text(encoding="utf-8")
    if skill_text is None:
        if not skill_path.is_file():
            return []
        skill_text = skill_path.read_text(encoding="utf-8")
    if bootstrap_text is None:
        if not bootstrap_path.is_file():
            return []
        bootstrap_text = bootstrap_path.read_text(encoding="utf-8")

    sources = {
        "commands/resume.md": dict(_RESUME_PHASE_FILE_RE.findall(resume_text)),
        "skills/autobot-orchestrator/SKILL.md": dict(_SKILL_PHASE_FILE_RE.findall(skill_text)),
        "skills/autobot-orchestrator/references/learning-bootstrap.md": dict(
            _BOOTSTRAP_PHASE_FILE_RE.findall(bootstrap_text)
        ),
    }

    errors: list[str] = []

    # A canonical doc that yields zero mappings has lost the prose entirely (or
    # its format drifted past the extractor) — the cross-doc agreement check
    # then silently passes on nothing.
    for doc_name, mapping in sources.items():
        if not mapping:
            errors.append(
                f"{doc_name}: extracted 0 Phase→phase-learning-file mappings "
                "(mapping prose missing or its format drifted)"
            )

    # Cross-source agreement: every phase mentioned by 2+ sources must name
    # the same file in all of them.
    all_phases = set()
    for mapping in sources.values():
        all_phases |= set(mapping)
    for phase in sorted(all_phases):
        seen = {name: mapping[phase] for name, mapping in sources.items() if phase in mapping}
        filenames = set(seen.values())
        if len(filenames) > 1:
            detail = ", ".join(f"{name}={fn}" for name, fn in seen.items())
            errors.append(f"phase-learning mapping for Phase {phase} disagrees across docs: {detail}")

    # Every named filename must be a known alias (or the shared fallback).
    known_filenames = (
        {fn for aliases in _phase_file_aliases().values() for fn in aliases} | {"active-learnings.md"}
        if known_filenames is None
        else known_filenames
    )
    if known_filenames:
        for doc_name, mapping in sources.items():
            for phase, filename in mapping.items():
                if filename not in known_filenames:
                    errors.append(
                        f"{doc_name}: Phase {phase} names '{filename}', which is not in "
                        f"render-active-learnings.py's PHASE_FILE_ALIASES"
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

    # 2b. Gate descriptor structure (non-empty checks array)
    errs = check_gate_structure(spec)
    all_errors.extend(errs)
    print(f"  Gate descriptor structure (non-empty checks): {'PASS' if not errs else f'{len(errs)} issues'}")

    # 3. Retry drift — a deterministic doc↔spec mismatch, so it fails the run.
    errs = check_retry_drift(spec)
    all_errors.extend(errs)
    print(f"  Retry value consistency: {'PASS' if not errs else f'{len(errs)} drift(s)'}")

    # 4. Phase count — deterministic drift, fails the run.
    errs = check_phase_count(spec)
    all_errors.extend(errs)
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

    # 9. Generic prose drift (events / pipeline.sh subcommands / script paths)
    errs = check_prose_generic_drift(spec)
    all_errors.extend(errs)
    print(f"  Generic prose drift (events/subcommands/paths/env vars): {'PASS' if not errs else f'{len(errs)} issues'}")

    # 10. Release metadata
    errs = check_release_metadata_consistency()
    all_errors.extend(errs)
    print(f"  Release metadata consistency: {'PASS' if not errs else f'{len(errs)} issues'}")

    # 11. Phase → phase-learning file mapping (3 prose copies must agree)
    errs = check_phase_learning_mapping()
    all_errors.extend(errs)
    print(f"  Phase learning file mapping: {'PASS' if not errs else f'{len(errs)} issues'}")

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
