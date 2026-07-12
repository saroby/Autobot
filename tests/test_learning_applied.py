"""learning_applied event records into state.learningsConsumed and gates can
check the field via state_field_contains.
"""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, run_build_log


class TestLearningApplied(IsolatedProjectCase):

    def test_learning_applied_accumulates_into_state(self):
        result = run_build_log(
            "--event", "learning_applied",
            "--phase", "1", "--agent", "architect",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        consumed = self.state()["phases"]["1"].get("learningsConsumed", [])
        self.assertIn("architect", consumed)

    def test_learning_applied_dedupes(self):
        for _ in range(3):
            result = run_build_log(
                "--event", "learning_applied",
                "--phase", "4", "--agent", "ui-builder",
                project_dir=self.project_dir,
            )
            self.assertEqual(result.returncode, 0)

        consumed = self.state()["phases"]["4"].get("learningsConsumed", [])
        # Same agent recorded multiple times must collapse to one entry.
        self.assertEqual(consumed.count("ui-builder"), 1)

    def test_multiple_agents_accumulate_sorted(self):
        for agent in ("data-engineer", "ui-builder", "backend-engineer"):
            run_build_log(
                "--event", "learning_applied",
                "--phase", "4", "--agent", agent,
                project_dir=self.project_dir,
            )
        consumed = self.state()["phases"]["4"].get("learningsConsumed", [])
        self.assertEqual(consumed, ["backend-engineer", "data-engineer", "ui-builder"])

    def test_rule_records_structured_entry_plus_agent_name(self):
        # --rule records a per-rule structured entry (for rule-granular grading)
        # WITHOUT dropping the bare agent name the *_consumed_learnings gate
        # asserts via state_field_contains.
        result = run_build_log(
            "--event", "learning_applied",
            "--phase", "4", "--agent", "ui-builder",
            "--rule", "pin the design-system module import",
            "--rule", "attach feature anchors to every P0 cta",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        consumed = self.state()["phases"]["4"].get("learningsConsumed", [])
        # Gate-visible agent name still present.
        self.assertIn("ui-builder", consumed)
        # One structured record per rule, each with id + rule + agent.
        rule_recs = [c for c in consumed if isinstance(c, dict)]
        self.assertEqual(len(rule_recs), 2)
        self.assertEqual({r["agent"] for r in rule_recs}, {"ui-builder"})
        rules = {r["rule"] for r in rule_recs}
        self.assertIn("pin the design-system module import", rules)
        self.assertTrue(all(r.get("id") for r in rule_recs))

    def test_first_build_empty_sources_records_agent(self):
        # First build (no learning files): learning-bootstrap.md now instructs
        # recording with sources:[] and NO --rule instead of skipping — the
        # gate's learningsConsumed requirement is satisfied without fabricating
        # fake rules ("clean first build").
        result = run_build_log(
            "--event", "learning_applied",
            "--phase", "1", "--agent", "architect",
            "--detail", '{"sources":[]}',
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        consumed = self.state()["phases"]["1"].get("learningsConsumed", [])
        self.assertIn("architect", consumed)
        # No structured rule records — nothing for grading to mint items from.
        self.assertEqual([c for c in consumed if isinstance(c, dict)], [])

    def test_rule_records_dedupe_by_id(self):
        for _ in range(3):
            run_build_log(
                "--event", "learning_applied",
                "--phase", "4", "--agent", "ui-builder",
                "--rule", "same rule twice",
                project_dir=self.project_dir,
            )
        consumed = self.state()["phases"]["4"].get("learningsConsumed", [])
        rule_recs = [c for c in consumed if isinstance(c, dict)]
        self.assertEqual(len(rule_recs), 1)
        self.assertEqual(consumed.count("ui-builder"), 1)


if __name__ == "__main__":
    unittest.main()
