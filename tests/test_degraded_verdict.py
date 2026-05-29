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


# ── Task 2: run_gate three-valued rollup (filled in Task 2) ──────────────────


# ── Task 3: format_text DEGRADED marker (filled in Task 3) ───────────────────


# ── Task 4: build_gate_evidence status minting (filled in Task 4) ────────────


# ── Task 5: phase advances on degraded (filled in Task 5, IsolatedProjectCase)


if __name__ == "__main__":
    unittest.main()
