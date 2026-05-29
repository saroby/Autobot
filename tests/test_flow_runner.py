"""Tests for scripts/flow_runner.py — the AXe-driven functional flow runner.

We never touch a real simulator or the axe binary here: `_run` and
`shutil.which` are monkeypatched, and describe-ui responses are fed from
FIXTURE JSON arrays so the postcondition evaluation logic is exercised
deterministically.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import flow_runner  # noqa: E402
from intent_spec import Acceptance, FeatureSpec, Postcondition  # noqa: E402


SCREEN = {"x": 0, "y": 0, "width": 393, "height": 852}


def _el(identifier, *, label="", enabled=True, x=20, y=100, w=200, h=44, typ="Button"):
    return {
        "type": typ,
        "identifier": identifier,
        "label": label,
        "enabled": enabled,
        "frame": {"x": x, "y": y, "width": w, "height": h},
    }


class TestAnchorReady(unittest.TestCase):
    def test_present_enabled_in_bounds_is_ready(self):
        els = [_el("autobot.primaryCTA")]
        self.assertTrue(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_absent_is_not_ready(self):
        els = [_el("autobot.other")]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_disabled_is_not_ready(self):
        els = [_el("autobot.primaryCTA", enabled=False)]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_offscreen_frame_is_not_ready(self):
        els = [_el("autobot.primaryCTA", x=5000, y=9000)]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))


class TestEvaluatePostcondition(unittest.TestCase):
    def test_count_increased_pass(self):
        before = [_el("autobot.row", typ="Cell"), _el("autobot.row", typ="Cell")]
        after = before + [_el("autobot.row", typ="Cell")]
        ok, _ = flow_runner._evaluate_postcondition(
            "count_increased", {"anchor": "autobot.row"}, before, after
        )
        self.assertTrue(ok)

    def test_count_increased_fail_when_unchanged(self):
        before = [_el("autobot.row", typ="Cell")]
        after = [_el("autobot.row", typ="Cell")]
        ok, _ = flow_runner._evaluate_postcondition(
            "count_increased", {"anchor": "autobot.row"}, before, after
        )
        self.assertFalse(ok)

    def test_navigated_to_pass(self):
        before = [_el("autobot.home")]
        after = [_el("autobot.detail")]
        ok, _ = flow_runner._evaluate_postcondition(
            "navigated_to", {"anchor": "autobot.detail"}, before, after
        )
        self.assertTrue(ok)

    def test_navigated_to_fail_when_target_absent(self):
        before = [_el("autobot.home")]
        after = [_el("autobot.home")]
        ok, _ = flow_runner._evaluate_postcondition(
            "navigated_to", {"anchor": "autobot.detail"}, before, after
        )
        self.assertFalse(ok)


def _feature(priority="P0", post_kind="navigated_to", post_anchor="autobot.detail"):
    acc = Acceptance(
        id="acc1",
        kind="flow",
        steps=({"action": "tap", "anchor": "autobot.primaryCTA"},),
        postcondition=Postcondition(kind=post_kind, params={"anchor": post_anchor}),
    )
    return FeatureSpec(
        id="feat1",
        title="Open detail",
        priority=priority,
        screen="Home",
        anchor="autobot.primaryCTA",
        acceptance=(acc,),
    )


class TestRunFlowsDegradedPaths(unittest.TestCase):
    def test_axe_missing_is_skipped_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value=None):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature()])
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["skipReason"], "axe_unavailable")

    def test_sim_missing_is_skipped_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=(None, "no_ios_simulator_available")):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature()])
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["skipReason"], "no_ios_simulator_available")

    def test_empty_features_is_skipped_not_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = flow_runner.run_flows(Path(tmp), "Demo", [])
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result.get("degraded", False))
        self.assertEqual(result["skipReason"], "no_features")


class TestRunFlowsHappyAndFail(unittest.TestCase):
    """Drive a full flow with describe-ui responses injected via a fake _run."""

    def _make_axe_driver(self, *, describe_sequence):
        """Return a fake _run that returns queued describe-ui payloads in order;
        `axe tap` and `simctl`/`boot`/`install`/`launch` all succeed silently."""
        seq = list(describe_sequence)

        def fake_run(cmd, *, timeout=flow_runner.DEFAULT_AXE_TIMEOUT):
            if "describe-ui" in cmd:
                payload = seq.pop(0) if seq else []
                return 0, json.dumps(payload), ""
            return 0, "", ""

        return fake_run

    def test_p0_flow_pass(self):
        cta = _el("autobot.primaryCTA")
        # describe-ui calls in order: wait-for-anchor, before-postcondition,
        # after-postcondition (target now visible).
        seq = [
            [cta],                       # _wait_for_anchor poll #1: ready
            [cta],                       # before snapshot
            [_el("autobot.detail")],     # after snapshot: navigated
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_relaunch", return_value=None), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P0")])
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len(result["results"]), 1)
        self.assertTrue(result["results"][0]["passed"])

    def test_p0_flow_fail_is_hard(self):
        cta = _el("autobot.primaryCTA")
        seq = [
            [cta],                       # wait: ready
            [cta],                       # before
            [cta],                       # after: NOT navigated (target absent)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_relaunch", return_value=None), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P0")])
        self.assertEqual(result["status"], "failed", result)
        self.assertFalse(result["results"][0]["passed"])

    def test_p1_flow_fail_is_warning_not_failed(self):
        cta = _el("autobot.primaryCTA")
        seq = [[cta], [cta], [cta]]  # after: not navigated
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_relaunch", return_value=None), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P1")])
        # P1 failure does NOT fail the suite (status passed), but the per-result
        # row records passed=False with a warning note.
        self.assertEqual(result["status"], "passed", result)
        self.assertFalse(result["results"][0]["passed"])
        self.assertIn("warning", result["results"][0]["message"].lower())


if __name__ == "__main__":
    unittest.main()
