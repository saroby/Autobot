"""Procedural gate-check registry.

Gate check implementations stay in domain modules. This file is the only
place that maps spec/pipeline.json procedural names to callables, so the
runner can focus on descriptor evaluation and CLI behavior.
"""
from __future__ import annotations

from typing import Any

from gate_checks.app import (
    check_backend_artifacts_exist_if_required,
    check_composition_seam_intact,
    check_models_checksum_matches,
    check_no_tabbar_safearea_smells,
    check_sandbox_clean,
    check_services_exist,
    check_views_exist,
)
from gate_checks.build import (
    check_app_uses_real_repositories,
    check_backend_deploy_readiness,
    check_build_succeeded,
    check_first_launch_seeded,
    check_metadata_readiness,
    check_runtime_smoke,
    check_service_stubs_preserved,
    check_visual_contract,
    check_visual_judge,
)
from gate_checks.capability import (
    check_app_intent_declared,
    check_feature_spec_declared,
    check_feature_spec_quality,
    check_idea_layout_requirements_captured,
    check_intent_anchors_in_ui,
    check_ios_capability_safe,
    check_primary_cta_visibility,
)
from gate_checks.deploy import check_deployment_attempt_recorded
from gate_checks.design import (
    check_app_icon_source_present,
    check_design_assets_exist_or_fallback,
    check_design_spec_json_valid,
    check_design_spec_sections_complete,
    check_design_system_package_exists,
    check_design_system_tokens_exist,
)
from gate_checks.functional import (
    check_functional_flows_pass,
    check_functional_verification_passed,
    check_logic_tests_pass,
)
from gate_checks.review import (
    check_architecture_peer_review_acceptable,
    check_axiom_critical_audit_acceptable,
    check_codex_review_acceptable,
    check_peer_review_acceptable,
)
from gate_checks.scaffold import (
    check_app_icon_applied,
    check_entitlements_exists,
    check_gitignore_exists,
    check_privacy_manifest_exists,
    check_scaffold_build_succeeded,
    check_xcodeproj_exists,
)
from gate_checks.setup import (
    check_architecture_document_exists,
    check_backend_required_consistent,
    check_build_state_initialized,
    check_contracts_snapshot_saved,
    check_design_direction_complete,
    check_environment_ready,
    check_environment_recorded,
    check_models_exist,
    check_project_name_resolved,
    check_service_protocols_exist,
)


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
    "idea_layout_requirements_captured": check_idea_layout_requirements_captured,
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
    "design_system_package_exists": check_design_system_package_exists,
    "design_system_tokens_exist": check_design_system_tokens_exist,
    # Gate 4→5
    "views_exist": check_views_exist,
    "services_exist": check_services_exist,
    "models_checksum_matches": check_models_checksum_matches,
    "backend_artifacts_exist_if_required": check_backend_artifacts_exist_if_required,
    "composition_seam_intact": check_composition_seam_intact,
    "primary_cta_visibility": check_primary_cta_visibility,
    "sandbox_clean": check_sandbox_clean,
    "no_tabbar_safearea_smells": check_no_tabbar_safearea_smells,
    # Gate 5→6
    "build_succeeded": check_build_succeeded,
    "peer_review_acceptable": check_peer_review_acceptable,
    "axiom_critical_audit_acceptable": check_axiom_critical_audit_acceptable,
    "app_uses_real_repositories": check_app_uses_real_repositories,
    "runtime_smoke": check_runtime_smoke,
    "visual_contract": check_visual_contract,
    "visual_judge": check_visual_judge,
    "metadata_readiness": check_metadata_readiness,
    "service_stubs_preserved": check_service_stubs_preserved,
    "first_launch_seeded": check_first_launch_seeded,
    "backend_deploy_readiness": check_backend_deploy_readiness,
    "logic_tests_pass": check_logic_tests_pass,
    "functional_flows_pass": check_functional_flows_pass,
    # Gate 6→7
    "deployment_attempt_recorded": check_deployment_attempt_recorded,
    "functional_verification_passed": check_functional_verification_passed,
}


__all__ = ["GATE_CHECKS"] + sorted(
    name for name in globals()
    if name.startswith("check_")
)
