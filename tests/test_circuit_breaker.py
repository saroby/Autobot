"""Circuit breaker enforcement: trip + auto-skip-to-retrospective."""

from __future__ import annotations

import json
import unittest

from conftest import IsolatedProjectCase, run_pipeline


class TestCircuitBreaker(IsolatedProjectCase):

    def _force_state(self, mutation: dict) -> None:
        path = self.project_dir / ".autobot" / "build-state.json"
        s = json.loads(path.read_text())
        for key, value in mutation.items():
            s[key] = value
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2))

    def test_trip_during_advance_phase_auto_skips_remaining_phases(self):
        # Reach maxRetry=2 on phase 1, ensuring failures hit threshold=3.
        from conftest import run_pipeline as _run

        # Manually push two prior failures so the next advance-phase trips.
        s = self.state()
        s["phases"]["1"]["status"] = "failed"
        s["phases"]["1"]["retryCount"] = 1
        s["phases"]["1"]["failedAt"] = "t"
        s["phases"]["1"]["error"] = "previous"
        # Bump global retryCount so the next failure (on phase 1) hits >= 3.
        s["phases"]["2"]["retryCount"] = 1
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            __import__("json").dumps(s, ensure_ascii=False, indent=2)
        )

        _run("start-phase", "--phase", "1", "--allow-terminal-restart", project_dir=self.project_dir)
        result = _run("advance-phase", "--phase", "1", project_dir=self.project_dir)

        # Trip exit code = 2.
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        s = self.state()
        # Trip-causing phase keeps `failed` for forensics.
        self.assertEqual(s["phases"]["1"]["status"], "failed")
        # Retro auto-scheduled.
        self.assertEqual(s["phases"]["7"]["status"], "in_progress")
        # Remaining phases (2..6) marked skipped with skipReason.
        for pid in ("2", "3", "4", "5", "6"):
            self.assertEqual(s["phases"][pid]["status"], "skipped",
                             msg=f"phase {pid} expected skipped, got {s['phases'][pid]['status']}")
            self.assertIn("circuit breaker", s["phases"][pid].get("skipReason", ""))

    def test_global_threshold_blocks_in_progress(self):
        # threshold=3 in spec; force retryCount sum to 3 across phases.
        s = json.loads((self.project_dir / ".autobot" / "build-state.json").read_text())
        s["phases"]["1"] = {"status": "completed", "retryCount": 0, "completedAt": "t"}
        s["phases"]["2"] = {"status": "completed", "retryCount": 1, "completedAt": "t"}
        s["phases"]["3"] = {"status": "completed", "retryCount": 1, "completedAt": "t"}
        s["phases"]["4"] = {"status": "failed", "retryCount": 1, "failedAt": "t", "error": "x"}
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=2)
        )

        result = run_pipeline("start-phase", "--phase", "4", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("circuit breaker tripped", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
