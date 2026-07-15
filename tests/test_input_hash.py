"""Tests for scripts/input_hash.py — per-phase input manifest hashing and
idempotent skip semantics that /autobot:resume relies on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from input_hash import (  # noqa: E402
    compute_phase_input_hash,
    mark_inputs,
    should_skip_phase,
)
from spec_loader import load_spec  # noqa: E402


def _setup_project(tmp: Path, *, models: list[str] | None = None) -> dict:
    (tmp / ".autobot").mkdir()
    if models is not None:
        models_dir = tmp / "DemoApp" / "Models"
        models_dir.mkdir(parents=True, exist_ok=True)
        for name in models:
            (models_dir / f"{name}.swift").write_text(f"struct {name} {{}}")
    return {"appName": "DemoApp", "idea": "demo idea", "phases": {}}


class TestComputeHash(unittest.TestCase):
    def test_same_inputs_yield_same_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            spec = load_spec()
            h1, _ = compute_phase_input_hash(proj, spec, state, "1")
            h2, _ = compute_phase_input_hash(proj, spec, state, "1")
            self.assertEqual(h1, h2)

    def test_owned_file_change_changes_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            spec = load_spec()
            h1, m1 = compute_phase_input_hash(proj, spec, state, "1")
            self.assertGreaterEqual(len(m1["ownedFiles"]), 1)
            (proj / "DemoApp" / "Models" / "Item.swift").write_text("struct Item { var x = 1 }")
            h2, _ = compute_phase_input_hash(proj, spec, state, "1")
            self.assertNotEqual(h1, h2)

    def test_idea_change_changes_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            spec = load_spec()
            h1, _ = compute_phase_input_hash(proj, spec, state, "1")
            state["idea"] = "completely different idea"
            h2, _ = compute_phase_input_hash(proj, spec, state, "1")
            self.assertNotEqual(h1, h2)

    def test_transitive_upstream_file_change_changes_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj)
            upstream = proj / ".autobot" / "design-spec.md"
            upstream.write_text("design A")
            spec = load_spec()

            h1, manifest = compute_phase_input_hash(proj, spec, state, "3")
            self.assertIn(".autobot/design-spec.md", manifest["requiredInputs"])

            upstream.write_text("design B")
            h2, _ = compute_phase_input_hash(proj, spec, state, "3")
            self.assertNotEqual(h1, h2)

    def test_phase_three_includes_phase_one_model_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            spec = load_spec()
            model = proj / "DemoApp" / "Models" / "Item.swift"

            h1, manifest = compute_phase_input_hash(proj, spec, state, "3")
            self.assertIn("DemoApp/Models/Item.swift", manifest["requiredInputs"])
            model.write_text("struct Item { let id: Int }")
            h2, _ = compute_phase_input_hash(proj, spec, state, "3")
            self.assertNotEqual(h1, h2)


class TestShouldSkip(unittest.TestCase):
    def test_unstored_hash_means_no_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            state["phases"]["1"] = {"status": "completed"}
            spec = load_spec()
            skip, reason = should_skip_phase(proj, spec, state, "1")
            self.assertFalse(skip)
            self.assertIn("no stored inputHash", reason)

    def test_matching_hash_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            state["phases"]["1"] = {"status": "completed"}
            spec = load_spec()
            h, m = compute_phase_input_hash(proj, spec, state, "1")
            mark_inputs(state, "1", hash_value=h, manifest=m)
            skip, reason = should_skip_phase(proj, spec, state, "1")
            self.assertTrue(skip, reason)

    def test_file_mutation_invalidates_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            state["phases"]["1"] = {"status": "completed"}
            spec = load_spec()
            h, m = compute_phase_input_hash(proj, spec, state, "1")
            mark_inputs(state, "1", hash_value=h, manifest=m)
            (proj / "DemoApp" / "Models" / "Item.swift").write_text("struct Item { var z = 99 }")
            skip, reason = should_skip_phase(proj, spec, state, "1")
            self.assertFalse(skip)
            self.assertIn("inputHash mismatch", reason)

    def test_force_disables_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            state["phases"]["1"] = {"status": "completed"}
            spec = load_spec()
            h, m = compute_phase_input_hash(proj, spec, state, "1")
            mark_inputs(state, "1", hash_value=h, manifest=m)
            skip, reason = should_skip_phase(proj, spec, state, "1", force=True)
            self.assertFalse(skip)
            self.assertEqual(reason, "force flag set")

    def test_non_terminal_status_does_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            state = _setup_project(proj, models=["Item"])
            state["phases"]["1"] = {"status": "failed", "inputHash": "anything"}
            spec = load_spec()
            skip, reason = should_skip_phase(proj, spec, state, "1")
            self.assertFalse(skip)
            self.assertIn("not terminal-success", reason)


class TestMarkInputs(unittest.TestCase):
    def test_stores_hash_and_compressed_manifest(self):
        state: dict = {"phases": {}}
        manifest = {
            "idea": {"idea": "x"},
            "ownedFiles": {"a.swift": "abc", "b.swift": "def"},
        }
        mark_inputs(state, "4", hash_value="HASH123", manifest=manifest)
        phase_block = state["phases"]["4"]
        self.assertEqual(phase_block["inputHash"], "HASH123")
        self.assertEqual(phase_block["inputManifest"]["ownedFileCount"], 2)
        self.assertEqual(phase_block["inputManifest"]["requiredInputCount"], 0)


if __name__ == "__main__":
    unittest.main()
