"""Sandbox enforcement: unknown agent, ownership violation, state recording."""

from __future__ import annotations

import unittest
from pathlib import Path

from conftest import IsolatedProjectCase, import_runtime_modules, run_sandbox

import_runtime_modules()

from gate_checks.app import check_sandbox_clean  # noqa: E402


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


class TestSandboxCleanGate(unittest.TestCase):
    """check_sandbox_clean is a pure state-dict reader — no tmp project needed."""

    PROJ = Path("/tmp")
    APP = "Demo"
    FULL = ["ui-builder", "data-engineer"]  # backend_required=False set

    def _state(self, *, agents=None, violations=None, backend=False) -> dict:
        sandbox = {}
        if agents is not None:
            sandbox["agentsVerified"] = agents
        if violations is not None:
            sandbox["violations"] = violations
        state = {"phases": {"4": {"sandbox": sandbox}}}
        if backend:
            state["backend_required"] = True
        return state

    def _by_check(self, state: dict) -> dict:
        return {r["check"]: r for r in check_sandbox_clean(self.PROJ, self.APP, state)}

    def test_no_agents_verified_fails(self):
        r = self._by_check(self._state())
        self.assertFalse(r["sandbox_recorded"]["passed"])
        self.assertIn("agent-sandbox.sh after", r["sandbox_recorded"]["message"])

    def test_partial_agents_verified_fails_naming_missing(self):
        # One agent skipping its verify must not roll up as "all agents verified".
        r = self._by_check(self._state(agents=["ui-builder"], violations=[]))
        self.assertFalse(r["sandbox_recorded"]["passed"])
        self.assertIn("data-engineer", r["sandbox_recorded"]["message"])
        self.assertNotIn("backend-engineer", r["sandbox_recorded"]["message"])

    def test_backend_required_also_expects_backend_engineer(self):
        r = self._by_check(self._state(agents=self.FULL, violations=[], backend=True))
        self.assertFalse(r["sandbox_recorded"]["passed"])
        self.assertIn("backend-engineer", r["sandbox_recorded"]["message"])

    def test_all_agents_clean_passes(self):
        r = self._by_check(self._state(agents=self.FULL, violations=[]))
        self.assertTrue(r["sandbox_recorded"]["passed"])
        self.assertTrue(r["sandbox_violations"]["passed"])

    def test_violations_fail_even_when_all_verified(self):
        r = self._by_check(self._state(
            agents=self.FULL,
            violations=[{"agent": "ui-builder", "kind": "OVERLAP", "path": "Demo/Services/X.swift"}],
        ))
        self.assertTrue(r["sandbox_recorded"]["passed"])
        self.assertFalse(r["sandbox_violations"]["passed"])


if __name__ == "__main__":
    unittest.main()
