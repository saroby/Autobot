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


if __name__ == "__main__":
    unittest.main()
