"""Three-valued (passed / degraded / failed) gate verdict — unit + e2e cover.

stdlib unittest only (see tests/run_tests.sh). Mirrors test_advance_phase_atomic.py.
"""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, import_runtime_modules, run_pipeline

import_runtime_modules()

from gate_checks._helpers import _ok  # noqa: E402
from gate_persistence import build_gate_evidence  # noqa: E402
from gate_runner import format_text, run_gate  # noqa: E402


# ── shared fakes ────────────────────────────────────────────────────────────

def _benign_skip(label="benign"):
    return _ok(label, True, "n/a on this path", skipped=True)


def _degraded_skip(label="degraded"):
    return _ok(label, False, "no simulator", skipped=True, degraded=True)


def _hard_fail(label="hardfail"):
    return _ok(label, False, "really broke")


def _green(label="green"):
    return _ok(label, True, "ok")


def _stub_spec_one_group():
    """Minimal spec with a single gate whose one check is a procedural hook
    we control via monkeypatching GATE_CHECKS."""
    return {
        "gates": {
            "5->6": {
                "fromPhase": "5",
                "toPhase": "6",
                "soft": False,
                "checks": [{"type": "procedural", "name": "_test_hook"}],
            }
        }
    }


# ── Task 1: _ok degraded kwarg ───────────────────────────────────────────────

class TestOkDegradedKwarg(unittest.TestCase):

    def test_plain_ok_has_no_degraded_or_skipped(self):
        r = _ok("c", True, "msg")
        self.assertNotIn("skipped", r)
        self.assertNotIn("degraded", r)
        self.assertTrue(r["passed"])

    def test_benign_skip_sets_skipped_only(self):
        r = _ok("c", True, "n/a", skipped=True)
        self.assertTrue(r["skipped"])
        self.assertNotIn("degraded", r)

    def test_degraded_skip_sets_both_flags(self):
        r = _ok("c", False, "no sim", skipped=True, degraded=True)
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])
        self.assertFalse(r["passed"])

    def test_degraded_without_skip_still_records_flag(self):
        # degraded is independent of skipped on the helper; the rollup decides meaning.
        r = _ok("c", False, "x", degraded=True)
        self.assertTrue(r["degraded"])
        self.assertNotIn("skipped", r)


class TestRunGateRollup(unittest.TestCase):
    """run_gate must distinguish benign-skip (green), degraded-skip (degraded),
    and hard-fail (red). Drives a single procedural group via a monkeypatched
    GATE_CHECKS entry so we control the exact sub_checks."""

    def setUp(self):
        import gate_runner
        self.gate_runner = gate_runner
        self._orig = dict(gate_runner.GATE_CHECKS)

    def tearDown(self):
        self.gate_runner.GATE_CHECKS.clear()
        self.gate_runner.GATE_CHECKS.update(self._orig)

    def _run_with_subs(self, subs):
        from pathlib import Path
        self.gate_runner.GATE_CHECKS["_test_hook"] = lambda pd, app, st: subs
        return run_gate("5->6", Path("/tmp"), "TestApp", {}, _stub_spec_one_group())

    def test_all_green_is_passed_not_degraded(self):
        r = self._run_with_subs([_green(), _benign_skip()])
        self.assertTrue(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertTrue(r["checks"][0]["passed"])
        self.assertFalse(r["checks"][0]["degraded"])

    def test_benign_skip_alone_stays_green(self):
        # backend_required N/A skip must NOT lower the gate.
        r = self._run_with_subs([_benign_skip()])
        self.assertTrue(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertFalse(r["checks"][0]["degraded"])

    def test_degraded_skip_keeps_passed_true_but_marks_degraded(self):
        r = self._run_with_subs([_green(), _degraded_skip()])
        self.assertTrue(r["passed"], "degraded must keep passed=True so mvp advances")
        self.assertTrue(r["degraded"])
        self.assertTrue(r["checks"][0]["degraded"])
        self.assertFalse(r["checks"][0]["passed"], "a degraded group is not green")

    def test_hard_fail_makes_gate_fail_not_degraded(self):
        r = self._run_with_subs([_green(), _hard_fail()])
        self.assertFalse(r["passed"])
        self.assertFalse(r["degraded"], "a failed gate is red, not degraded")
        self.assertFalse(r["checks"][0]["passed"])

    def test_hard_fail_dominates_degraded(self):
        # When a group has both a degraded skip and a real failure, it is a hard fail.
        r = self._run_with_subs([_degraded_skip(), _hard_fail()])
        self.assertFalse(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertFalse(r["checks"][0]["degraded"], "hard_fail group is red, degraded suppressed")

    def test_top_level_has_degraded_key_always(self):
        r = self._run_with_subs([_green()])
        self.assertIn("degraded", r)
        self.assertIn("degraded", r["checks"][0])


# ── Task 3: format_text DEGRADED marker (filled in Task 3) ───────────────────


# ── Task 4: build_gate_evidence status minting (filled in Task 4) ────────────


# ── Task 5: phase advances on degraded (filled in Task 5, IsolatedProjectCase)


if __name__ == "__main__":
    unittest.main()
