"""Execute the documented SSOT wiring recipe against real local Git repos."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR


class TestSsotSubmoduleWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.ssot = self.project / "ssot"
        self.ssot.mkdir()
        self.remote = self.root / "blueprint.git"
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith("GIT_"):
                self.env.pop(key)
        self.env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="Audit",
            GIT_AUTHOR_EMAIL="audit@example.invalid",
            GIT_COMMITTER_NAME="Audit",
            GIT_COMMITTER_EMAIL="audit@example.invalid",
            GIT_TERMINAL_PROMPT="0",
        )
        self.git(self.project, "init", "-b", "main")
        self.git(self.project, "commit", "--allow-empty", "-m", "parent")
        self.git(self.root, "init", "--bare", "-b", "main", str(self.remote))
        self.git(self.ssot, "init", "-b", "main")
        (self.ssot / "README.md").write_text("confirmed blueprint\n")
        self.git(self.ssot, "add", "-A")
        self.git(self.ssot, "commit", "-m", "blueprint")
        self.git(self.ssot, "remote", "add", "origin", str(self.remote))
        self.git(self.ssot, "push", "-u", "origin", "HEAD")
        self.commit = self.git(self.ssot, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(
            self.git(self.ssot, "ls-remote", "origin", "HEAD").stdout.split()[0],
            self.commit,
        )

    def git(self, cwd, *args):
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=self.env,
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def wire(self):
        reference = PLUGIN_DIR / "skills/autobot-ssot/references/submodule-setup.md"
        match = re.search(
            r"## 5\.[\s\S]*?```bash\n(.*?)\n```",
            reference.read_text(encoding="utf-8"), re.DOTALL,
        )
        self.assertIsNotNone(match, "Missing executable SSOT wiring recipe")
        return subprocess.run(
            ["bash", "-c", match.group(1)], cwd=self.project, env=self.env,
            text=True, capture_output=True, timeout=15,
        )

    def allow_file_transport(self):
        # Isolate preservation assertions from the old recipe's transport bug.
        self.env.update(
            GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="protocol.file.allow",
            GIT_CONFIG_VALUE_0="always",
        )

    def test_existing_backup_is_preserved(self):
        self.allow_file_transport()
        backup = self.project / "ssot.tmp"
        backup.mkdir()
        notes = backup / "irreplaceable-notes.md"
        notes.write_text("existing user data\n")

        result = self.wire()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(notes.is_file(), "Existing backup was deleted")
        self.assertEqual(notes.read_text(), "existing user data\n")

    def test_local_bare_option_works_with_default_transport_policy(self):
        result = self.wire()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.ssot / ".git").is_file())
        self.assertEqual(self.git(self.ssot, "rev-parse", "HEAD").stdout.strip(), self.commit)
        self.assertTrue(self.git(self.project, "ls-files", "--stage", "ssot").stdout.startswith("160000 "))
        self.assertIn("path = ssot", (self.project / ".gitmodules").read_text())
        self.assertNotIn("protocol.file.allow", self.git(self.project, "config", "--local", "--list").stdout)

    def test_failed_registration_preserves_original_repository(self):
        blob = self.git(self.project, "hash-object", "-w", "ssot/README.md").stdout.strip()
        self.git(self.project, "update-index", "--add", "--cacheinfo", "100644", blob, "ssot/README.md")
        before_index = self.git(self.project, "ls-files", "--stage").stdout

        result = self.wire()

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.ssot / "README.md").is_file(), "Failed wiring lost the original")
        self.assertEqual((self.ssot / "README.md").read_text(), "confirmed blueprint\n")
        self.assertEqual(self.git(self.ssot, "rev-parse", "HEAD").stdout.strip(), self.commit)
        self.assertEqual(self.git(self.project, "ls-files", "--stage").stdout, before_index)

    def test_uncommitted_and_untracked_files_are_preserved(self):
        self.allow_file_transport()
        (self.ssot / "README.md").write_text("user's uncommitted edits\n")
        screenshot = self.ssot / "untracked.png"
        screenshot.write_bytes(b"user asset")

        result = self.wire()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.ssot / "README.md").read_text(), "user's uncommitted edits\n")
        self.assertEqual(screenshot.read_bytes(), b"user asset")


if __name__ == "__main__":
    unittest.main()
