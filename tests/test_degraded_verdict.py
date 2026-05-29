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


class TestFormatTextDegraded(unittest.TestCase):

    def _gate(self, *, passed, degraded, soft=False, group_degraded=False):
        return {
            "gate": "5->6",
            "passed": passed,
            "degraded": degraded,
            "soft": soft,
            "checks": [{
                "check": "functional_flows_pass",
                "passed": passed and not group_degraded,
                "degraded": group_degraded,
                "sub_checks": [
                    _ok("flow", not group_degraded, "x",
                        skipped=group_degraded, degraded=group_degraded),
                ],
            }],
        }

    def test_pass_header_when_clean(self):
        txt = format_text(self._gate(passed=True, degraded=False))
        self.assertIn("Gate 5->6: PASS", txt)
        self.assertNotIn("DEGRADED", txt)

    def test_degraded_header_and_group_marker(self):
        txt = format_text(self._gate(passed=True, degraded=True, group_degraded=True))
        self.assertIn("Gate 5->6: DEGRADED", txt)
        # the degraded group renders a DEGRADED marker, not PASS/FAIL
        self.assertIn("[DEGRADED] functional_flows_pass", txt)

    def test_fail_header_unchanged(self):
        txt = format_text(self._gate(passed=False, degraded=False))
        self.assertIn("Gate 5->6: FAIL", txt)

    def test_soft_fail_still_renders(self):
        txt = format_text(self._gate(passed=False, degraded=False, soft=True))
        self.assertIn("Gate 5->6: SOFT FAIL", txt)

    def test_degraded_sub_check_icon(self):
        txt = format_text(self._gate(passed=True, degraded=True, group_degraded=True))
        # degraded skip uses the degraded icon, distinct from benign skip ⊘
        self.assertIn("⚠", txt)


class TestBuildGateEvidenceStatus(unittest.TestCase):
    """All four statuses must round-trip from gate_result → evidence.status."""

    SPEC = {
        "gates": {
            "5->6": {"fromPhase": "5", "toPhase": "6"},
            "6->7": {"fromPhase": "6", "toPhase": "7"},
        }
    }

    def _evidence(self, gate_result, gate_id="5->6"):
        return build_gate_evidence(self.SPEC, gate_id, gate_result, "2026-05-29T00:00:00Z")

    def test_passed(self):
        gr = {"gate": "5->6", "passed": True, "degraded": False, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "passed")

    def test_degraded(self):
        gr = {"gate": "5->6", "passed": True, "degraded": True, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "degraded")

    def test_failed(self):
        gr = {"gate": "5->6", "passed": False, "degraded": False, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "failed")

    def test_soft_failed(self):
        gr = {"gate": "6->7", "passed": False, "degraded": False, "soft": True, "checks": []}
        self.assertEqual(self._evidence(gr, gate_id="6->7")["status"], "soft_failed")

    def test_degraded_only_applies_when_passed(self):
        # a failed gate that somehow also flagged degraded is still failed (hard wins).
        gr = {"gate": "5->6", "passed": False, "degraded": True, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "failed")

    def test_soft_passed_with_degraded_is_degraded(self):
        # soft gate that passed-with-degradation records degraded, not passed.
        gr = {"gate": "6->7", "passed": True, "degraded": True, "soft": True, "checks": []}
        self.assertEqual(self._evidence(gr, gate_id="6->7")["status"], "degraded")


# ── Task 5: phase advances on degraded (filled in Task 5, IsolatedProjectCase)


if __name__ == "__main__":
    unittest.main()
