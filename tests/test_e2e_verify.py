"""Unit tests for the e2e harness verdict logic (scripts/e2e_verify.py::evaluate).

The pure verdict function is testable without any Mac/simulator: it maps the
two check result lists + an expectation to a pass/fail. The full hardware run is
proven by scripts/e2e_verify.py itself (locally + the e2e-verify.yml CI job).
"""
from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

import e2e_verify  # noqa: E402


def _ok(passed, *, skipped=False, degraded=False, msg="m"):
    r = {"check": "c", "passed": passed, "message": msg}
    if skipped:
        r["skipped"] = True
    if degraded:
        r["degraded"] = True
    return [r]


class TestEvaluate(unittest.TestCase):
    def test_verified_when_both_pass(self):
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(True), "verified")
        self.assertTrue(ok)

    def test_verified_fails_when_flow_failed(self):
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(False), "verified")
        self.assertFalse(ok)

    def test_verified_fails_when_logic_degraded(self):
        # a degraded (skipped+degraded) logic check is not a real pass
        ok, _ = e2e_verify.evaluate(_ok(False, skipped=True, degraded=True), _ok(True), "verified")
        self.assertFalse(ok)

    def test_verified_fails_when_flow_degraded(self):
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(False, skipped=True, degraded=True), "verified")
        self.assertFalse(ok)

    def test_flow_fail_ok_when_flow_hard_fails(self):
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(False), "flow-fail")
        self.assertTrue(ok)

    def test_flow_fail_not_ok_when_flow_passed(self):
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(True), "flow-fail")
        self.assertFalse(ok)

    def test_flow_fail_not_ok_when_flow_only_degraded_skip(self):
        # a degraded skip is NOT a hard fail — the detector didn't actually run,
        # so "expected hard-fail" is not satisfied.
        ok, _ = e2e_verify.evaluate(_ok(True), _ok(False, skipped=True, degraded=True), "flow-fail")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
