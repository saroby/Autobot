"""Shared fixtures and helpers for the regression suite.

These tests use only the Python stdlib (unittest) — no pytest dependency. Each
test module subclasses unittest.TestCase and uses build_fresh_project() to
spin up an isolated build directory under tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_DIR / "scripts"

# ── Global learning-store isolation (suite-wide, import-time) ──
# learning_impact.grade_build() publishes to the host-wide store under
# XDG_CONFIG_HOME (or ~/.config). Tests must NEVER touch the developer's real
# store — that is exactly how fixtures ("good rule", "always pin the sdk")
# leaked into ~/.config/autobot/learnings.json. unittest has no pytest-style
# autouse fixtures, so conftest import time is the earliest hook shared by
# every test module (they all `from conftest import ...`). _scoped_env() copies
# os.environ, so subprocess-driven tests inherit the isolation too.
# Defense line 2: tests/run_tests.sh exports the same vars for the discover
# entrypoint, and grade_build honors AUTOBOT_NO_GLOBAL_PUBLISH directly.
if not os.environ.get("AUTOBOT_TEST_XDG_ISOLATED"):
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="autobot-tests-xdg-")
    os.environ["AUTOBOT_TEST_XDG_ISOLATED"] = "1"
os.environ.setdefault("AUTOBOT_NO_GLOBAL_PUBLISH", "1")


def import_runtime_modules():
    """Insert SCRIPTS_DIR into sys.path so test modules can import runtime."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def _scoped_env(project_dir: Path, extra: dict | None = None) -> dict:
    """Return an env that pins CLAUDE_PROJECT_DIR/AUTOBOT_* to the temp project.

    pipeline.sh resolves PROJECT_DIR from CLAUDE_PROJECT_DIR. If the harness
    that runs the tests (e.g. Claude Code) sets it to the real Autobot repo,
    every subprocess would write into the real .autobot/ — leaking state
    across tests and clobbering the developer's working tree. Pin the env
    explicitly so cwd= and the env agree.
    """
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    # Unit tests must not require Xcode/iOS simulator. Gate 0 (environment_ready)
    # and the Phase 5 build/runtime paths honor these to degrade-skip hardware
    # probes (gate_checks/setup.py, sim_runtime.py, xcodebuild_runner.py). Keeps
    # the suite hermetic across mac/Linux and green on no-Xcode CI (ubuntu-latest).
    # A test that needs the live probe can override via `extra`.
    env["AUTOBOT_DISABLE_SIMULATOR"] = "1"
    env["AUTOBOT_DISABLE_XCODEBUILD"] = "1"
    env.pop("AUTOBOT_ACTIVE_AGENT", None)
    env.pop("AUTOBOT_APP_NAME", None)
    if extra:
        env.update(extra)
    return env


def run_pipeline(*args, project_dir: Path, env: dict | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Execute pipeline.sh in a project directory.

    Inherits the current process environment so the same python interpreter
    that ran the test is used by the subprocess (avoids picking up an older
    system python via /usr/bin first), but rebinds CLAUDE_PROJECT_DIR to the
    temp project so harness-injected values don't leak.
    """
    cmd = ["bash", str(SCRIPTS_DIR / "pipeline.sh"), *args]
    kwargs.setdefault("env", _scoped_env(project_dir, env))
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, **kwargs)


def run_runtime(*args, project_dir: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["python3", str(SCRIPTS_DIR / "runtime.py"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, env=_scoped_env(project_dir, env))


def run_sandbox(*args, project_dir: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(SCRIPTS_DIR / "agent-sandbox.sh"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, env=_scoped_env(project_dir, env))


def run_build_log(*args, project_dir: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(SCRIPTS_DIR / "build-log.sh"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, env=_scoped_env(project_dir, env))


class IsolatedProjectCase(unittest.TestCase):
    """Create a temp dir, run init-build, and tear it down per-test."""

    APP_NAME = "TestApp"
    DISPLAY_NAME = "Test"
    BUILD_ID = "build-test"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name)
        result = run_pipeline(
            "init-build",
            "--build-id", self.BUILD_ID,
            "--app-name", self.APP_NAME,
            "--display-name", self.DISPLAY_NAME,
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        result = run_pipeline(
            "record-environment",
            "--xcodegen", "true",
            "--fastlane", "false",
            "--ascConfigured", "false",
            "--axiom", "false",
            "--stitch", "false",
            "--runtimeHost", "codex",
            "--peerAi", "claude",
            "--peerReviewAvailable", "false",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        result = run_pipeline("start-phase", "--phase", "0", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        result = run_pipeline("advance-phase", "--phase", "0", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ── helpers ──

    def state(self) -> dict:
        return json.loads((self.project_dir / ".autobot" / "build-state.json").read_text())

    def log_lines(self) -> list[dict]:
        log = self.project_dir / ".autobot" / "build-log.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
