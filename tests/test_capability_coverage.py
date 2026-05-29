"""Tests for scripts/capability_coverage.py — makes the feature's limits loud.

Covers: P2-downgrade surfacing, requested-but-unbuilt iOS categories, backend
localhost warning, AXe/simulator prereq install hints, device-deploy note,
advisory Views scan, and the rendered markdown section.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import capability_coverage as cc  # noqa: E402


class TestCapabilityCoverage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _state(self, **kw) -> None:
        (self.proj / ".autobot" / "build-state.json").write_text(json.dumps(kw))

    def _arch(self, text: str) -> None:
        (self.proj / ".autobot" / "architecture.md").write_text(text)

    def _feature_spec(self, features: list) -> None:
        (self.proj / ".autobot" / "feature-spec.json").write_text(
            json.dumps({"version": 1, "features": features})
        )

    def _env(self, *, axe: bool, sim: bool) -> None:
        (self.proj / ".autobot" / "env_snapshot.json").write_text(json.dumps({
            "simulator": {"udid": "X"} if sim else None,
            "environment": {"axe": axe},
        }))

    # ── scope surfacing ──

    def test_p2_features_surfaced_as_downgraded(self):
        self._state(appName="Demo")
        self._feature_spec([
            {"id": "core", "title": "Log it", "priority": "P0", "acceptance": []},
            {"id": "share", "title": "Share to friends", "priority": "P2", "acceptance": []},
        ])
        cov = cc.assess(self.proj)
        ids = [f["id"] for f in cov["scope"]["downgradedFeatures"]]
        self.assertEqual(ids, ["share"])

    def test_unsupported_categories_detected_from_idea(self):
        self._state(appName="Demo", idea="A meditation app with a daily-reminder widget and subscriptions")
        cov = cc.assess(self.proj)
        cats = {u["category"] for u in cov["scope"]["unsupportedRequested"]}
        self.assertIn("Home-screen widgets (WidgetKit)", cats)
        self.assertIn("In-app purchases / subscriptions (StoreKit)", cats)

    def test_unsupported_detected_from_architecture_text(self):
        self._state(appName="Demo")
        self._arch("## Overview\nReal-time chat with sync across devices via CloudKit.")
        cov = cc.assess(self.proj)
        cats = {u["category"] for u in cov["scope"]["unsupportedRequested"]}
        self.assertIn("Real-time / collaboration (WebSocket)", cats)
        self.assertIn("Cross-device sync (CloudKit)", cats)

    def test_no_false_positive_for_plain_crud_idea(self):
        self._state(appName="Demo", idea="A simple to-do list to track daily tasks")
        cov = cc.assess(self.proj)
        self.assertEqual(cov["scope"]["unsupportedRequested"], [])

    def test_backend_pending_warning_when_required(self):
        self._state(appName="Demo", backend_required=True)
        cov = cc.assess(self.proj)
        self.assertIsNotNone(cov["scope"]["backend"])
        self.assertFalse(cov["scope"]["backend"]["deployed"])
        self.assertIn("localhost", cov["scope"]["backend"]["note"])

    def test_no_backend_block_when_not_required(self):
        self._state(appName="Demo", backend_required=False)
        self.assertIsNone(cc.assess(self.proj)["scope"]["backend"])

    # ── verification prereqs ──

    def test_missing_axe_yields_install_hint(self):
        self._state(appName="Demo")
        self._env(axe=False, sim=True)
        cov = cc.assess(self.proj)
        axe = next(p for p in cov["verification"]["prereqs"] if "AXe" in p["tool"])
        self.assertFalse(axe["present"])
        self.assertIn("brew install", axe["installHint"])

    def test_present_axe_marked_present(self):
        self._state(appName="Demo")
        self._env(axe=True, sim=True)
        cov = cc.assess(self.proj)
        axe = next(p for p in cov["verification"]["prereqs"] if "AXe" in p["tool"])
        self.assertTrue(axe["present"])

    def test_badge_reflects_gate_status(self):
        self._state(appName="Demo", gates={"5->6": {"status": "degraded"}})
        self.assertEqual(cc.assess(self.proj)["verification"]["badge"], "DEGRADED")

    # ── advisory Views scan ──

    def test_views_scan_counts_hardcoded_colors_and_modern_api(self):
        self._state(appName="Demo")
        views = self.proj / "Demo" / "Views"
        views.mkdir(parents=True)
        (views / "HomeView.swift").write_text(
            "import SwiftUI\nstruct HomeView: View {\n"
            "  var body: some View { Text(\"hi\").foregroundStyle(Color(red: 1, green: 0, blue: 0)) }\n}\n"
        )
        cov = cc.assess(self.proj)
        self.assertTrue(cov["quality"]["scanned"])
        self.assertGreaterEqual(cov["quality"]["hardcodedColorHits"], 1)
        self.assertFalse(cov["quality"]["modernApiUsed"])

    def test_views_scan_detects_modern_api(self):
        self._state(appName="Demo")
        views = self.proj / "Demo" / "Views"
        views.mkdir(parents=True)
        (views / "HomeView.swift").write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { "
            "Text(\"x\").glassEffect() } }\n"
        )
        cov = cc.assess(self.proj)
        self.assertTrue(cov["quality"]["modernApiUsed"])
        self.assertIn("glassEffect", cov["quality"]["modernApiMarkers"])

    def test_views_scan_degrades_when_no_app(self):
        self._state(appName="Demo")
        self.assertFalse(cc.assess(self.proj)["quality"]["scanned"])

    # ── fail-safe + render ──

    def test_assess_on_empty_project_does_not_crash(self):
        cov = cc.assess(self.proj)  # only .autobot/ exists
        self.assertIn("verification", cov)
        self.assertIn("scope", cov)

    def test_render_surfaces_all_loud_warnings(self):
        self._state(appName="Demo", idea="chat app with widget", backend_required=True,
                    gates={"5->6": {"status": "degraded"}})
        self._env(axe=False, sim=False)
        self._feature_spec([{"id": "share", "title": "Share", "priority": "P2", "acceptance": []}])
        md = cc.render(cc.assess(self.proj))
        self.assertIn("## Capability Coverage", md)
        self.assertIn("brew install", md)                  # AXe hint
        self.assertIn("aspirational stubs", md)            # P2
        self.assertIn("does NOT include", md)              # unsupported categories
        self.assertIn("localhost", md)                     # backend pending
        self.assertIn("On-device", md)                     # device deploy note
        self.assertIn("Changing the app", md)              # iteration guidance


if __name__ == "__main__":
    unittest.main()
