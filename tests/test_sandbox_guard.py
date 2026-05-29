"""Tests for scripts/sandbox_guard.py — pre-write file-ownership enforcement
and the .guard-active marker behavior.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from sandbox_guard import check  # noqa: E402


class TestSandboxGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()
        (self.proj / ".autobot" / "build-state.json").write_text(
            json.dumps({"appName": "Demo"})
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _set_active(self, agent: str, phase: str = "4") -> None:
        (self.proj / ".autobot" / ".guard-active").write_text(
            json.dumps({"agent": agent, "phase": phase})
        )

    def _clear_active(self) -> None:
        marker = self.proj / ".autobot" / ".guard-active"
        if marker.exists():
            marker.unlink()

    # ── allow paths ──

    def test_ui_builder_can_write_views(self):
        self._set_active("ui-builder")
        allowed, reason = check(self.proj, self.proj / "Demo" / "Views" / "HomeView.swift")
        self.assertTrue(allowed, reason)

    def test_data_engineer_can_write_services(self):
        self._set_active("data-engineer")
        allowed, _ = check(self.proj, self.proj / "Demo" / "Services" / "ItemRepository.swift")
        self.assertTrue(allowed)

    def test_architect_can_write_models(self):
        self._set_active("architect")
        allowed, _ = check(self.proj, self.proj / "Demo" / "Models" / "Item.swift")
        self.assertTrue(allowed)

    # ── deny paths ──

    def test_ui_builder_cannot_write_models(self):
        self._set_active("ui-builder")
        allowed, reason = check(self.proj, self.proj / "Demo" / "Models" / "Item.swift")
        self.assertFalse(allowed)
        self.assertIn("may not write", reason)

    def test_data_engineer_cannot_write_views(self):
        self._set_active("data-engineer")
        allowed, _ = check(self.proj, self.proj / "Demo" / "Views" / "Item.swift")
        self.assertFalse(allowed)

    def test_writes_outside_project_blocked(self):
        self._set_active("ui-builder")
        allowed, _ = check(self.proj, self.proj / "random_root_file.swift")
        self.assertFalse(allowed)

    # ── marker absence / broadAccess ──

    def test_no_marker_falls_back_to_quality_engineer_broad_access(self):
        # No marker → quality-engineer (broadAccess) → an ordinary project file
        # is allowed so orchestrator self-step edits keep working.
        self._clear_active()
        allowed, reason = check(self.proj, self.proj / "Demo" / "App" / "CompositionRoot.swift")
        self.assertTrue(allowed, reason)

    def test_quality_engineer_broad_access_allows_ordinary_file(self):
        self._set_active("quality-engineer")
        allowed, reason = check(self.proj, self.proj / "Demo" / "App" / "Wiring.swift")
        self.assertTrue(allowed, reason)

    # ── forbidden floor: enforced even for broadAccess (the core fix) ──

    def test_broad_access_cannot_write_models_forbidden_floor(self):
        # quality-engineer has broadAccess but is NOT in forbiddenAlwaysExempt,
        # so it must still be blocked from Models/ (architect-only contract).
        self._set_active("quality-engineer")
        allowed, reason = check(self.proj, self.proj / "Demo" / "Models" / "Item.swift")
        self.assertFalse(allowed, "broadAccess must not bypass forbiddenAlways")
        self.assertIn("FORBIDDEN", reason)

    def test_no_marker_cannot_write_models_forbidden_floor(self):
        self._clear_active()
        allowed, reason = check(self.proj, self.proj / "Demo" / "Models" / "Item.swift")
        self.assertFalse(allowed, "no-marker default must not bypass forbiddenAlways")
        self.assertIn("FORBIDDEN", reason)

    def test_broad_access_cannot_write_infra_control_files(self):
        self._set_active("quality-engineer")
        for infra in ("build-state.json", "learnings.json", "build.lock"):
            with self.subTest(infra=infra):
                allowed, reason = check(self.proj, self.proj / ".autobot" / infra)
                self.assertFalse(allowed, f"broadAccess must not write {infra}")
                self.assertIn("INFRA", reason)

    # ── per-agent overlap (forbiddenPerAgent) ──

    def test_ui_builder_cannot_write_services_overlap(self):
        self._set_active("ui-builder")
        allowed, reason = check(self.proj, self.proj / "Demo" / "Services" / "Repo.swift")
        self.assertFalse(allowed)
        self.assertIn("OVERLAP", reason)

    def test_design_system_cannot_write_app_tree_overlap(self):
        self._set_active("design-system")
        allowed, reason = check(self.proj, self.proj / "Demo" / "Views" / "X.swift")
        self.assertFalse(allowed)
        self.assertIn("OVERLAP", reason)

    # ── architect writes its full declared output set ──

    def test_architect_can_write_intent_artifacts(self):
        self._set_active("architect")
        for art in ("architecture.json", "app-intent.json", "feature-spec.json"):
            with self.subTest(art=art):
                allowed, reason = check(self.proj, self.proj / ".autobot" / art)
                self.assertTrue(allowed, f"architect must be able to write {art}: {reason}")

    # ── explicit agent override ──

    def test_explicit_agent_overrides_marker(self):
        self._set_active("quality-engineer")  # broad
        allowed, _ = check(
            self.proj,
            self.proj / "Demo" / "Models" / "Item.swift",
            agent="ui-builder",  # explicit narrow
        )
        self.assertFalse(allowed)

    def test_unknown_agent_denied(self):
        allowed, reason = check(
            self.proj,
            self.proj / "Demo" / "Views" / "X.swift",
            agent="invented-agent",
        )
        self.assertFalse(allowed)
        self.assertIn("unknown agent", reason)


if __name__ == "__main__":
    unittest.main()
