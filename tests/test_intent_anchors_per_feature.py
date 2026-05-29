"""Gate 4->5 intent_anchors_in_ui — generalized to per-feature anchors.
When feature-spec.json is present, each feature's anchor must appear in the
UI source; the failure names which FEATURE is missing its UI. Falls back to
flat app-intent requiredAnchors when feature-spec is absent.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import check_intent_anchors_in_ui  # noqa: E402


def _autobot(root: Path) -> Path:
    d = root / ".autobot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_feature_spec(root: Path, features: list[dict]) -> None:
    _autobot(root)
    (root / ".autobot" / "feature-spec.json").write_text(
        json.dumps({"features": features}), encoding="utf-8")


def _write_app_intent(root: Path, payload: dict) -> None:
    _autobot(root)
    (root / ".autobot" / "app-intent.json").write_text(
        json.dumps(payload), encoding="utf-8")


def _write_view(root: Path, app: str, name: str, anchors: list[str]) -> None:
    vdir = root / app / "Views"
    vdir.mkdir(parents=True, exist_ok=True)
    body = "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\")"
    for a in anchors:
        body += f'.accessibilityIdentifier("{a}")'
    body += " } }"
    (vdir / f"{name}.swift").write_text(body, encoding="utf-8")


def _feat(fid, anchor, priority="P0") -> dict:
    return {"id": fid, "title": fid, "priority": priority, "screen": "Home",
            "anchor": anchor,
            "acceptance": [{"id": f"{fid}.a1", "kind": "flow",
                            "steps": [{"action": "tap", "anchor": anchor}],
                            "postcondition": {"kind": "navigated_to", "params": {}}}]}


class TestPerFeatureAnchors(unittest.TestCase):
    def test_all_feature_anchors_present_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_feature_spec(root, [
                _feat("log", "autobot.log.cta"),
                _feat("share", "autobot.share.cta"),
            ])
            _write_view(root, "Demo", "Screens",
                        ["autobot.log.cta", "autobot.share.cta"])
            r = check_intent_anchors_in_ui(root, "Demo", {})
            self.assertTrue(r[0]["passed"], r[0]["message"])

    def test_missing_feature_anchor_names_feature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_feature_spec(root, [
                _feat("log", "autobot.log.cta"),
                _feat("share", "autobot.share.cta"),
            ])
            # only log's anchor is in the UI
            _write_view(root, "Demo", "Screens", ["autobot.log.cta"])
            r = check_intent_anchors_in_ui(root, "Demo", {})
            self.assertFalse(r[0]["passed"])
            # message must name the FEATURE (id), not just the anchor
            self.assertIn("share", r[0]["message"])
            self.assertIn("autobot.share.cta", r[0]["message"])

    def test_p2_feature_missing_anchor_still_fails(self):
        # generalized check asserts EVERY feature's anchor regardless of priority;
        # priority tiering is for acceptance/flows, not for anchor presence.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_feature_spec(root, [_feat("opt", "autobot.opt.cta", priority="P2")])
            _write_view(root, "Demo", "Screens", [])
            r = check_intent_anchors_in_ui(root, "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertIn("opt", r[0]["message"])

    def test_falls_back_to_app_intent_when_no_feature_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_app_intent(root, {
                "appName": "Demo", "promise": "p",
                "primaryScreenTitle": "Home", "primaryCTA": "Go",
                "requiredAnchors": ["autobot.root", "autobot.primaryCTA"],
            })
            _write_view(root, "Demo", "Screens",
                        ["autobot.root", "autobot.primaryCTA"])
            r = check_intent_anchors_in_ui(root, "Demo", {})
            self.assertTrue(r[0]["passed"], r[0]["message"])

    def test_falls_back_and_detects_missing_app_intent_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_app_intent(root, {
                "appName": "Demo", "promise": "p",
                "primaryScreenTitle": "Home", "primaryCTA": "Go",
                "requiredAnchors": ["autobot.root", "autobot.primaryCTA"],
            })
            _write_view(root, "Demo", "Screens", ["autobot.root"])
            r = check_intent_anchors_in_ui(root, "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertIn("autobot.primaryCTA", r[0]["message"])

    def test_no_spec_at_all_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = check_intent_anchors_in_ui(Path(tmp), "Demo", {})
            self.assertTrue(r[0]["passed"])
            self.assertTrue(r[0].get("skipped"))


if __name__ == "__main__":
    unittest.main()
