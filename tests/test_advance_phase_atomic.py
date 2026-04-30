"""advance-phase atomic semantics — codex Q6 regression cover."""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, run_pipeline


class TestAdvancePhaseAtomic(IsolatedProjectCase):

    def test_gate_fail_marks_phase_failed_and_increments_retry(self):
        run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        result = run_pipeline("advance-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)

        phase = self.state()["phases"]["1"]
        self.assertEqual(phase["status"], "failed")
        self.assertEqual(phase["retryCount"], 1)
        self.assertIn("gate 1->2 failed", phase.get("error", ""))

    def test_rejected_transition_does_not_touch_state_or_log(self):
        # Run advance-phase twice to reach maxRetry=2.
        for _ in range(2):
            run_pipeline("start-phase", "--phase", "1", "--allow-terminal-restart", project_dir=self.project_dir)
            run_pipeline("advance-phase", "--phase", "1", project_dir=self.project_dir)

        before_gate = self.state().get("gates", {}).get("1->2", {}).get("checkedAt")
        before_log_count = len(self.log_lines())
        self.assertIsNotNone(before_gate)

        # 3rd advance-phase: retry exhausted → transition rejected.
        result = run_pipeline("advance-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REJECTED", result.stdout + result.stderr)

        # Atomicity invariants: no new gate evidence, no new log rows.
        after_gate = self.state().get("gates", {}).get("1->2", {}).get("checkedAt")
        after_log_count = len(self.log_lines())
        self.assertEqual(before_gate, after_gate, "gate evidence must not change on rejected transition")
        self.assertEqual(before_log_count, after_log_count, "build-log must not gain rows on rejected transition")


if __name__ == "__main__":
    unittest.main()
