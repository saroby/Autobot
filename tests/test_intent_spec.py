"""Tests for scripts/intent_spec.py — the bridge between architect's
promised UI and Phase 5 anchor verification.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from intent_spec import (  # noqa: E402
    Acceptance,
    AppIntent,
    DEFAULT_REQUIRED_ANCHORS,
    FeatureSpec,
    POSTCONDITION_KINDS,
    Postcondition,
    assess_feature_spec_quality,
    find_unused_anchors,
    load_app_intent,
    load_feature_spec,
    validate_feature_spec,
    validate_manifest,
)


def _write_intent(project_root: Path, payload: dict) -> None:
    (project_root / ".autobot").mkdir(parents=True, exist_ok=True)
    (project_root / ".autobot" / "app-intent.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class TestLoadAppIntent(unittest.TestCase):
    def test_returns_none_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_app_intent(Path(tmp)))

    def test_returns_none_when_file_unparseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autobot").mkdir()
            (Path(tmp) / ".autobot" / "app-intent.json").write_text("not json")
            self.assertIsNone(load_app_intent(Path(tmp)))

    def test_defaults_required_anchors_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_intent(Path(tmp), {
                "appName": "X", "promise": "p",
                "primaryScreenTitle": "Home", "primaryCTA": "Go",
            })
            intent = load_app_intent(Path(tmp))
            assert intent is not None
            self.assertEqual(intent.required_anchors, DEFAULT_REQUIRED_ANCHORS)

    def test_preserves_custom_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_intent(Path(tmp), {
                "appName": "X", "promise": "p",
                "primaryScreenTitle": "Home", "primaryCTA": "Go",
                "requiredAnchors": ["autobot.root", "autobot.primaryList"],
            })
            intent = load_app_intent(Path(tmp))
            assert intent is not None
            self.assertEqual(intent.required_anchors, ("autobot.root", "autobot.primaryList"))


class TestValidateManifest(unittest.TestCase):
    def test_complete_manifest_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_intent(Path(tmp), {
                "appName": "Demo", "promise": "Track workouts.",
                "primaryScreenTitle": "Today", "primaryCTA": "Log",
            })
            ok, problems = validate_manifest(Path(tmp))
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])

    def test_missing_promise_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_intent(Path(tmp), {
                "appName": "Demo", "primaryScreenTitle": "T", "primaryCTA": "G",
            })
            ok, problems = validate_manifest(Path(tmp))
            self.assertFalse(ok)
            self.assertTrue(any("promise" in p for p in problems))

    def test_missing_file_returns_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, problems = validate_manifest(Path(tmp))
            self.assertFalse(ok)
            self.assertIn("app-intent.json absent or unparseable", problems)


class TestFindUnusedAnchors(unittest.TestCase):
    def _setup_app(self, tmp: Path, *, anchors_in_views: list[str]) -> None:
        _write_intent(tmp, {
            "appName": "Demo", "promise": "p",
            "primaryScreenTitle": "Home", "primaryCTA": "Go",
        })
        views_dir = tmp / "Demo" / "Views"
        views_dir.mkdir(parents=True)
        body = "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\")"
        for anchor in anchors_in_views:
            body += f".accessibilityIdentifier(\"{anchor}\")"
        body += " } }"
        (views_dir / "V.swift").write_text(body)

    def test_all_anchors_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_app(tmp_path, anchors_in_views=list(DEFAULT_REQUIRED_ANCHORS))
            missing, present = find_unused_anchors(tmp_path, "Demo")
            self.assertEqual(missing, [])
            self.assertEqual(set(present), set(DEFAULT_REQUIRED_ANCHORS))

    def test_missing_one_anchor_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._setup_app(tmp_path, anchors_in_views=["autobot.root", "autobot.primaryTitle"])
            missing, present = find_unused_anchors(tmp_path, "Demo")
            self.assertEqual(missing, ["autobot.primaryCTA"])
            self.assertEqual(set(present), {"autobot.root", "autobot.primaryTitle"})

    def test_no_app_root_treats_all_anchors_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_intent(tmp_path, {
                "appName": "Demo", "promise": "p",
                "primaryScreenTitle": "Home", "primaryCTA": "Go",
            })
            # No Demo/ directory at all
            missing, present = find_unused_anchors(tmp_path, "Demo")
            self.assertEqual(set(missing), set(DEFAULT_REQUIRED_ANCHORS))
            self.assertEqual(present, [])

    def test_missing_intent_returns_empty(self):
        # When the manifest is absent, the caller treats it as "skip" not "fail"
        with tempfile.TemporaryDirectory() as tmp:
            missing, present = find_unused_anchors(Path(tmp), "Demo")
            self.assertEqual(missing, [])
            self.assertEqual(present, [])


def _write_feature_spec(project_root: Path, payload: dict) -> None:
    (project_root / ".autobot").mkdir(parents=True, exist_ok=True)
    (project_root / ".autobot" / "feature-spec.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _valid_feature_payload() -> dict:
    """A structurally + quality-valid spec: one P0 flow feature with a real
    postcondition, plus a P2 feature we don't strictly police."""
    return {
        "version": 1,
        "features": [
            {
                "id": "log-workout",
                "title": "Log a workout",
                "priority": "P0",
                "screen": "Today",
                "anchor": "autobot.primaryCTA",
                "acceptance": [
                    {
                        "id": "tap-log-increments-count",
                        "kind": "flow",
                        "steps": [{"action": "tap", "anchor": "autobot.primaryCTA"}],
                        "postcondition": {
                            "kind": "count_increased",
                            "params": {"anchor": "autobot.workoutCount"},
                        },
                    }
                ],
            },
            {
                "id": "about-screen",
                "title": "About",
                "priority": "P2",
                "screen": "Settings",
                "anchor": "autobot.aboutRow",
                "acceptance": [],
            },
        ],
    }


class TestLoadFeatureSpec(unittest.TestCase):
    def test_returns_none_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_feature_spec(Path(tmp)))

    def test_returns_none_when_unparseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autobot").mkdir()
            (Path(tmp) / ".autobot" / "feature-spec.json").write_text("not json")
            self.assertIsNone(load_feature_spec(Path(tmp)))

    def test_valid_spec_parses_into_dataclasses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            features = load_feature_spec(tmp_path)
            assert features is not None
            self.assertEqual(len(features), 2)
            first = features[0]
            self.assertIsInstance(first, FeatureSpec)
            self.assertEqual(first.id, "log-workout")
            self.assertEqual(first.priority, "P0")
            self.assertEqual(first.screen, "Today")
            self.assertEqual(first.anchor, "autobot.primaryCTA")
            self.assertEqual(len(first.acceptance), 1)
            acc = first.acceptance[0]
            self.assertIsInstance(acc, Acceptance)
            self.assertEqual(acc.kind, "flow")
            self.assertEqual(acc.steps, ({"action": "tap", "anchor": "autobot.primaryCTA"},))
            self.assertIsInstance(acc.postcondition, Postcondition)
            self.assertEqual(acc.postcondition.kind, "count_increased")
            self.assertEqual(acc.postcondition.params, {"anchor": "autobot.workoutCount"})

    def test_tolerates_missing_and_extra_fields(self):
        # A feature missing optional bits + carrying junk keys must still parse,
        # with safe defaults (empty acceptance tuple, empty params dict).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, {
                "features": [
                    {
                        "id": "f1",
                        "title": "F1",
                        "priority": "P1",
                        "screen": "Home",
                        "anchor": "autobot.root",
                        "junkKey": 123,
                        "acceptance": [
                            {
                                "id": "a1",
                                "kind": "logic",
                                # no "steps", no "params", extra noise field
                                "postcondition": {"kind": "setting_stored", "noise": True},
                                "alsoJunk": "x",
                            }
                        ],
                    }
                ]
            })
            features = load_feature_spec(tmp_path)
            assert features is not None
            self.assertEqual(features[0].acceptance[0].steps, ())
            self.assertEqual(features[0].acceptance[0].postcondition.params, {})
            self.assertEqual(features[0].acceptance[0].postcondition.kind, "setting_stored")

    def test_non_dict_root_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autobot").mkdir()
            (Path(tmp) / ".autobot" / "feature-spec.json").write_text("[1, 2, 3]")
            self.assertIsNone(load_feature_spec(Path(tmp)))


class TestValidateFeatureSpec(unittest.TestCase):
    def test_valid_spec_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = validate_feature_spec(tmp_path)
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])

    def test_absent_file_fails_with_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, problems = validate_feature_spec(Path(tmp))
            self.assertFalse(ok)
            self.assertTrue(any("feature-spec.json" in p for p in problems))

    def test_p0_with_no_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"] = []  # P0 with zero acceptance
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p and "acceptance" in p for p in problems))

    def test_p1_with_empty_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["priority"] = "P1"
            payload["features"][0]["anchor"] = ""  # empty anchor on a P1 feature
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p and "anchor" in p for p in problems))

    def test_p2_feature_with_no_acceptance_is_allowed(self):
        # Only P0/P1 are policed structurally; the P2 in the payload has [].
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = validate_feature_spec(tmp_path)
            self.assertTrue(ok, problems)


class TestAssessFeatureSpecQuality(unittest.TestCase):
    def test_valid_postcondition_kind_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])

    def test_anchor_only_acceptance_rejected(self):
        # Acceptance with no real postcondition (empty kind) = "anchor-only",
        # which assess_feature_spec_quality must reject for P0/P1.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"][0]["postcondition"] = {"kind": ""}
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p for p in problems))

    def test_bad_postcondition_kind_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"][0]["postcondition"]["kind"] = "made_up_kind"
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("made_up_kind" in p for p in problems))

    def test_absent_file_fails_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, problems = assess_feature_spec_quality(Path(tmp))
            self.assertFalse(ok)
            self.assertTrue(any("feature-spec.json" in p for p in problems))

    def test_all_kinds_recognized(self):
        # Sanity: each declared kind is accepted on a P0 acceptance.
        for kind in POSTCONDITION_KINDS:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                payload = _valid_feature_payload()
                payload["features"][0]["acceptance"][0]["postcondition"]["kind"] = kind
                _write_feature_spec(tmp_path, payload)
                ok, problems = assess_feature_spec_quality(tmp_path)
                self.assertTrue(ok, f"{kind}: {problems}")

    def test_p0_with_flow_acceptance_passes(self):
        # The default valid payload's P0 already has a flow acceptance.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok, problems)

    def test_p0_logic_only_acceptance_rejected(self):
        # A P0 feature whose only acceptance is logic-kind (with a perfectly
        # valid postcondition) must STILL be rejected: Gate 5->6 only drives
        # `flow` acceptances on a simulator, so a logic-only P0 would earn the
        # VERIFIED badge with no UI flow ever run (the broken-UI / intact-logic
        # hole). assess_feature_spec_quality must demand >=1 flow per P0.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"] = [{
                "id": "log-workout.logic",
                "kind": "logic",
                "steps": [{"action": "noop"}],
                "postcondition": {"kind": "value_persisted_after_relaunch", "params": {}},
            }]
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(
                any("flow" in p and "log-workout" in p for p in problems),
                problems,
            )

    def test_p1_logic_only_is_allowed(self):
        # P1 flow failures only warn, so a P1 need not declare a flow acceptance.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["priority"] = "P1"
            payload["features"][0]["acceptance"] = [{
                "id": "log-workout.logic",
                "kind": "logic",
                "steps": [{"action": "noop"}],
                "postcondition": {"kind": "setting_stored", "params": {}},
            }]
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
