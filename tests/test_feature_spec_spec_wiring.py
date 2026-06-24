"""spec/pipeline.json wiring for the feature-spec spine: Gate 1->2 must list
feature_spec_declared + feature_spec_quality, Gate 4->5 keeps intent_anchors_in_ui,
and every named procedural check must have an impl in the GATE_CHECKS registry.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import gate_runner  # noqa: E402
from gate_checks.registry import GATE_CHECKS  # noqa: E402

SPEC = Path(__file__).resolve().parent.parent / "spec" / "pipeline.json"


def _names(gate: dict) -> list[str]:
    return [c.get("name") for c in gate.get("checks", []) if c.get("type") == "procedural"]


def _procedural_names(checks: list[dict]) -> list[str]:
    names: list[str] = []
    for check in checks:
        if check.get("type") == "procedural":
            names.append(check["name"])
        elif check.get("type") == "all":
            names.extend(_procedural_names(check.get("checks", [])))
    return names


class TestFeatureSpecSpecWiring(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(SPEC.read_text(encoding="utf-8"))
        self.gates = self.spec["gates"]

    def test_gate_1_2_lists_feature_spec_checks(self):
        names = _names(self.gates["1->2"])
        self.assertIn("feature_spec_declared", names)
        self.assertIn("feature_spec_quality", names)

    def test_gate_4_5_keeps_intent_anchors(self):
        names = _names(self.gates["4->5"])
        self.assertIn("intent_anchors_in_ui", names)

    def test_new_checks_have_impls(self):
        for name in ("feature_spec_declared", "feature_spec_quality", "intent_anchors_in_ui"):
            self.assertIn(name, GATE_CHECKS, f"{name} missing from GATE_CHECKS registry")

    def test_all_spec_procedural_checks_have_impls(self):
        missing = []
        for gate_id, gate in self.gates.items():
            for name in _procedural_names(gate.get("checks", [])):
                if name not in GATE_CHECKS:
                    missing.append(f"{gate_id}:{name}")
        self.assertEqual(missing, [])

    def test_gate_runner_reexports_registry_object(self):
        self.assertIs(gate_runner.GATE_CHECKS, GATE_CHECKS)

    def test_descriptor_shape(self):
        for c in self.gates["1->2"]["checks"]:
            if c.get("name") in ("feature_spec_declared", "feature_spec_quality"):
                self.assertEqual(c["type"], "procedural")
                self.assertEqual(c["label"], c["name"])


if __name__ == "__main__":
    unittest.main()
