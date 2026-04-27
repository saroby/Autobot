"""Shared fixtures and helpers for the regression suite.

These tests use only the Python stdlib (unittest) — no pytest dependency. Each
test module subclasses unittest.TestCase and uses build_fresh_project() to
spin up an isolated build directory under tmp_path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_DIR / "scripts"


def import_runtime_modules():
    """Insert SCRIPTS_DIR into sys.path so test modules can import runtime."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def run_pipeline(*args, project_dir: Path, **kwargs) -> subprocess.CompletedProcess:
    """Execute pipeline.sh in a project directory.

    Inherits the current process environment so the same python interpreter
    that ran the test is used by the subprocess (avoids picking up an older
    system python via /usr/bin first).
    """
    cmd = ["bash", str(SCRIPTS_DIR / "pipeline.sh"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, **kwargs)


def run_runtime(*args, project_dir: Path) -> subprocess.CompletedProcess:
    cmd = ["python3", str(SCRIPTS_DIR / "runtime.py"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)


def run_sandbox(*args, project_dir: Path) -> subprocess.CompletedProcess:
    cmd = ["bash", str(SCRIPTS_DIR / "agent-sandbox.sh"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)


def run_build_log(*args, project_dir: Path) -> subprocess.CompletedProcess:
    cmd = ["bash", str(SCRIPTS_DIR / "build-log.sh"), *args]
    return subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)


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
            "--xcodegen", "true", "--fastlane", "false",
            "--ascConfigured", "false", "--axiom", "false", "--stitch", "false",
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
