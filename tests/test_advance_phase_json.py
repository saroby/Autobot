"""The actual advance-phase CLI must emit one JSON value on every result path."""

from __future__ import annotations

import json
import unittest

from conftest import IsolatedProjectCase, run_pipeline


class TestAdvancePhaseJson(IsolatedProjectCase):
    def advance(self, phase):
        result = run_pipeline(
            "advance-phase", "--phase", phase, "--format", "json",
            project_dir=self.project_dir,
        )
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            self.fail(f"Invalid JSON stdout: {result.stdout!r}; stderr: {result.stderr!r}")
        self.assertEqual(payload["returnCode"], result.returncode)
        self.assertIsInstance(payload["messages"], list)
        return result, payload

    def restart_phase_zero(self):
        result = run_pipeline(
            "start-phase", "--phase", "0", "--allow-terminal-restart",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_success_is_parseable_json(self):
        self.restart_phase_zero()

        result, payload = self.advance("0")

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["passed"])
        self.assertEqual(self.state()["phases"]["0"]["status"], "completed")

    def test_hard_gate_failure_is_parseable_json(self):
        run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)

        result, payload = self.advance("1")

        self.assertEqual(result.returncode, 1)
        self.assertFalse(payload["passed"])
        self.assertEqual(self.state()["phases"]["1"]["status"], "failed")

    def test_rejected_transition_is_parseable_json_without_mutation(self):
        before = self.state()
        before_log = self.log_lines()

        result, payload = self.advance("0")

        self.assertEqual(result.returncode, 1)
        self.assertTrue(any("REJECTED" in message for message in payload["messages"]))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.log_lines(), before_log)

    def test_phase_without_gate_is_parseable_json(self):
        state = self.state()
        state["phases"]["7"] = {"status": "in_progress", "startedAt": "t"}
        state_path = self.project_dir / ".autobot/build-state.json"
        state_path.write_text(json.dumps(state))

        result, payload = self.advance("7")

        self.assertEqual(result.returncode, 0)
        self.assertTrue(any("no gate" in message for message in payload["messages"]))
        self.assertEqual(self.state()["phases"]["7"]["status"], "completed")

    def test_schema_warnings_do_not_pollute_json_stdout(self):
        self.restart_phase_zero()
        state = self.state()
        state.pop("contracts")
        state_path = self.project_dir / ".autobot/build-state.json"
        state_path.write_text(json.dumps(state))

        result, payload = self.advance("0")

        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["passed"])
        self.assertIn("WARN: Missing recommended field: contracts", result.stderr)


if __name__ == "__main__":
    unittest.main()
