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
    AppIntent,
    DEFAULT_REQUIRED_ANCHORS,
    find_unused_anchors,
    load_app_intent,
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


if __name__ == "__main__":
    unittest.main()
