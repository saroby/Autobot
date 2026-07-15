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


if __name__ == "__main__":
    unittest.main()
