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
    DEPTH_THRESHOLDS,
    FeatureSpec,
    POSTCONDITION_KINDS,
    Postcondition,
    assess_feature_spec_depth,
    assess_feature_spec_quality,
    find_unused_anchors,
    input_intent_signal,
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

    def test_invalid_priority_enum_rejected(self):
        # A "P3" typo (or any non-enum value) silently bypasses every P0/P1/P2
        # rule downstream — structural validation must reject it.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["priority"] = "P3"
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("invalid priority" in p for p in problems), problems)

    def test_empty_priority_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            del payload["features"][0]["priority"]  # → "" after parsing
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("invalid priority" in p for p in problems), problems)


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
        # The payload keeps its valid P0 feature — a zero-P0 spec is rejected
        # outright by rule 3 (tested separately below).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"].append({
                "id": "export-report",
                "title": "Export report",
                "priority": "P1",
                "screen": "Settings",
                "anchor": "autobot.exportRow",
                "acceptance": [{
                    "id": "export-report.logic",
                    "kind": "logic",
                    "steps": [{"action": "noop"}],
                    "postcondition": {"kind": "setting_stored", "params": {}},
                }],
            })
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok, problems)

    def test_p2_empty_screen_is_depth_problem_not_quality_hardfail(self):
        # P2 grounding moved from feature_spec_quality (hard) to
        # feature_spec_depth (DEGRADED-default): a screen-less P2 is grounding
        # debt, not a Gate 1->2 hard fail (which would pressure the architect to
        # drop P2s entirely — a Goodhart trap).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][1]["screen"] = ""
            _write_feature_spec(tmp_path, payload)
            d = assess_feature_spec_depth(tmp_path)
            self.assertTrue(
                any("about-screen" in p and "screen" in p for p in d["problems"]),
                d["problems"])
            ok, _ = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok)  # no longer a quality hard-fail

    def test_p2_empty_title_is_depth_problem_not_quality_hardfail(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][1]["title"] = ""
            _write_feature_spec(tmp_path, payload)
            d = assess_feature_spec_depth(tmp_path)
            self.assertTrue(any("title" in p for p in d["problems"]), d["problems"])
            ok, _ = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok)

    def test_zero_p0_spec_rejected(self):
        # All-P1/P2 spec: every flow could fail and the suite would still pass
        # (P1 failures only warn) — the zero-P0 VERIFIED-badge laundering hole.
        # Rule 3 demands >=1 P0 feature; the P0 count is deterministic, so this
        # is a safe Gate 1->2 hard fail.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["priority"] = "P1"  # leaves only P1 + P2
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("no P0 feature" in p for p in problems), problems)


def _deep_feature(fid, priority, screen, role, post_kind, steps=1):
    return {
        "id": fid,
        "title": fid.replace("-", " "),
        "priority": priority,
        "screen": screen,
        "anchor": f"autobot.{fid}",
        "role": role,
        "acceptance": [{
            "id": f"{fid}.a1",
            "kind": "flow",
            "steps": [{"action": "tap", "anchor": f"autobot.{fid}"}] * steps,
            "postcondition": {"kind": post_kind, "params": {"anchor": f"autobot.{fid}.out"}},
        }],
    }


def _deep_payload() -> dict:
    """Meets every DEPTH_THRESHOLDS floor: P0+P1=5, P0=2, screens=4, kinds=3,
    hook+retention roles, one multi-step journey."""
    return {"version": 1, "features": [
        _deep_feature("log-entry", "P0", "Home", "hook", "count_increased", steps=2),
        _deep_feature("weekly-stats", "P0", "Stats", "insight", "navigated_to"),
        _deep_feature("history", "P1", "History", "retention", "value_persisted_after_relaunch"),
        _deep_feature("edit-entry", "P1", "Home", "table-stakes", "count_increased"),
        _deep_feature("open-settings", "P1", "Settings", "table-stakes", "navigated_to"),
    ]}


class TestFeatureSpecRoleParsing(unittest.TestCase):
    def test_role_parsed_and_defaults_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["role"] = "hook"
            _write_feature_spec(tmp_path, payload)
            features = load_feature_spec(tmp_path)
            self.assertEqual(features[0].role, "hook")
            self.assertEqual(features[1].role, "")  # absent → legacy default


class TestAssessFeatureSpecDepth(unittest.TestCase):
    def _assess(self, payload, *, quality_max=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, payload)
            return assess_feature_spec_depth(tmp_path, quality_max=quality_max)

    def test_deep_spec_has_no_findings(self):
        d = self._assess(_deep_payload())
        self.assertEqual(d["hard_problems"], [])
        self.assertEqual(d["problems"], [])
        self.assertEqual(d["advisories"], [])
        self.assertEqual(d["metrics"]["p0_p1"], 5)

    def test_shallow_spec_reports_threshold_problems(self):
        # One P0 + one P2, one screen, one kind — every floor is missed. The
        # single P0 has a multi-step acceptance so it is NOT the one-tap
        # degenerate case (that is a separate hard bucket).
        payload = {"version": 1, "features": [
            _deep_feature("log-entry", "P0", "Home", "table-stakes", "count_increased", steps=3),
            {"id": "share", "title": "Share", "priority": "P2", "screen": "Home",
             "anchor": "autobot.share", "acceptance": []},
        ]}
        d = self._assess(payload)
        self.assertEqual(d["hard_problems"], [])
        joined = " ".join(d["problems"])
        self.assertIn(f"< {DEPTH_THRESHOLDS['min_p0_p1_features']}", joined)
        self.assertIn(f"P0 features 1 < {DEPTH_THRESHOLDS['min_p0_features']}", joined)
        self.assertIn("screens", joined)
        self.assertIn("postcondition kinds", joined)

    def test_missing_hook_retention_roles_are_problems(self):
        payload = _deep_payload()
        for f in payload["features"]:
            f["role"] = "table-stakes"  # roles declared, but no hook/retention
        d = self._assess(payload)
        joined = " ".join(d["problems"])
        self.assertIn("hook", joined)
        self.assertIn("retention", joined)

    def test_legacy_spec_without_roles_warns_not_fails(self):
        payload = _deep_payload()
        for f in payload["features"]:
            del f["role"]
        d = self._assess(payload)
        self.assertEqual(d["problems"], [])
        self.assertTrue(any("legacy" in a for a in d["advisories"]), d["advisories"])

    def test_invalid_role_value_is_problem(self):
        payload = _deep_payload()
        payload["features"][0]["role"] = "banana"
        d = self._assess(payload)
        self.assertTrue(any("banana" in p for p in d["problems"]), d["problems"])

    def test_one_tap_degenerate_spec_is_hard(self):
        payload = {"version": 1, "features": [
            _deep_feature("tap-count", "P0", "Home", "hook", "count_increased", steps=1),
        ]}
        d = self._assess(payload)
        self.assertTrue(any("demo" in p for p in d["hard_problems"]), d)

    def test_quality_max_raises_p0_p1_floor(self):
        d = self._assess(_deep_payload(), quality_max=True)  # 5 < 7
        self.assertTrue(
            any(f"< {DEPTH_THRESHOLDS['min_p0_p1_features_quality_max']}" in p
                for p in d["problems"]), d["problems"])

    def test_single_step_flows_only_is_advisory(self):
        payload = _deep_payload()
        for f in payload["features"]:
            f["acceptance"][0]["steps"] = f["acceptance"][0]["steps"][:1]
        d = self._assess(payload)
        self.assertTrue(any("multi-step" in a for a in d["advisories"]), d["advisories"])

    def test_setting_stored_without_persistence_pair_is_advisory(self):
        payload = _deep_payload()
        # replace the persistence feature so setting_stored has no pair
        payload["features"][2]["acceptance"][0]["postcondition"]["kind"] = "setting_stored"
        d = self._assess(payload)
        self.assertTrue(
            any("value_persisted_after_relaunch" in a for a in d["advisories"]),
            d["advisories"])

    def test_input_intent_idea_without_text_input_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".autobot").mkdir(parents=True)
            (tmp_path / ".autobot" / "build-state.json").write_text(
                json.dumps({"idea": "A quick notes app to search my memos"}),
                encoding="utf-8",
            )
            _write_feature_spec(tmp_path, _deep_payload())
            d = assess_feature_spec_depth(tmp_path)
            self.assertTrue(any("text_input" in a for a in d["advisories"]), d["advisories"])

    def test_p2_majority_is_advisory_and_p2_listed(self):
        payload = _deep_payload()
        for f in payload["features"][2:]:
            f["priority"] = "P2"
        payload["features"].append({
            "id": "extra-stub", "title": "Extra", "priority": "P2",
            "screen": "Home", "anchor": "autobot.extra", "acceptance": [],
        })
        d = self._assess(payload)  # P2=4 > P0+P1=2
        self.assertTrue(any("outnumber" in a for a in d["advisories"]), d["advisories"])
        self.assertEqual(len(d["p2_features"]), 4)

    def test_partial_role_coverage_flags_missing_role_advisory(self):
        # Some P0/P1 declare a role, one does not. The old "any role ⇒ whole spec
        # migrated" heuristic let the role-less feature pass silently; now it is
        # an advisory (warn-default, DEGRADED under quality-max).
        payload = _deep_payload()
        del payload["features"][3]["role"]  # a P1 loses its role; hook+retention remain
        d = self._assess(payload)
        self.assertTrue(
            any("declare no role" in a for a in d["advisories"]), d["advisories"])
        self.assertEqual(d["problems"], [])  # hook+retention still present

    def test_persistence_pair_only_on_p2_does_not_satisfy(self):
        # setting_stored lives on a P0/P1 flow, but the value_persisted pair is
        # parked on a P2 feature — never driven at Gate 5->6, so the pairing is
        # unproven and the advisory must still fire.
        payload = _deep_payload()
        payload["features"][2]["acceptance"][0]["postcondition"]["kind"] = "setting_stored"
        payload["features"].append({
            "id": "p2-persist", "title": "P2 persist", "priority": "P2",
            "screen": "Home", "anchor": "autobot.p2",
            "acceptance": [{
                "id": "a", "kind": "flow",
                "steps": [{"action": "tap", "anchor": "autobot.p2"}],
                "postcondition": {"kind": "value_persisted_after_relaunch", "params": {}},
            }],
        })
        d = self._assess(payload)
        self.assertTrue(
            any("value_persisted_after_relaunch" in a for a in d["advisories"]),
            d["advisories"])

    def test_allow_preexisting_on_p0_flow_is_advisory(self):
        # allow_preexisting waives navigated_to's novelty proof — auditable as an
        # advisory when used on a P0 flow.
        payload = _deep_payload()
        payload["features"][1]["acceptance"][0]["postcondition"]["params"] = {
            "anchor": "autobot.weekly.out", "allow_preexisting": True,
        }
        d = self._assess(payload)
        self.assertTrue(
            any("allow_preexisting" in a for a in d["advisories"]), d["advisories"])

    def test_absent_spec_is_problem_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = assess_feature_spec_depth(Path(tmp))
            self.assertTrue(any("absent" in p for p in d["problems"]), d)


class TestInputIntentSignal(unittest.TestCase):
    def test_matches_search_and_korean_memo(self):
        self.assertIsNotNone(input_intent_signal("an app to search recipes"))
        self.assertIsNotNone(input_intent_signal("간단한 메모 앱"))

    def test_no_match_for_plain_viewer_idea(self):
        self.assertIsNone(input_intent_signal("a timer with preset intervals"))


if __name__ == "__main__":
    unittest.main()
