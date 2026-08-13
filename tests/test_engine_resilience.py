"""Engine state-machine resilience — WS2 regression cover.

1. retryCount resets on success → the breaker's declared 'consecutive'
   semantics (spec.policies.circuitBreaker.maxConsecutivePhaseFailures) hold:
   scattered within-budget retries must not kill an unattended build.
2. Crash reclaim (in_progress → in_progress) and retry-exhausted phases are
   recoverable via the explicit --allow-terminal-restart operator flag, and
   ONLY via the flag (autonomous path unchanged).
3. A phase added to the spec after a build-state was written (the "2.5" case)
   is backfilled as pending instead of bricking every mutation.
4. learning_applied validates the log event BEFORE mutating state, so a bad
   detail can no longer leave gate-satisfying state without an audit row.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import (
    IsolatedProjectCase,
    import_runtime_modules,
    run_build_log,
    run_pipeline,
)

import_runtime_modules()

import phase_advance  # noqa: E402
import transitions  # noqa: E402
from spec_loader import load_spec  # noqa: E402
from transitions import circuit_breaker_tripped, update_phase_status  # noqa: E402


class TestRetryCountResetsOnSuccess(unittest.TestCase):
    """Unit-level: transitions.update_phase_status success branches."""

    def setUp(self) -> None:
        self.spec = load_spec()
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / ".autobot" / "build-state.json"
        self.state_path.parent.mkdir(parents=True)
        phases = {pid: {"status": "pending"} for pid in self.spec["phases"]}
        phases["0"] = {"status": "completed", "completedAt": "t"}
        self.state_path.write_text(json.dumps({
            "schemaVersion": self.spec.get("schemaVersion"),
            "buildId": "b", "appName": "TestApp", "displayName": "Test",
            "phases": phases,
        }))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _step(self, phase: str, status: str, **kwargs) -> None:
        ok, messages, _ = update_phase_status(
            self.spec, self.state_path,
            phase=phase, target_status=status, **kwargs,
        )
        self.assertTrue(ok, msg=f"{phase}→{status}: " + "\n".join(messages))

    def _phases(self) -> dict:
        return json.loads(self.state_path.read_text())["phases"]

    def test_fail_recover_across_three_phases_does_not_trip_breaker(self):
        # Phases 1, 4, 5 (each maxRetry=2) fail once then recover — every
        # phase stays within its own retry budget. Before the reset-on-success
        # fix the global breaker summed the stale counts (1+1+1 = threshold 3)
        # and rejected phase 5's retry restart.
        for pid in ("1", "2", "3", "4", "5"):
            fail_once = pid in ("1", "4", "5")
            self._step(pid, "in_progress")
            if fail_once:
                self._step(pid, "failed", error="boom", increment_retry=True)
                self._step(pid, "in_progress")  # retry within budget
            self._step(pid, "completed")
            self.assertNotIn(
                "retryCount", self._phases()[pid],
                f"phase {pid} must drop retryCount on success",
            )
        tripped, failures, threshold, scope = circuit_breaker_tripped(
            self.spec, json.loads(self.state_path.read_text()),
        )
        self.assertFalse(
            tripped,
            f"breaker tripped ({scope} {failures} ≥ {threshold}) despite every "
            "phase recovering within its own retry budget",
        )

    def test_fallback_also_resets_retry_count(self):
        # Phase 1 (maxRetry=2) fails once, then lands on the fallback branch.
        self._step("1", "in_progress")
        self._step("1", "failed", error="agent down", increment_retry=True)
        self._step("1", "in_progress")
        self._step("1", "fallback")
        self.assertNotIn("retryCount", self._phases()["1"])


class TestAdvancePhaseSuccessResetsRetryCount(unittest.TestCase):
    """phase_advance success mutate is a separate code path from transitions."""

    def test_gate_pass_pops_retry_count(self):
        proj = Path(tempfile.mkdtemp())
        state_path = proj / ".autobot" / "build-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "buildId": "test", "appName": "X", "displayName": "X",
            "bundleId": "x.x", "backendRequired": False,
            "phases": {
                "0": {"status": "completed"}, "1": {"status": "completed"},
                "2": {"status": "in_progress", "retryCount": 1},
                "2.5": {"status": "pending"},
                "3": {"status": "pending"}, "4": {"status": "pending"},
                "5": {"status": "pending"}, "6": {"status": "pending"},
                "7": {"status": "pending"},
            },
            "environment": {"axiom": False, "fastlane": False, "ascConfigured": False},
        }))
        args = types.SimpleNamespace(
            phase=2, project_dir=str(proj), state_file=None,
            app_name="X", status="completed", at="2026-07-12T00:00:00Z",
            detail=None, metadata=None, format="json",
        )

        def fake_gate(gate_id, pd, app, state, spec):
            return {"passed": True, "checks": [], "gate": gate_id}

        with patch.object(phase_advance, "execute_gate", side_effect=fake_gate):
            result = phase_advance._advance_phase_core(args)

        self.assertEqual(result.return_code, 0, msg="\n".join(result.messages))
        phases = json.loads(state_path.read_text())["phases"]
        self.assertEqual(phases["2"]["status"], "completed")
        self.assertNotIn("retryCount", phases["2"])


class TestOperatorRestartRecovery(IsolatedProjectCase):
    """Crash reclaim + retry-exhausted escape — flag-gated, autonomous path unchanged."""

    def test_in_progress_reclaim_requires_explicit_flag(self):
        result = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

        # Autonomous path (no flag): a second start on an in_progress phase
        # stays rejected — the reclaim is an operator decision.
        blocked = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("REJECTED", blocked.stdout + blocked.stderr)

        # Operator crash-reclaim path: explicit flag allows in_progress→in_progress.
        forced = run_pipeline(
            "start-phase", "--phase", "1", "--allow-terminal-restart",
            project_dir=self.project_dir,
        )
        self.assertEqual(forced.returncode, 0, msg=forced.stdout + forced.stderr)
        self.assertEqual(self.state()["phases"]["1"]["status"], "in_progress")

    def test_retry_exhausted_phase_recoverable_only_with_flag(self):
        # Force phase 1 into failed with retryCount == maxRetry (2).
        path = self.project_dir / ".autobot" / "build-state.json"
        s = json.loads(path.read_text())
        s["phases"]["1"] = {"status": "failed", "failedAt": "t", "error": "x", "retryCount": 2}
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2))

        blocked = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("exhausted retries", blocked.stdout + blocked.stderr)

        forced = run_pipeline(
            "start-phase", "--phase", "1", "--allow-terminal-restart",
            project_dir=self.project_dir,
        )
        self.assertEqual(forced.returncode, 0, msg=forced.stdout + forced.stderr)
        self.assertEqual(self.state()["phases"]["1"]["status"], "in_progress")


class TestSpecGrownPhaseBackfill(IsolatedProjectCase):
    """A build-state written before a spec phase existed must stay mutable."""

    def _drop_phase_25(self) -> None:
        path = self.project_dir / ".autobot" / "build-state.json"
        s = json.loads(path.read_text())
        del s["phases"]["2.5"]
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2))

    def test_mutation_backfills_missing_phase_as_pending(self):
        self._drop_phase_25()
        result = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        s = self.state()
        self.assertEqual(s["phases"]["1"]["status"], "in_progress")
        self.assertEqual(s["phases"]["2.5"], {"status": "pending"})

    def test_validate_schema_warns_instead_of_erroring(self):
        self._drop_phase_25()
        result = run_pipeline("schema", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Missing phase 2.5", result.stdout)
        self.assertIn("WARN", result.stdout)


class TestTransitionRevalidatedInsideLock(unittest.TestCase):
    """TOCTOU guard: the pre-validation done outside the write lock must be
    re-checked against the FRESH state inside the lock."""

    def test_concurrent_retry_exhaustion_rejected_inside_lock(self):
        spec = load_spec()
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / ".autobot" / "build-state.json"
            state_path.parent.mkdir(parents=True)
            phases = {pid: {"status": "pending"} for pid in spec["phases"]}
            phases["0"] = {"status": "completed", "completedAt": "t"}
            phases["1"] = {"status": "failed", "failedAt": "t", "error": "x", "retryCount": 2}
            disk_state = {
                "schemaVersion": spec.get("schemaVersion"),
                "buildId": "b", "appName": "TestApp", "displayName": "Test",
                "phases": phases,
            }
            state_path.write_text(json.dumps(disk_state))

            # The pre-validation read sees a STALE state (retryCount below max),
            # as if a concurrent fail-phase exhausted the retries right after
            # the check but before the write lock was taken.
            stale = json.loads(json.dumps(disk_state))
            stale["phases"]["1"]["retryCount"] = 1

            with patch.object(transitions, "load_state", return_value=stale):
                ok, messages, _ = update_phase_status(
                    spec, state_path, phase="1", target_status="in_progress",
                )

            self.assertFalse(ok, "in-lock re-validation must reject the stale transition")
            self.assertIn("exhausted retries", "\n".join(messages))
            final = json.loads(state_path.read_text())["phases"]["1"]
            self.assertEqual(final["status"], "failed", "rejected transition must not write")


class TestLegacySchemaVersionPromotion(IsolatedProjectCase):
    """A legacy-version state that passes validation is promoted on write,
    so the 'legacy compat mode' WARN is not emitted forever."""

    def test_mutation_promotes_schema_version(self):
        spec_version = load_spec().get("schemaVersion")
        path = self.project_dir / ".autobot" / "build-state.json"
        s = json.loads(path.read_text())
        s["schemaVersion"] = spec_version - 1
        path.write_text(json.dumps(s, ensure_ascii=False, indent=2))

        result = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(self.state()["schemaVersion"], spec_version)


class TestLearningAppliedValidatesBeforeMutation(IsolatedProjectCase):
    """Invalid learning_applied detail must not leave learningsConsumed behind."""

    def test_invalid_detail_leaves_state_and_log_untouched(self):
        log_before = len(self.log_lines())
        result = run_build_log(
            "--event", "learning_applied", "--phase", "1", "--agent", "architect",
            "--detail", '{"nope": 1}',  # detailSchema requires "sources"
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid build-log event", result.stdout + result.stderr)
        self.assertNotIn("learningsConsumed", self.state()["phases"]["1"])
        self.assertEqual(len(self.log_lines()), log_before)

    def test_valid_detail_still_records(self):
        result = run_build_log(
            "--event", "learning_applied", "--phase", "1", "--agent", "architect",
            "--detail", '{"sources": []}',
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("architect", self.state()["phases"]["1"]["learningsConsumed"])


if __name__ == "__main__":
    unittest.main()
