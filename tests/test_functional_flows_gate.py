"""Tests for check_functional_flows_pass — maps flow_runner.run_flows output
to the three-valued gate verdict via _ok(..., skipped=, degraded=)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks import functional  # noqa: E402


class _P0Feature:
    """Minimal feature stand-in — a P0 must exist for flows to be judged
    (zero-P0 specs hard-fail up front; see the dedicated test below)."""
    priority = "P0"


class TestCheckFunctionalFlowsPass(unittest.TestCase):
    def _run(self, *, features, run_result, state=None):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(functional, "load_feature_spec", return_value=features), \
                 mock.patch.object(functional, "run_flows", return_value=run_result):
                return functional.check_functional_flows_pass(Path(tmp), "Demo", state or {})

    def test_no_feature_spec_is_degraded_skip(self):
        out = self._run(features=None, run_result=None)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertTrue(r.get("degraded", False))

    def test_passed_flows(self):
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P0",
                 "passed": True, "message": "navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertFalse(r.get("degraded", False))

    def test_p0_failure_is_hard_fail(self):
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "failed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P0",
                 "passed": False, "message": "entry anchor never ready"}]},
        )
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))   # ran and truly failed = hard fail
        self.assertFalse(r.get("degraded", False))

    def test_degraded_skip_when_axe_missing(self):
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "skipped", "skipReason": "axe_unavailable",
                        "degraded": True, "results": []},
        )
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])

    def test_zero_p0_features_is_hard_fail(self):
        # Features exist but none is P0 (the bare object has no .priority) —
        # nothing would ever be ENFORCED at runtime (P1 failures only warn), so
        # the old benign skip laundered an unverified build to VERIFIED.
        # Deterministic P0 count → hard fail (defense-in-depth for Gate 1->2's
        # zero-P0 rejection). run_flows must not even be consulted.
        out = self._run(features=[object()], run_result=None)
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertFalse(r.get("degraded", False))
        self.assertIn("P0", r["message"])

    def test_no_flow_but_p0_present_is_hard_fail(self):
        # A P0 feature exists but run_flows benign-skipped (no flow acceptance):
        # the spec slipped past Gate 1->2. Refuse it here too — benign-skipping
        # would launder a logic-only build to VERIFIED with no flow ever run.
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "skipped", "skipReason": "no_features",
                        "degraded": False, "results": []},
        )
        r = out[0]
        self.assertFalse(r["passed"])          # hard fail, not a skip
        self.assertFalse(r.get("skipped", False))
        self.assertFalse(r.get("degraded", False))
        self.assertIn("flow", r["message"].lower())

    def test_p1_flake_above_floor_is_warning_not_fail(self):
        # 3/4 P1 flows pass (75% >= 70% floor): a stray flake stays a warning
        # so autonomous completion is not held hostage.
        p1_pass = [
            {"featureId": f"f{i}", "acceptanceId": "a1", "priority": "P1",
             "passed": True, "message": "ok"} for i in range(3)
        ]
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "passed", "results": p1_pass + [
                {"featureId": "f9", "acceptanceId": "a1", "priority": "P1",
                 "passed": False, "message": "WARNING (P1): not navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])      # suite passed; P1 fail is a warning
        self.assertFalse(r.get("degraded", False))
        self.assertIn("warning", r["message"].lower())

    def test_p1_pass_rate_below_floor_is_degraded(self):
        # A mostly-broken P1 tier (here 0/1 = 0% < 70%) must not hide under a
        # green badge even in default mode — DEGRADED (shipping-blocked), but
        # never a hard fail (no circuit-breaker retry).
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P1",
                 "passed": False, "message": "WARNING (P1): not navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])       # not a hard fail
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])     # shipping-blocked
        self.assertIn("70%", r["message"])

    def test_p1_failure_degraded_in_quality_max(self):
        # quality-max (#4 P1 hard mode): a P1 flow failure is no longer a warning
        # under a green badge — DEGRADED (shipping-blocked), but NOT a hard fail
        # (that would trip the circuit breaker). Default mode is unchanged (above).
        out = self._run(
            features=[_P0Feature()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P1",
                 "passed": False, "message": "not navigated"}]},
            state={"qualityMax": True},
        )
        r = out[0]
        self.assertTrue(r["passed"])       # not a hard fail
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])     # shipping-blocked
        self.assertIn("quality-max", r["message"].lower())


class TestLogicTestCompleteness(unittest.TestCase):
    """_completeness_subcheck — P0 logic acceptance ↔ named test coverage.

    Missing P0 named coverage is always DEGRADED (shipping-blocked,
    deterministic, not a hard fail). bundle=None means every acceptance is
    missing and isolates that branch.
    """
    from pathlib import Path as _P

    def _feat(self):
        return functional._FeatureLite(
            feature_id="log-workout", priority="P0", logic_acceptance_ids=["calc-streak"]
        )

    def test_default_missing_is_degraded(self):
        r = functional._completeness_subcheck(self._P("/tmp"), None, [self._feat()], quality_max=False)
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded", False))

    def test_quality_max_missing_is_degraded(self):
        r = functional._completeness_subcheck(self._P("/tmp"), None, [self._feat()], quality_max=True)
        self.assertTrue(r["passed"])          # not a hard fail
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))    # shipping-blocked
        self.assertIn("degraded", r["message"].lower())

    def test_no_features_is_clean(self):
        r = functional._completeness_subcheck(self._P("/tmp"), None, [], quality_max=True)
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))

    def test_p1_missing_is_warning_not_degraded(self):
        # P1 logic gaps mirror P1 flow semantics: recorded, never blocking.
        p1 = functional._FeatureLite(
            feature_id="search", priority="P1", logic_acceptance_ids=["rank-results"]
        )
        r = functional._completeness_subcheck(self._P("/tmp"), None, [p1], quality_max=False)
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))
        self.assertIn("warning", r["message"].lower())
        self.assertIn("coverage 0%", r["message"])

    def test_coverage_percent_in_message(self):
        # run-summary consumes gate messages — the coverage % must ride along.
        r = functional._completeness_subcheck(self._P("/tmp"), None, [self._feat()], quality_max=False)
        self.assertIn("coverage 0% (0/1)", r["message"])


if __name__ == "__main__":
    unittest.main()
