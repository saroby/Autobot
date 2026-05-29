"""Agent prompts must instruct per-feature anchor attachment (ui-builder) and a
functional-acceptance test standard (quality-engineer). These keep the prompts
in sync with the feature-spec spine gates.
"""
from __future__ import annotations

import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parent.parent / "agents"


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


if __name__ == "__main__":
    unittest.main()
