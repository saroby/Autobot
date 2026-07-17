"""Regression coverage for orchestration-doc alignment fixes (2026-07-17 audit).

Pure text contracts over commands/resume.md, commands/mvp.md,
skills/autobot-orchestrator/SKILL.md, agents/ui-builder.md, agents/deployer.md.
No sandbox/runtime state needed — these are doc-drift guards.
"""
from __future__ import annotations

import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _read(*parts: str) -> str:
    return (PLUGIN_DIR / Path(*parts)).read_text(encoding="utf-8")


class TestPhase2AppIconResumePath(unittest.TestCase):
    """Finding: Phase 2 app-icon step existed only in mvp.md prose — resume/dispatcher
    couldn't reproduce it, so a resumed Phase 2 could fail gate 2->3 deterministically
    (real incident: BookMemo shipped iconless)."""

    def test_resume_phase2_section_mentions_app_icon_skill(self):
        resume = _read("commands", "resume.md")
        phase2_start = resume.index("### Phase 2 재개")
        phase3_start = resume.index("### Phase 3 재개")
        section = resume[phase2_start:phase3_start]
        self.assertIn("autobot-app-icon", section)
        self.assertIn("app-icon-1024.png", section)

    def test_dispatcher_encodes_phase2_two_step(self):
        skill = _read("skills", "autobot-orchestrator", "SKILL.md")
        self.assertIn("autobot-app-icon", skill)
        self.assertIn("app_icon_source_present", skill)


class TestBackendEngineerConditionalDispatchProse(unittest.TestCase):
    """Finding: resume.md Phase 4 section omitted backend-engineer entirely,
    contradicting the conditional dispatch contract in agent-dispatch.md."""

    def test_resume_phase4_mentions_backend_required_condition(self):
        resume = _read("commands", "resume.md")
        phase4_start = resume.index("### Phase 4 재개")
        phase5_start = resume.index("### Phase 5 재개")
        section = resume[phase4_start:phase5_start]
        self.assertIn("backend_required", section)
        self.assertIn("backend-engineer", section)

    def test_skill_dispatcher_rule_2_states_backend_condition(self):
        skill = _read("skills", "autobot-orchestrator", "SKILL.md")
        self.assertIn("backend_required == true", skill)


class TestCompositionRootAuthorityUnified(unittest.TestCase):
    """Finding: ui-builder.md granted a 'DI wiring only' exception on CompositionRoot
    while SKILL.md claimed a gate blocks CompositionRoot edits that it never checks —
    two independently false/contradictory statements. Lock the corrected wording in
    and forbid the old exception clause from silently reappearing."""

    def test_ui_builder_has_no_di_wiring_exception(self):
        ui_builder = _read("agents", "ui-builder.md")
        self.assertNotIn("DI 주입 코드 외에는 수정 금지", ui_builder)
        self.assertIn("CompositionRoot.swift", ui_builder)
        self.assertIn("수정 금지", ui_builder)

    def test_skill_does_not_claim_gate_4to5_blocks_composition_root_edits(self):
        skill = _read("skills", "autobot-orchestrator", "SKILL.md")
        self.assertNotIn("`Models` 직접 수정 금지 — Gate 4→5 에서 차단", skill)
        self.assertIn("no_stubs_in_app", skill)


class TestDeployerOutputListsAllStatusFiles(unittest.TestCase):
    """Finding: deployer.md's Output section didn't enumerate the 4 status files
    it actually writes (register/archive/upload/invite), only deploy-status.json."""

    def test_deployer_output_enumerates_all_status_files(self):
        deployer = _read("agents", "deployer.md")
        output_section = deployer[deployer.index("**Output:**"):]
        for status_file in (
            "register-status.json",
            "archive-status.json",
            "upload-status.json",
            "invite-status.json",
            "deploy-status.json",
        ):
            self.assertIn(status_file, output_section, msg=status_file)


class TestRunSummaryBadgeIsRegeneratedNotStale(unittest.TestCase):
    """Finding: mvp.md read artifacts/latest/run-summary.json directly, which can
    point at a prior build's VERIFIED badge if the current build crashed before
    Phase 7. Consumption must regenerate from current build-state first."""

    def test_mvp_regenerates_run_summary_before_reading_badge(self):
        mvp = _read("commands", "mvp.md")
        self.assertIn("write-run-summary", mvp)
        badge_section = mvp[mvp.index("기능 검증 배지"):]
        self.assertIn("write-run-summary", badge_section)


class TestMarketBriefSelfStep(unittest.TestCase):
    """Finding: no market/competitor research step precedes Phase 1 architect
    dispatch. Orchestrator-side self-step with soft-skip when mcp-appstore is
    unavailable (falls back to architect's existing WebSearch)."""

    def test_skill_declares_market_brief_self_step(self):
        skill = _read("skills", "autobot-orchestrator", "SKILL.md")
        self.assertIn("market-brief", skill)
        self.assertIn("market-brief.json", skill)
        self.assertIn("noDirectCompetitors", skill)

    def test_mvp_flow_narrative_mentions_market_brief(self):
        mvp = _read("commands", "mvp.md")
        self.assertIn("market-brief", mvp)


class TestUiBuilderDelightGuidance(unittest.TestCase):
    """Finding: no haptic/animation guidance existed anywhere in agents/* — delight
    was structurally impossible to reach even when architect specs a hook feature."""

    def test_ui_builder_has_sensory_feedback_guidance(self):
        ui_builder = _read("agents", "ui-builder.md")
        self.assertIn("sensoryFeedback", ui_builder)
        self.assertIn("withAnimation", ui_builder)


if __name__ == "__main__":
    unittest.main()
