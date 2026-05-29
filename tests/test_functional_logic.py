"""Tests for scripts/gate_checks/functional.py::check_logic_tests_pass.

Drives the parser against synthetic xcresulttool-summary JSON (pass + fail)
and asserts the degraded-skip path when integration_build reports no
xcodebuild / no simulator. No real .xcresult or simulator is touched — the
xcresulttool subprocess and integration_build are both monkeypatched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks import functional as fn  # noqa: E402


# ── Fixture builders mirroring `xcresulttool get test-results summary` ──
def _summary_json(*, result: str, total: int, passed: int, failed: int) -> str:
    return json.dumps({
        "title": "Test",
        "result": result,            # "Passed" | "Failed" | "Skipped"
        "totalTestCount": total,
        "passedTests": passed,
        "failedTests": failed,
        "skippedTests": 0,
        "expectedFailures": 0,
    })


def _tests_json(*test_names: str) -> str:
    """Mirror `get test-results tests`: nested testNodes tree whose leaf
    nodeType == 'Test Case' carries the authored test function name."""
    cases = [
        {"nodeType": "Test Case", "name": n, "result": "Passed"} for n in test_names
    ]
    return json.dumps({
        "testNodes": [
            {"nodeType": "Test Plan", "name": "Plan", "children": [
                {"nodeType": "Unit test bundle", "name": "DemoTests", "children": [
                    {"nodeType": "Test Suite", "name": "LogicTests", "children": cases},
                ]},
            ]},
        ],
    })


class _Patches:
    """Context object collecting monkeypatches; restored in tearDown."""

    def __init__(self) -> None:
        self._orig: list = []

    def set(self, obj, attr, value) -> None:
        self._orig.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def restore(self) -> None:
        for obj, attr, value in reversed(self._orig):
            setattr(obj, attr, value)


class TestCheckLogicTestsPass(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        self.p = _Patches()

    def tearDown(self) -> None:
        self.p.restore()
        self._tmp.cleanup()

    def _patch_build(self, *, status: str, skip_reason: str | None = None) -> Path:
        bundle = self.proj / "Build.xcresult"
        def fake_build(project_root, app_name, *, attempt=1, test=False, destination=None):
            out = {"phase": "5", "status": status}
            if status == "skipped":
                out["skipReason"] = skip_reason or "xcodebuild_unavailable"
            else:
                out["resultBundlePath"] = str(bundle)
                out["exitCode"] = 0 if status == "passed" else 65
            return out
        self.p.set(fn, "integration_build", fake_build)
        return bundle

    def _patch_xcresult(self, summary: str, tests: str | None = None) -> None:
        def fake_run(cmd, *, timeout=120):
            # cmd is the xcresulttool argv built by functional._xcresult_json
            if "summary" in cmd:
                return 0, summary
            if "tests" in cmd:
                return 0, tests if tests is not None else _tests_json()
            return 1, "unexpected"
        self.p.set(fn, "_run_xcresulttool", fake_run)

    # ── degraded skip: no xcodebuild ──
    def test_no_xcodebuild_is_degraded_skip(self):
        self._patch_build(status="skipped", skip_reason="xcodebuild_unavailable")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertEqual(primary["check"], "logic_tests_pass")
        self.assertFalse(primary["passed"])
        self.assertTrue(primary.get("skipped"))
        self.assertTrue(primary.get("degraded"))
        self.assertIn("xcodebuild_unavailable", primary["message"])

    def test_no_simulator_is_degraded_skip(self):
        # integration_build maps a missing sim to status="skipped"; we model the
        # xcodeproj_missing/sim skip reasons the same degraded way.
        self._patch_build(status="skipped", skip_reason="xcodeproj_missing")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertTrue(primary.get("skipped"))
        self.assertTrue(primary.get("degraded"))

    # ── pass ──
    def test_passed_xcresult_passes(self):
        self._patch_build(status="passed")
        self._patch_xcresult(_summary_json(result="Passed", total=3, passed=3, failed=0))
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertTrue(primary["passed"])
        self.assertFalse(primary.get("skipped", False))
        self.assertFalse(primary.get("degraded", False))
        self.assertIn("3", primary["message"])

    # ── hard fail: tests failed ──
    def test_failed_xcresult_hard_fails(self):
        self._patch_build(status="passed")  # xcodebuild ran; tests inside failed
        self._patch_xcresult(_summary_json(result="Failed", total=3, passed=2, failed=1))
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertFalse(primary["passed"])
        self.assertFalse(primary.get("skipped", False))   # NOT a skip — a real failure
        self.assertFalse(primary.get("degraded", False))  # hard fail, not degraded
        self.assertIn("failed", primary["message"].lower())

    # ── hard fail: integration_build itself reported test command failure ──
    def test_build_failed_status_hard_fails(self):
        self._patch_build(status="failed")
        # summary unparseable / absent → still a hard fail (build/test command failed)
        self._patch_xcresult("not json")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertFalse(primary["passed"])
        self.assertFalse(primary.get("degraded", False))

    # ── completeness sub-check: P0 logic acceptance with NO matching test → WARNING (non-blocking) ──
    def test_missing_p0_test_is_nonblocking_warning(self):
        self._patch_build(status="passed")
        # authored tests do NOT include a test named after acceptance "addItem_increasesCount"
        self._patch_xcresult(
            _summary_json(result="Passed", total=1, passed=1, failed=0),
            _tests_json("appLaunches()"),
        )
        feature = fn._FeatureLite(
            feature_id="F1", priority="P0",
            logic_acceptance_ids=["addItem_increasesCount"],
        )
        results = fn.check_logic_tests_pass(
            self.proj, "Demo", {}, _features_override=[feature],
        )
        primary = results[0]
        completeness = next(r for r in results if r["check"] == "logic_test_completeness")
        # Primary still GREEN (build+tests passed); completeness is a warning, not a fail.
        self.assertTrue(primary["passed"])
        self.assertTrue(completeness["passed"])        # non-blocking
        self.assertFalse(completeness.get("degraded", False))
        self.assertIn("WARNING", completeness["message"])
        self.assertIn("addItem_increasesCount", completeness["message"])

    def test_matching_p0_test_completeness_clean(self):
        self._patch_build(status="passed")
        self._patch_xcresult(
            _summary_json(result="Passed", total=1, passed=1, failed=0),
            _tests_json("addItem_increasesCount()"),
        )
        feature = fn._FeatureLite(
            feature_id="F1", priority="P0",
            logic_acceptance_ids=["addItem_increasesCount"],
        )
        results = fn.check_logic_tests_pass(
            self.proj, "Demo", {}, _features_override=[feature],
        )
        completeness = next(r for r in results if r["check"] == "logic_test_completeness")
        self.assertTrue(completeness["passed"])
        self.assertNotIn("WARNING", completeness["message"])


if __name__ == "__main__":
    unittest.main()
