"""Tests for scripts/context_pack.py — REQUIRED INPUTS must surface the full
transitive-upstream contract, not just the immediate dependency.

Regression guard for the gap where phase-4 coders' pack listed design-system's
Packages/ (immediate dep, Phase 3) but NOT the Phase-1 {appName}/Models/ +
ServiceProtocols.swift type contract their whole prompt depends on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import context_pack  # noqa: E402
from spec_loader import load_spec  # noqa: E402


class TestContextPackRequiredInputs(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        self.spec = load_spec()
        self.app = "Demo"
        # Phase-1 (architect) outputs — the type contract.
        models = self.proj / self.app / "Models"
        models.mkdir(parents=True)
        (models / "Item.swift").write_text("import SwiftData\n@Model final class Item {}\n")
        (models / "ServiceProtocols.swift").write_text("protocol ItemService {}\n")
        # Phase-3 (design-system) output — the immediate dependency.
        pkg = self.proj / "Packages" / "DesignSystem" / "Sources"
        pkg.mkdir(parents=True)
        (pkg / "Theme.swift").write_text("public enum Theme {}\n")
        (self.proj / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _inputs(self, agent: str) -> list[str]:
        ins = context_pack._required_inputs(self.spec, agent, self.app, self.proj)
        return [i["path"] for i in ins]

    def test_phase4_coder_gets_phase1_models_contract(self):
        paths = self._inputs("ui-builder")
        self.assertIn(f"{self.app}/Models/Item.swift", paths,
                      "phase-4 coder must receive the Phase-1 Models/ type contract")
        self.assertIn(f"{self.app}/Models/ServiceProtocols.swift", paths,
                      "phase-4 coder must receive the ServiceProtocols contract")

    def test_phase4_coder_still_gets_immediate_dep_packages(self):
        paths = self._inputs("data-engineer")
        self.assertTrue(any(p.startswith("Packages/") for p in paths),
                        "the immediate Phase-3 dependency must still be present")
        # And the transitive Models/ contract too.
        self.assertIn(f"{self.app}/Models/ServiceProtocols.swift", paths)

    def test_inputs_are_deduped_by_path(self):
        paths = self._inputs("ui-builder")
        self.assertEqual(len(paths), len(set(paths)), "no duplicate input paths")

    def test_pack_text_lists_models_under_required_inputs(self):
        state = {"appName": self.app}
        result = context_pack.build(self.proj, self.spec, state, phase="4", agent="ui-builder")
        self.assertIn("REQUIRED INPUTS", result["text"])
        self.assertIn(f"{self.app}/Models/ServiceProtocols.swift", result["text"])

    def test_pack_does_not_duplicate_static_guidance_or_learnings(self):
        result = context_pack.build(
            self.proj, self.spec, {"appName": self.app},
            phase="4", agent="ui-builder",
        )
        self.assertNotIn("HIGH-IMPACT LEARNINGS", result["text"])
        self.assertNotIn("REFERENCE INDEX", result["text"])


class TestTransitiveUpstream(unittest.TestCase):
    def test_phase4_closure_includes_phase1(self):
        phases = load_spec()["phases"]
        up = context_pack._transitive_upstream(phases, "4")
        self.assertIn("1", up, "Phase 4's transitive upstream must include Phase 1")
        self.assertIn("3", up)
        self.assertNotIn("4", up, "a phase is not its own upstream")
        self.assertNotIn("5", up, "downstream phases are not upstream")


if __name__ == "__main__":
    unittest.main()
