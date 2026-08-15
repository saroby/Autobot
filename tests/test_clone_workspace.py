"""Clone workspace preparation — generate the Xcode shell without launching it."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_workspace.sh"


class TestCloneWorkspace(unittest.TestCase):
    def test_prepare_is_idempotent_and_creates_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "clone-project"
            env = {**os.environ, "CLONE_WORKSPACE_DIR": str(project_dir)}
            first = subprocess.run(
                ["bash", str(SCRIPT), "prepare"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(first.returncode, 0, msg=first.stderr)
            project = project_dir / "CloneWorkspace.xcodeproj"
            self.assertTrue(project.is_dir())

            marker = project / "project.pbxproj"
            before = marker.stat().st_mtime_ns
            second = subprocess.run(
                ["bash", str(SCRIPT), "prepare"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(second.returncode, 0, msg=second.stderr)
            self.assertEqual(before, marker.stat().st_mtime_ns)
            self.assertIn("OK: clone Xcode workspace", second.stdout)


if __name__ == "__main__":
    unittest.main()
