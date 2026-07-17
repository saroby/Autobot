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
        # The retro (phase 7) is forced in_progress, so it must NOT also carry a
        # "skip" build-log event — that would be a contradictory audit trail.
        retro_skips = [
            e for e in self.log_lines()
            if e.get("event") == "skip" and str(e.get("phase")) == "7"
        ]
        self.assertEqual(retro_skips, [], f"retro must not be logged as skipped: {retro_skips}")

    def _trip_global_threshold(self) -> None:
        # threshold=3 in spec; force retryCount sum to 3 across phases, with the
        # trip-causing phase 4 left `failed` (retry 1 < maxRetry 2) and phase 3
        # completed so phase 4's dependency is satisfied.
        s = json.loads((self.project_dir / ".autobot" / "build-state.json").read_text())
        s["phases"]["1"] = {"status": "completed", "retryCount": 0, "completedAt": "t"}
        s["phases"]["2"] = {"status": "completed", "retryCount": 1, "completedAt": "t"}
        s["phases"]["3"] = {"status": "completed", "retryCount": 1, "completedAt": "t"}
        s["phases"]["4"] = {"status": "failed", "retryCount": 1, "failedAt": "t", "error": "x"}
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=2)
        )

    def test_global_threshold_blocks_in_progress(self):
        self._trip_global_threshold()
        result = run_pipeline("start-phase", "--phase", "4", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("circuit breaker tripped", result.stdout + result.stderr)

    def test_fail_phase_path_trips_breaker_and_schedules_retrospective(self):
        # Residual failed sibling (2.5 left behind by /autobot:plan) + two
        # fail-phase failures on Phase 5 cross the global threshold on the
        # fail-phase path. Previously only advance-phase handled the trip:
        # no circuit_open event, no auto-scheduled retrospective → deadlock.
        path = self.project_dir / ".autobot" / "build-state.json"
        s = self.state()
        s["phases"]["1"] = {"status": "completed", "completedAt": "t"}
        s["phases"]["2"] = {"status": "completed", "completedAt": "t"}
        s["phases"]["2.5"] = {"status": "failed", "failedAt": "t", "error": "plan residue", "retryCount": 1}
        s["phases"]["3"] = {"status": "completed", "completedAt": "t"}
        s["phases"]["4"] = {"status": "completed", "completedAt": "t"}
        s["phases"]["5"] = {"status": "in_progress", "startedAt": "t"}
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2))

        first = run_pipeline(
            "fail-phase", "--phase", "5", "--error", "xcodebuild failed",
            "--increment-retry", project_dir=self.project_dir,
        )
        self.assertEqual(first.returncode, 0, msg=first.stdout + first.stderr)
        self.assertNotIn("circuit breaker tripped", first.stdout)

        retry = run_pipeline("start-phase", "--phase", "5", project_dir=self.project_dir)
        self.assertEqual(retry.returncode, 0, msg=retry.stdout + retry.stderr)

        second = run_pipeline(
            "fail-phase", "--phase", "5", "--error", "xcodebuild failed again",
            "--increment-retry", project_dir=self.project_dir,
        )
        self.assertEqual(second.returncode, 0, msg=second.stdout + second.stderr)
        self.assertIn("circuit breaker tripped", second.stdout)

        s = self.state()
        self.assertEqual(s["phases"]["5"]["status"], "failed")
        self.assertEqual(s["phases"]["7"]["status"], "in_progress")
        self.assertEqual(s["phases"]["6"]["status"], "skipped")
        self.assertIn("circuit breaker", s["phases"]["6"].get("skipReason", ""))
        self.assertIn("circuit_open", [e.get("event") for e in self.log_lines()])

    def test_retro_start_permitted_after_trip_without_flag(self):
        # alwaysRun exemption: onTrip=skipToRetrospective promises "only Phase 7
        # proceeds" — retro entry must survive a tripped breaker even when the
        # trip handler never ran (historical/legacy state).
        self._trip_global_threshold()
        result = run_pipeline("start-phase", "--phase", "7", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.state()["phases"]["7"]["status"], "in_progress")

    def test_operator_override_is_audited_in_state_and_log(self):
        self._trip_global_threshold()
        forced = run_pipeline(
            "start-phase", "--phase", "4", "--allow-terminal-restart",
            project_dir=self.project_dir,
        )
        self.assertEqual(forced.returncode, 0, msg=forced.stdout + forced.stderr)

        phase = self.state()["phases"]["4"]
        self.assertEqual(phase["operatorOverrides"], 1)
        last = phase["lastOperatorOverride"]
        self.assertEqual(last["priorRetryCount"], 1)
        self.assertEqual(last["breakerFailures"], 3)
        self.assertEqual(last["threshold"], 3)

        start_events = [
            e for e in self.log_lines()
            if e.get("event") == "start" and str(e.get("phase")) == "4"
        ]
        self.assertTrue(start_events, "start event for phase 4 missing from build-log")
        self.assertIs(start_events[-1]["detail"].get("operatorOverride"), True)

    def test_explicit_restart_overrides_tripped_breaker(self):
        # The documented `/autobot:resume <N> --allow-terminal-restart` recovery
        # must survive a tripped breaker; otherwise the only escape is
        # `rm -rf build-state.json` (losing all completed work).
        self._trip_global_threshold()

        # No flag → breaker still guards the autonomous path (regression guard).
        blocked = run_pipeline("start-phase", "--phase", "4", project_dir=self.project_dir)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("circuit breaker tripped", blocked.stdout + blocked.stderr)

        # --allow-terminal-restart = operator override → breaker is cleared.
        forced = run_pipeline(
            "start-phase", "--phase", "4", "--allow-terminal-restart",
            project_dir=self.project_dir,
        )
        self.assertEqual(forced.returncode, 0, msg=forced.stdout + forced.stderr)
        self.assertEqual(self.state()["phases"]["4"]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
