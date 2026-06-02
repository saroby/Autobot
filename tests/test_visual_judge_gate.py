"""Gate 5→6 check_visual_judge — design-fidelity verdict → gate mapping.

The vision judge (an agent, Phase 5 Step 9) records its verdict to
phases.5.metadata.visualJudge; this deterministic gate check only reads it.
These tests exercise the verdict→gate matrix directly (no simulator / no LLM).

The anti-laundering branch depends on whether a runtime screenshot exists on
disk, so each test runs in a tmp project dir and opts a screenshot in/out.

Policy under test (DEGRADED-only, never a hard fail):
  allowVisualDrift == buildId       → pass (release-scoped waiver for THIS build)
  verdict=pass                      → pass
  verdict=fail                      → DEGRADED (skipped+degraded)
  no/garbled verdict + screenshot   → DEGRADED (anti-laundering)
  no/garbled verdict + no shot      → benign skip (not verifiable here)
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import check_visual_judge  # noqa: E402

BUILD_ID = "b-test"


def _state(visual_judge=None, allow_drift=None) -> dict:
    meta = {}
    if visual_judge is not None:
        meta["visualJudge"] = visual_judge
    state: dict = {"buildId": BUILD_ID, "phases": {"5": {"metadata": meta}}}
    if allow_drift is not None:
        # waiver is buildId-scoped: True means "waive THIS build" → bind to buildId.
        # Any other value (e.g. a stale build id) is left as-is so tests can assert
        # the waiver does NOT apply to a different build.
        state["allowVisualDrift"] = BUILD_ID if allow_drift is True else allow_drift
    return state


class TestCheckVisualJudge(unittest.TestCase):
    APP = "TestApp"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _add_screenshot(self):
        shot = self.proj / "artifacts" / BUILD_ID / "phase-5" / "runtime-smoke" / "screenshot.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2048)

    def _run(self, state: dict) -> dict:
        results = check_visual_judge(self.proj, self.APP, state)
        self.assertEqual(len(results), 1, "check returns exactly one sub-check")
        return results[0]

    # ── pass ──

    def test_pass_verdict_is_green(self):
        r = self._run(_state(visual_judge={"verdict": "pass", "summary": "matches design"}))
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertFalse(r.get("degraded", False))
        self.assertIn("matches design", r["message"])

    def test_pass_verdict_case_insensitive(self):
        r = self._run(_state(visual_judge={"verdict": "PASS"}))
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))

    # ── fail → DEGRADED (never hard fail) ──

    def test_fail_verdict_degrades_not_hard_fail(self):
        r = self._run(_state(visual_judge={
            "verdict": "fail", "highCount": 2,
            "summary": "system-blue list, design called for coral",
        }))
        # DEGRADED idiom: passed=False BUT skipped=True so the rollup does NOT
        # count it as a hard fail; degraded=True drives badge → DEGRADED.
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))
        self.assertIn("2 high-severity", r["message"])

    def test_fail_verdict_is_not_a_hard_fail_in_rollup(self):
        # Mirror gate_runner rollup: hard_fail = (not passed) AND (not skipped).
        r = self._run(_state(visual_judge={"verdict": "fail", "summary": "x"}))
        hard_fail = (not r["passed"]) and (not r.get("skipped", False))
        degraded = r.get("skipped", False) and r.get("degraded", False)
        self.assertFalse(hard_fail, "visual_judge must never hard-fail the gate")
        self.assertTrue(degraded, "fail verdict must degrade the gate")

    # ── anti-laundering: no/garbled verdict gated on screenshot presence ──

    def test_absent_verdict_without_screenshot_skips_green(self):
        # No simulator → no screenshot → fidelity not verifiable → benign skip.
        r = self._run(_state(visual_judge=None))
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_absent_verdict_with_screenshot_degrades(self):
        # Screenshot exists (sim ran) but Step 9 recorded nothing → would launder
        # to VERIFIED → refuse: DEGRADED.
        self._add_screenshot()
        r = self._run(_state(visual_judge=None))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))
        self.assertIn("screenshot exists", r["message"])

    def test_empty_verdict_with_screenshot_degrades(self):
        self._add_screenshot()
        r = self._run(_state(visual_judge={"verdict": ""}))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))

    def test_garbled_verdict_with_screenshot_degrades(self):
        self._add_screenshot()
        r = self._run(_state(visual_judge={"verdict": "maybe?"}))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))
        self.assertIn("unrecognized", r["message"])

    def test_garbled_verdict_without_screenshot_skips_green(self):
        r = self._run(_state(visual_judge={"verdict": "maybe?"}))
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_fallback_screenshot_path_also_counts(self):
        # The .autobot/ fallback path must also satisfy "screenshot exists".
        shot = self.proj / ".autobot" / "phase-5" / "runtime-smoke" / "screenshot.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(b"\x89PNG" + b"0" * 2048)
        r = self._run(_state(visual_judge=None))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))

    # ── override waives gating entirely ──

    def test_allow_visual_drift_waives_fail(self):
        self._add_screenshot()
        r = self._run(_state(
            visual_judge={"verdict": "fail", "highCount": 1, "summary": "drifted"},
            allow_drift=True,
        ))
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))
        self.assertIn("waived", r["message"])

    def test_allow_visual_drift_waives_absent_verdict_with_screenshot(self):
        # Operator opted out of visual gating: even the anti-laundering DEGRADED
        # is waived.
        self._add_screenshot()
        r = self._run(_state(visual_judge=None, allow_drift=True))
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))

    def test_allow_drift_false_still_degrades_fail(self):
        r = self._run(_state(visual_judge={"verdict": "fail", "summary": "drifted"}, allow_drift=False))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))

    def test_allow_drift_stale_buildid_does_not_waive(self):
        # Waiver bound to a DIFFERENT build id → release-scoped expiry: it must NOT
        # launder this build. A stale waiver from a prior build degrades like an
        # unwaived fail (this is the whole point of buildId-scoping vs persistent).
        self._add_screenshot()
        r = self._run(_state(
            visual_judge={"verdict": "fail", "summary": "drifted"},
            allow_drift="some-other-build",
        ))
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))


if __name__ == "__main__":
    unittest.main()
