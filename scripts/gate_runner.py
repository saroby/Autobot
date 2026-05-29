"""Gate-runner: tiny core + a registry of per-domain check functions.

The check implementations live in scripts/gate_checks/*.py — this module
only wires them into the GATE_CHECKS registry and drives the descriptor
engine + CLI. All public symbols are re-exported so existing callers
(``from gate_runner import run_gate``, tests importing individual
``check_*`` functions, etc.) keep working unchanged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"

from spec_loader import resolve_app_template  # noqa: E402

# ── re-export helpers + check functions ──
from gate_checks._helpers import (  # noqa: E402,F401
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
from gate_checks.setup import (  # noqa: E402,F401
    check_environment_ready,
    check_project_name_resolved,
    check_build_state_initialized,
    check_environment_recorded,
    check_architecture_document_exists,
    check_design_direction_complete,
    check_models_exist,
    check_service_protocols_exist,
    check_contracts_snapshot_saved,
    check_backend_required_consistent
)
from gate_checks.capability import (  # noqa: E402,F401
    check_app_intent_declared,
    check_feature_spec_declared,
    check_feature_spec_quality,
    check_intent_anchors_in_ui,
    check_primary_cta_visibility,
    check_ios_capability_safe
)
from gate_checks.review import (  # noqa: E402,F401
    check_architecture_peer_review_acceptable,
    check_codex_review_acceptable,
    check_axiom_critical_audit_acceptable,
    check_peer_review_acceptable
)
from gate_checks.design import (  # noqa: E402,F401
    check_design_assets_exist_or_fallback,
    check_app_icon_source_present,
    check_design_spec_sections_complete,
    check_design_spec_json_valid,
    check_design_system_package_exists,
    check_design_system_tokens_exist
)
from gate_checks.scaffold import (  # noqa: E402,F401
    check_xcodeproj_exists,
    check_privacy_manifest_exists,
    check_app_icon_applied,
    check_entitlements_exists,
    check_scaffold_build_succeeded,
    check_gitignore_exists
)
from gate_checks.app import (  # noqa: E402,F401
    check_views_exist,
    check_services_exist,
    check_no_tabbar_safearea_smells,
    check_models_checksum_matches,
    check_backend_artifacts_exist_if_required,
    check_composition_seam_intact,
    check_sandbox_clean
)
from gate_checks.build import (  # noqa: E402,F401
    check_build_succeeded,
    check_visual_contract,
    check_runtime_smoke,
    check_metadata_readiness,
    check_app_uses_real_repositories,
    check_service_stubs_preserved
)
from gate_checks.deploy import (  # noqa: E402,F401
    check_deployment_attempt_recorded
)
from gate_checks.functional import (  # noqa: E402,F401
    check_logic_tests_pass,
    check_functional_flows_pass
)


# ── Registry: spec name → procedural check function ──
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
    "feature_spec_declared": check_feature_spec_declared,
    "feature_spec_quality": check_feature_spec_quality,
    "intent_anchors_in_ui": check_intent_anchors_in_ui,
    # Gate 2→3
    "design_spec_sections_complete": check_design_spec_sections_complete,
    "design_assets_exist_or_fallback": check_design_assets_exist_or_fallback,
    "design_spec_json_valid": check_design_spec_json_valid,
    "app_icon_source_present": check_app_icon_source_present,
    # Gate 3→4
    "xcodeproj_exists": check_xcodeproj_exists,
    "privacy_manifest_exists": check_privacy_manifest_exists,
    "entitlements_exists": check_entitlements_exists,
    "gitignore_exists": check_gitignore_exists,
    "scaffold_build_succeeded": check_scaffold_build_succeeded,
    "app_icon_applied": check_app_icon_applied,
    # Gate 4→5
    "views_exist": check_views_exist,
    "services_exist": check_services_exist,
    "models_checksum_matches": check_models_checksum_matches,
    "backend_artifacts_exist_if_required": check_backend_artifacts_exist_if_required,
    "composition_seam_intact": check_composition_seam_intact,
    "primary_cta_visibility": check_primary_cta_visibility,
    # Gate 5→6
    "build_succeeded": check_build_succeeded,
    "peer_review_acceptable": check_peer_review_acceptable,
    "axiom_critical_audit_acceptable": check_axiom_critical_audit_acceptable,
    "app_uses_real_repositories": check_app_uses_real_repositories,
    "runtime_smoke": check_runtime_smoke,
    "visual_contract": check_visual_contract,
    "metadata_readiness": check_metadata_readiness,
    "service_stubs_preserved": check_service_stubs_preserved,
    "logic_tests_pass": check_logic_tests_pass,
    "functional_flows_pass": check_functional_flows_pass,
    # Gate 6→7
    "deployment_attempt_recorded": check_deployment_attempt_recorded,
    # Gate 4→5 (added with fileOwnership SSOT)
    "sandbox_clean": check_sandbox_clean,
    "no_tabbar_safearea_smells": check_no_tabbar_safearea_smells,
    # Gate 3→4 (design-system package)
    "design_system_package_exists": check_design_system_package_exists,
    "design_system_tokens_exist": check_design_system_tokens_exist,
}



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
    any_hard_fail = False
    any_degraded = False

    for raw in raw_checks:
        descriptor = _normalize_check(raw)
        label = descriptor.get("label") or descriptor.get("name") or descriptor.get("type", "unnamed")
        sub_checks = _evaluate_descriptor(descriptor, project_dir, app_name, state)

        # Three-valued group rollup:
        #   hard_fail = a sub-check ran and truly failed (not a skip)
        #   degraded  = a sub-check skipped *because* a degradable resource was
        #               missing (skipped AND degraded). A benign skip (skipped
        #               only, no degraded flag) still counts as green so
        #               backend_required N/A skips never lower the gate.
        group_hard_fail = any(
            (not r["passed"]) and (not r.get("skipped", False))
            for r in sub_checks
        )
        group_degraded = any(
            r.get("skipped", False) and r.get("degraded", False)
            for r in sub_checks
        )
        group_passed = not group_hard_fail and not group_degraded

        if group_hard_fail:
            any_hard_fail = True
        if group_degraded and not group_hard_fail:
            any_degraded = True

        all_results.append({
            "check": label,
            "passed": group_passed,
            "degraded": (group_degraded and not group_hard_fail),
            "sub_checks": sub_checks,
        })

    passed = not any_hard_fail
    degraded = passed and any_degraded
    return {
        "gate": gate_id,
        "passed": passed,
        "degraded": degraded,
        "soft": soft,
        "checks": all_results,
    }


def format_text(result: dict) -> str:
    lines: list[str] = []
    if result["passed"]:
        status = "DEGRADED" if result.get("degraded") else "PASS"
    else:
        status = "SOFT FAIL" if result.get("soft") else "FAIL"
    lines.append(f"Gate {result['gate']}: {status}")
    lines.append("")

    for group in result.get("checks", []):
        if group["passed"]:
            mark = "PASS"
        elif group.get("degraded"):
            mark = "DEGRADED"
        else:
            mark = "FAIL"
        lines.append(f"  [{mark}] {group['check']}")
        for sub in group.get("sub_checks", []):
            if sub.get("skipped") and sub.get("degraded"):
                icon = "⚠"
            elif sub.get("skipped"):
                icon = "⊘"
            elif sub["passed"]:
                icon = "✓"
            else:
                icon = "✗"
            lines.append(f"    {icon} {sub['check']}: {sub['message']}")

    if "error" in result:
        lines.append(f"\n  ERROR: {result['error']}")
    return "\n".join(lines)


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
