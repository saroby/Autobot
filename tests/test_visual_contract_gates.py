"""Look-and-feel contract gates."""

from __future__ import annotations

import json
import unittest

from conftest import IsolatedProjectCase, run_pipeline


class TestVisualContractGates(IsolatedProjectCase):

    def _write_state(self, state: dict) -> None:
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2)
        )

    def _prepare_phase1_artifacts(self, architecture: str) -> None:
        autobot = self.project_dir / ".autobot"
        autobot.mkdir(exist_ok=True)
        (autobot / "architecture.md").write_text(architecture, encoding="utf-8")

        models = self.project_dir / self.APP_NAME / "Models"
        models.mkdir(parents=True, exist_ok=True)
        (models / "Item.swift").write_text("import Foundation\nstruct Item {}\n", encoding="utf-8")
        (models / "ServiceProtocols.swift").write_text(
            "import Foundation\nprotocol ItemRepository {}\n",
            encoding="utf-8",
        )

        snap = autobot / "contracts" / "phase-1-models"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "Item.swift").write_text("import Foundation\nstruct Item {}\n", encoding="utf-8")
        (autobot / "contracts" / "models.sha256").write_text("checksum\n", encoding="utf-8")

        state = self.state()
        state["phases"]["1"] = {
            "status": "in_progress",
            "startedAt": "t",
            "retryCount": 0,
            "metadata": {"codexReview": {"verdict": "PASS", "attempt": 1}},
            "learningsConsumed": ["architect"],
        }
        self._write_state(state)

    def test_gate_1_requires_design_direction_subsections(self):
        self._prepare_phase1_artifacts(
            """# Architecture

## Screens
- Home screen

## Design Direction
Use a distinctive palette role and a clear design direction.

## Layout
Use a dashboard layout pattern.

## Services
Use a service layer and service protocol integration.

## Privacy
Use privacy-safe file.timestamp C617 metadata.
"""
        )

        result = run_pipeline(
            "run-gate", "--gate", "1->2", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("design_direction_complete", result.stdout + result.stderr)

    def test_gate_2_fallback_still_requires_design_spec(self):
        state = self.state()
        state["phases"]["2"] = {"status": "fallback", "completedAt": "t", "retryCount": 0}
        self._write_state(state)

        result = run_pipeline(
            "run-gate", "--gate", "2->3", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("design_spec", result.stdout + result.stderr)

    def test_gate_2_requires_design_spec_sections(self):
        autobot = self.project_dir / ".autobot"
        autobot.mkdir(exist_ok=True)
        (autobot / "design-spec.md").write_text(
            "# UX Design Specification\n\n## Design Tokens\n- blue\n",
            encoding="utf-8",
        )
        state = self.state()
        state["phases"]["2"] = {"status": "fallback", "completedAt": "t", "retryCount": 0}
        self._write_state(state)

        result = run_pipeline(
            "run-gate", "--gate", "2->3", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("design_spec_sections_complete", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
