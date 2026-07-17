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
    # Mirror the REAL AXe 1.7.0 describe-ui schema: the accessibility identifier
    # is carried in "AXUniqueId" (NOT "identifier"), alongside AXLabel/frame/enabled.
    return {
        "type": typ,
        "AXUniqueId": identifier,
        "AXLabel": label,
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

    def test_legacy_identifier_key_still_matches(self):
        # back-compat: an element using the legacy "identifier" key (no AXUniqueId)
        # must still match, so flow_runner tolerates both real AXe + older shapes.
        el = {"type": "Button", "identifier": "autobot.primaryCTA",
              "enabled": True, "frame": {"x": 20, "y": 100, "width": 200, "height": 44}}
        self.assertTrue(flow_runner._anchor_ready([el], "autobot.primaryCTA", SCREEN))

    def test_axuniqueid_is_the_real_key(self):
        # real AXe carries the identifier in AXUniqueId; matching must key off it.
        el = {"type": "Button", "AXUniqueId": "autobot.primaryCTA",
              "enabled": True, "frame": {"x": 20, "y": 100, "width": 200, "height": 44}}
        self.assertTrue(flow_runner._anchor_ready([el], "autobot.primaryCTA", SCREEN))


class TestFlatten(unittest.TestCase):
    """AXe describe-ui returns a nested tree (root + children); the matchers
    need every node. _flatten must surface deeply-nested anchors."""

    def _nested(self):
        return [{
            "type": "Application", "AXUniqueId": "root", "children": [
                {"type": "Group", "children": [
                    {"type": "Button", "AXUniqueId": "autobot.add", "enabled": True,
                     "frame": {"x": 20, "y": 80, "width": 100, "height": 44}},
                ]},
            ],
        }]

    def test_flattens_nested_tree_so_anchor_is_found(self):
        flat = flow_runner._flatten(self._nested())
        self.assertTrue(any(flow_runner._anchor_id(e) == "autobot.add" for e in flat))
        self.assertTrue(flow_runner._anchor_ready(flat, "autobot.add", SCREEN))

    def test_single_root_dict_flattens(self):
        root = self._nested()[0]
        flat = flow_runner._flatten(root)
        self.assertTrue(flow_runner._present(flat, "autobot.add"))


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

    def test_navigated_to_fail_when_target_preexisting(self):
        # A static stub (or tab-bar root) that showed the anchor BEFORE the tap
        # proves nothing about navigation — novelty is required.
        before = [_el("autobot.home"), _el("autobot.detail")]
        after = [_el("autobot.home"), _el("autobot.detail")]
        ok, msg = flow_runner._evaluate_postcondition(
            "navigated_to", {"anchor": "autobot.detail"}, before, after
        )
        self.assertFalse(ok, msg)

    def test_navigated_to_allow_preexisting_opt_out(self):
        # Legitimate always-visible destinations (tab-bar roots) opt out via
        # params.allow_preexisting — presence-only check.
        before = [_el("autobot.detail")]
        after = [_el("autobot.detail")]
        ok, msg = flow_runner._evaluate_postcondition(
            "navigated_to",
            {"anchor": "autobot.detail", "allow_preexisting": True},
            before, after,
        )
        self.assertTrue(ok)
        # #4a: the bypass must be named in the result message for audit.
        self.assertIn("allow_preexisting", msg)

    def test_setting_stored_requires_value_change(self):
        before = [_el("autobot.toggle", label="Off")]
        unchanged = [_el("autobot.toggle", label="Off")]
        changed = [_el("autobot.toggle", label="On")]
        ok, msg = flow_runner._evaluate_postcondition(
            "setting_stored", {"anchor": "autobot.toggle"}, before, unchanged
        )
        self.assertFalse(ok, msg)
        ok, _ = flow_runner._evaluate_postcondition(
            "setting_stored", {"anchor": "autobot.toggle"}, before, changed
        )
        self.assertTrue(ok)

    def test_artifact_generated_requires_new_or_changed_anchor(self):
        before = [_el("autobot.home")]
        generated = [_el("autobot.home"), _el("autobot.artifact")]
        ok, _ = flow_runner._evaluate_postcondition(
            "artifact_generated", {"anchor": "autobot.artifact"}, before, generated
        )
        self.assertTrue(ok)
        # Same static anchor before and after = nothing was generated.
        static = [_el("autobot.artifact", label="stub")]
        ok, msg = flow_runner._evaluate_postcondition(
            "artifact_generated", {"anchor": "autobot.artifact"}, static, static
        )
        self.assertFalse(ok, msg)

    def test_unknown_kind_fails(self):
        # The old lenient fallback let any unknown/empty kind pass on anchor
        # presence — stub screens sailed through. Unknown = spec bug = fail.
        els = [_el("autobot.home")]
        ok, msg = flow_runner._evaluate_postcondition(
            "made_up_kind", {"anchor": "autobot.home"}, els, els
        )
        self.assertFalse(ok, msg)
        ok, _ = flow_runner._evaluate_postcondition("", {}, els, els)
        self.assertFalse(ok)

    def test_visual_kinds_are_delegated_pass(self):
        # occupies_screen_fraction / matches_visual_reference are asserted by
        # visual_contract / visual_judge — explicit pass-through, not the
        # unknown-kind fail path.
        els = [_el("autobot.root")]
        for kind in ("occupies_screen_fraction", "matches_visual_reference"):
            ok, msg = flow_runner._evaluate_postcondition(kind, {}, els, els)
            self.assertTrue(ok, msg)
            self.assertIn("visual", msg)


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

    def test_navigated_to_novelty_uses_flow_entry_snapshot(self):
        # The destination anchor becomes visible MID-flow (before the final
        # tap's wait snapshot). Novelty must compare against the flow-entry
        # snapshot, not the last per-step wait — otherwise a legitimate
        # navigation reads as "preexisting" and false-fails.
        cta = _el("autobot.primaryCTA")
        detail = _el("autobot.detail", y=300)
        seq = [
            [cta],                # entry wait: detail NOT yet visible
            [cta, detail],        # step wait snapshot: detail already visible
            [cta, detail],        # after snapshot
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
        self.assertTrue(result["results"][0]["passed"])

    def test_p0_flow_fail_when_destination_preexisting(self):
        # detail visible from the very first (entry) snapshot: a stubbed static
        # screen. The flow must FAIL even though the anchor is present after.
        cta = _el("autobot.primaryCTA")
        detail = _el("autobot.detail", y=300)
        seq = [
            [cta, detail],        # entry wait: detail ALREADY visible
            [cta, detail],        # step wait
            [cta, detail],        # after
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

    def test_delta_postcondition_uses_flow_entry_snapshot(self):
        # Multi-step flow whose count change lands at an EARLIER step (step 1),
        # so by the final step's pre-action snapshot the row is already there.
        # A delta postcondition compared against the LAST pre-action snapshot
        # would read "no change" and false-fail P0. Baseline must be the
        # flow-entry snapshot, which measures the flow's net effect.
        cta = _el("autobot.primaryCTA")
        cta2 = _el("autobot.secondCTA")
        row = _el("autobot.row", typ="Cell")
        two_step = FeatureSpec(
            id="feat1", title="Add then confirm", priority="P0",
            screen="Home", anchor="autobot.primaryCTA",
            acceptance=(Acceptance(
                id="acc1", kind="flow",
                steps=(
                    {"action": "tap", "anchor": "autobot.primaryCTA"},
                    {"action": "tap", "anchor": "autobot.secondCTA"},
                ),
                postcondition=Postcondition(
                    kind="count_increased", params={"anchor": "autobot.row"}),
            ),),
        )
        seq = [
            [cta, row],                     # entry wait: 1 row
            [cta, row],                     # step 1 wait: still 1 row (pre-tap)
            [cta2, row, row],               # step 2 wait: step 1 added a row → 2
            [cta2, row, row],               # after: step 2 changed nothing → 2
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_relaunch", return_value=None), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [two_step])
        self.assertEqual(result["status"], "passed", result)
        self.assertTrue(result["results"][0]["passed"], result["results"][0])

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
