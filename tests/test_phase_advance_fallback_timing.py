"""Regression: --status fallback must propagate into the state passed to the
gate so fallback-aware checks (e.g. design_assets_exist_or_fallback) take
their relaxed branch BEFORE the gate verdict is locked in.

Build-20260526-solos Phase 2 trap: ux-designer produced a text-only spec,
the orchestrator called advance --status fallback, but the gate evaluated
against the still-in_progress state and rejected the build for missing PNGs.
"""

from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from conftest import import_runtime_modules

import_runtime_modules()

import phase_advance  # noqa: E402


class TestFallbackPropagatesIntoGate(unittest.TestCase):
    def _make_state_and_args(self, project_dir: Path, target_status: str) -> tuple[dict, types.SimpleNamespace]:
        state_path = project_dir / ".autobot" / "build-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "buildId": "test", "appName": "X", "displayName": "X",
            "bundleId": "x.x", "backendRequired": False,
            "phases": {
                "0": {"status": "completed"}, "1": {"status": "completed"},
                "2": {"status": "in_progress"}, "2.5": {"status": "pending"},
                "3": {"status": "pending"}, "4": {"status": "pending"},
                "5": {"status": "pending"}, "6": {"status": "pending"},
                "7": {"status": "pending"},
            },
            "environment": {"axiom": False, "stitch": False, "fastlane": False, "ascConfigured": False},
        }))
        args = types.SimpleNamespace(
            phase=2, project_dir=str(project_dir), state_file=None,
            app_name="X", status=target_status, at="2026-05-28T00:00:00Z",
            detail=None, metadata=None, format="json",
        )
        return {}, args

    def test_fallback_status_visible_to_gate(self) -> None:
        proj = Path(tempfile.mkdtemp())
        _, args = self._make_state_and_args(proj, "fallback")
        captured_state: dict = {}

        def fake_gate(gate_id, pd, app, state, spec):
            captured_state.update(state)
            # Pretend the fallback branch passes
            return {"passed": True, "checks": [], "gate": gate_id}

        with patch.object(phase_advance, "execute_gate", side_effect=fake_gate):
            phase_advance._advance_phase_core(args)

        # The gate must have seen phase 2 status == fallback, not in_progress.
        self.assertEqual(
            captured_state["phases"]["2"]["status"], "fallback",
            "execute_gate received stale in_progress status — fallback intent was dropped",
        )

    def test_non_fallback_status_keeps_actual_state(self) -> None:
        proj = Path(tempfile.mkdtemp())
        _, args = self._make_state_and_args(proj, "completed")
        captured_state: dict = {}

        def fake_gate(gate_id, pd, app, state, spec):
            captured_state.update(state)
            return {"passed": True, "checks": [], "gate": gate_id}

        with patch.object(phase_advance, "execute_gate", side_effect=fake_gate):
            phase_advance._advance_phase_core(args)

        # No mutation for normal completion path.
        self.assertEqual(captured_state["phases"]["2"]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
