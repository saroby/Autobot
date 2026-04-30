"""Sandbox enforcement: unknown agent, ownership violation, state recording."""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, run_sandbox


class TestSandbox(IsolatedProjectCase):

    def test_unknown_agent_rejected(self):
        result = run_sandbox(
            "before", "--agent", "phantom-agent", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not declared", result.stdout + result.stderr)

    def test_violation_recorded_in_state(self):
        # ui-builder writing into Services/ violates ownership.
        services = self.project_dir / self.APP_NAME / "Services"
        services.mkdir(parents=True, exist_ok=True)

        run_sandbox("before", "--agent", "ui-builder", "--app-name", self.APP_NAME,
                    project_dir=self.project_dir)
        (services / "Bad.swift").touch()
        result = run_sandbox(
            "after", "--agent", "ui-builder", "--app-name", self.APP_NAME, "--phase", "4",
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)

        sandbox_state = self.state()["phases"]["4"].get("sandbox", {})
        self.assertIn("ui-builder", sandbox_state.get("agentsVerified", []))
        violations = sandbox_state.get("violations", [])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["agent"], "ui-builder")
        self.assertEqual(violations[0]["kind"], "OVERLAP")

    def test_clean_run_zero_violations(self):
        views = self.project_dir / self.APP_NAME / "Views"
        views.mkdir(parents=True, exist_ok=True)

        run_sandbox("before", "--agent", "ui-builder", "--app-name", self.APP_NAME,
                    project_dir=self.project_dir)
        (views / "OK.swift").touch()
        result = run_sandbox(
            "after", "--agent", "ui-builder", "--app-name", self.APP_NAME, "--phase", "4",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        sandbox_state = self.state()["phases"]["4"].get("sandbox", {})
        self.assertEqual(sandbox_state.get("violations", []), [])


if __name__ == "__main__":
    unittest.main()
