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


class TestCheckFunctionalFlowsPass(unittest.TestCase):
    def _run(self, *, features, run_result):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(functional, "load_feature_spec", return_value=features), \
                 mock.patch.object(functional, "run_flows", return_value=run_result):
                return functional.check_functional_flows_pass(Path(tmp), "Demo", {})

    def test_no_feature_spec_is_benign_skip(self):
        out = self._run(features=None, run_result=None)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertFalse(r.get("degraded", False))

    def test_passed_flows(self):
        out = self._run(
            features=[object()],
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
            features=[object()],
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
            features=[object()],
            run_result={"status": "skipped", "skipReason": "axe_unavailable",
                        "degraded": True, "results": []},
        )
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])

    def test_benign_skip_when_no_flow_features(self):
        out = self._run(
            features=[object()],
            run_result={"status": "skipped", "skipReason": "no_features",
                        "degraded": False, "results": []},
        )
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertFalse(r.get("degraded", False))

    def test_p1_warning_does_not_fail(self):
        out = self._run(
            features=[object()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P1",
                 "passed": False, "message": "WARNING (P1): not navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])      # suite passed; P1 fail is a warning
        self.assertIn("warning", r["message"].lower())


if __name__ == "__main__":
    unittest.main()
