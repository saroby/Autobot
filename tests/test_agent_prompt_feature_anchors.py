"""Agent prompts must instruct per-feature anchor attachment (ui-builder) and a
functional-acceptance test standard (quality-engineer). These keep the prompts
in sync with the feature-spec spine gates.
"""
from __future__ import annotations

import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent / "agents"
PLUGIN_DIR = AGENTS.parent


class TestAgentPrompts(unittest.TestCase):
    def test_ui_builder_mentions_feature_spec_anchor(self):
        text = (AGENTS / "ui-builder.md").read_text(encoding="utf-8")
        self.assertIn("feature-spec.json", text)
        self.assertIn("feature", text.lower())
        # the per-feature anchor field must be named so the agent attaches it
        self.assertIn(".accessibilityIdentifier", text)

    def test_quality_engineer_requires_functional_acceptance(self):
        text = (AGENTS / "quality-engineer.md").read_text(encoding="utf-8")
        self.assertIn("functional acceptance", text.lower())
        self.assertIn("P0", text)
        self.assertIn("compile", text.lower())

    def test_agents_inherit_the_host_model(self):
        pinned = []
        for path in sorted(AGENTS.glob("*.md")):
            frontmatter = path.read_text(encoding="utf-8").split("---", 2)[1]
            if any(line.strip().startswith("model:") for line in frontmatter.splitlines()):
                pinned.append(path.name)
        self.assertEqual([], pinned)

    def test_dispatch_has_one_provider_neutral_path(self):
        text = (
            PLUGIN_DIR / "skills" / "autobot-orchestrator" /
            "references" / "agent-dispatch.md"
        ).read_text(encoding="utf-8")
        for obsolete in ("TeamCreate", "SendMessage", "run_in_background", "claude-sonnet"):
            self.assertNotIn(obsolete, text)
        self.assertIn("context-pack", text)


class TestPlanningDepthPromptContracts(unittest.TestCase):
    """2026-07-17 약점 감사 — 기획 깊이 프롬프트/템플릿 층.

    프롬프트 층이 기획-깊이 계약(market-brief 사다리, Features 구성 요건 4종,
    feature-spec `role`, firstRunPolicy, Hook & Retention, 비-CRUD 파생 메서드,
    codex 리뷰 planningViolations)과 desync 되면 여기서 잡는다.
    """

    @classmethod
    def setUpClass(cls):
        cls.architect = (AGENTS / "architect.md").read_text(encoding="utf-8")
        cls.data_engineer = (AGENTS / "data-engineer.md").read_text(encoding="utf-8")
        refs = PLUGIN_DIR / "skills" / "autobot-orchestrator" / "references"
        cls.template = (refs / "architecture-template.md").read_text(encoding="utf-8")
        cls.patterns = (refs / "planning-patterns.md").read_text(encoding="utf-8")
        cls.plan_preview = (
            PLUGIN_DIR / "skills" / "autobot-plan-preview" / "SKILL.md"
        ).read_text(encoding="utf-8")
        cls.codex_review = (
            PLUGIN_DIR / "scripts" / "codex-architecture-review.sh"
        ).read_text(encoding="utf-8")

    def test_architect_market_context_research_ladder(self):
        # 사다리: market-brief.json 필수 소비 → WebSearch 직접 조사 → model-knowledge 표기
        self.assertIn("## Market Context", self.architect)
        self.assertIn("market-brief.json", self.architect)
        self.assertIn("(model-knowledge only, no live research)", self.architect)
        # WebSearch 가 tools 라인 외에 본문 지시로도 등장해야 한다 (사문화 방지)
        body = self.architect.split("---", 2)[2]
        self.assertIn("WebSearch", body)

    def test_architect_feature_composition_requirements(self):
        for token in ("table-stakes ≥3", "feature_spec_depth"):
            self.assertIn(token, self.architect)
        # Simple > Complex 는 구현 방식 한정 — 기능 구성 축소 근거 금지
        self.assertIn("구현 방식", self.architect)
        self.assertNotIn("- Simple > Complex. Apple", self.architect)

    def test_architect_feature_spec_role_field(self):
        self.assertIn('"role"', self.architect)
        for role in ("table-stakes", "hook", "retention", "insight"):
            self.assertIn(role, self.architect)

    def test_architect_first_run_policy(self):
        self.assertIn("firstRunPolicy", self.architect)
        self.assertIn('"primer"', self.architect)
        self.assertIn("## First-Run Experience", self.architect)

    def test_architect_non_crud_derived_method_rule(self):
        self.assertIn("비-CRUD", self.architect)
        self.assertIn("service_protocol_depth", self.architect)

    def test_architect_multistep_journey_rule(self):
        self.assertIn("steps ≥2", self.architect)
        self.assertIn("역방향 acceptance", self.architect)

    def test_architect_hook_retention_bullet(self):
        self.assertIn("### Hook & Retention", self.architect)
        self.assertIn("hook_retention_present", self.architect)
        # 연결 규칙: 훅 기능은 Features 표에 P0 로 실재
        self.assertIn("P0 로 존재", self.architect)

    def test_template_market_context_section(self):
        self.assertIn("## Market Context", self.template)
        self.assertIn("(model-knowledge only, no live research)", self.template)

    def test_template_hook_retention_section(self):
        self.assertIn("### Hook & Retention", self.template)
        # ❌/✅ 대조표 + 자가 점검 (Signature Layout 과 동형)
        self.assertIn("❌ 무효", self.template)
        self.assertIn("✅ 유효", self.template)
        self.assertIn("P0 로 존재", self.template)

    def test_template_features_roles_and_delight(self):
        self.assertIn("| Role |", self.template)
        for role in ("table-stakes", "hook", "retention", "insight"):
            self.assertIn(role, self.template)
        self.assertIn("delight", self.template)

    def test_template_integration_map_derived_verbs(self):
        self.assertIn("weeklySummary", self.template)
        self.assertIn("currentStreak", self.template)

    def test_template_first_run_experience(self):
        self.assertIn("## First-Run Experience", self.template)
        self.assertIn("firstRunPolicy", self.template)

    def test_data_engineer_repository_derived_method(self):
        self.assertIn("weeklySummary", self.data_engineer)
        self.assertIn("비-CRUD", self.data_engineer)

    def test_planning_patterns_floors_not_caps(self):
        self.assertIn("최소치(floor)", self.patterns)
        # 옛 상한 표기("3-5" 스크린 레인지)가 되살아나면 안 된다
        self.assertNotIn("| Simple | 3-5 | 2-3 |", self.patterns)

    def test_planning_patterns_delight_p1_required(self):
        self.assertIn("delight P1", self.patterns)
        self.assertNotIn("Polish features (skip for MVP)", self.patterns)

    def test_plan_preview_planning_axis_attraction_items(self):
        for token in ("차별점이 말뿐", "훅 부재", "재방문 이유 부재", "권한 다이얼로그"):
            self.assertIn(token, self.plan_preview)

    def test_codex_review_planning_violations_separate_key(self):
        # schema + 프롬프트 + persist 세 곳 모두에 별도 키로 존재
        self.assertGreaterEqual(self.codex_review.count("planningViolations"), 3)
        # 기획 위반은 경고-only — verdict 는 hard violations 만 결정
        self.assertIn("NEVER change the verdict", self.codex_review)
        self.assertIn("planningViolationsCount", self.codex_review)


if __name__ == "__main__":
    unittest.main()
