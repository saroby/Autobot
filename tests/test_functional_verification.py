"""Anti-laundering: shipping must re-require a fresh functional PASS.

check_functional_verification_passed reads state.gates['5->6'].status and
HARD-FAILS (not a benign skip) when it is anything other than 'passed' —
including 'degraded'. A degraded 5->6 (functional flows unverified because no
simulator / axe / xcodebuild) must never be allowed to ship.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.functional import check_functional_verification_passed  # noqa: E402


def _state(status):
    if status is None:
        return {"gates": {}}
    return {"gates": {"5->6": {"status": status}}}


class TestFunctionalVerificationPassed(unittest.TestCase):
    def _result(self, status):
        results = check_functional_verification_passed(Path("/tmp"), "App", _state(status))
        self.assertEqual(len(results), 1, msg=f"expected exactly one sub-check, got {results}")
        return results[0]

    def test_passed_status_is_green(self):
        r = self._result("passed")
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_degraded_status_is_hard_fail(self):
        r = self._result("degraded")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False), msg="degraded must be a HARD fail, never a benign skip")
        self.assertIn("degraded", r["message"].lower())

    def test_soft_failed_status_is_hard_fail(self):
        r = self._result("soft_failed")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_failed_status_is_hard_fail(self):
        r = self._result("failed")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_missing_gate_is_hard_fail(self):
        r = self._result(None)
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertIn("missing", r["message"].lower())

    def test_registered_in_gate_checks(self):
        from gate_runner import GATE_CHECKS
        self.assertIs(GATE_CHECKS.get("functional_verification_passed"),
                      check_functional_verification_passed)


class TestSpecWiring(unittest.TestCase):
    def test_gate_6to7_lists_functional_verification_passed_first(self):
        import json
        from pathlib import Path as _P
        spec_path = _P(__file__).resolve().parent.parent / "spec" / "pipeline.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        checks = spec["gates"]["6->7"]["checks"]
        names = [c.get("name") for c in checks if isinstance(c, dict)]
        self.assertIn("functional_verification_passed", names,
                      msg="gate 6->7 must record the functional verification verdict")
        self.assertEqual(names[0], "functional_verification_passed",
                         msg="functional_verification_passed must be the FIRST check in 6->7")


if __name__ == "__main__":
    unittest.main()
