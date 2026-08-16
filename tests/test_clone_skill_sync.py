from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clone_skill_sync.py"


class CloneSkillSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.cache = self.base / "cache"
        (self.repo / ".claude-plugin").mkdir(parents=True)
        (self.repo / "skills" / "autobot-clone-app").mkdir(parents=True)
        (self.repo / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"version": "1.2.3"}), encoding="utf-8"
        )
        self.source = self.repo / "skills" / "autobot-clone-app" / "SKILL.md"
        self.source.write_text("repo skill\n", encoding="utf-8")

    def run_sync(self, mode: str):
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                mode,
                "--repo",
                str(self.repo),
                "--cache-root",
                str(self.cache),
            ],
            text=True,
            capture_output=True,
        )

    def install(self, version: str, contents: str = "installed skill\n") -> Path:
        target = self.cache / version / "skills" / "autobot-clone-app" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(contents, encoding="utf-8")
        return target

    def add_script(self, root: Path, name: str, contents: str) -> Path:
        target = root / "scripts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        return target

    def test_check_rejects_when_matching_version_is_not_installed(self):
        self.install("1.2.2")
        result = self.run_sync("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("do not mix", result.stderr)
        self.assertIn("1.2.2", result.stderr)

    def test_check_reports_drift(self):
        self.install("1.2.3")
        result = self.run_sync("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clone skill drift", result.stderr)

    def test_sync_is_atomic_and_check_then_passes(self):
        target = self.install("1.2.3")
        synced = self.run_sync("sync")
        self.assertEqual(synced.returncode, 0, synced.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "repo skill\n")
        checked = self.run_sync("check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("matches installed plugin", checked.stdout)

    def test_sync_refuses_to_write_into_an_old_plugin_version(self):
        old = self.install("1.2.2")
        result = self.run_sync("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_text(encoding="utf-8"), "installed skill\n")
        self.assertIn("mixed-version", result.stderr)

    def test_sync_refuses_when_referenced_runtime_is_missing_or_stale(self):
        self.source.write_text("run scripts/device_wda.sh\n", encoding="utf-8")
        self.add_script(self.repo, "device_wda.sh", "new runtime\n")
        installed = self.install("1.2.3")

        missing = self.run_sync("sync")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("installed-missing:device_wda.sh", missing.stderr)
        self.assertEqual(installed.read_text(encoding="utf-8"), "installed skill\n")

        self.add_script(self.cache / "1.2.3", "device_wda.sh", "old runtime\n")
        stale = self.run_sync("sync")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("mismatch:device_wda.sh", stale.stderr)

    def test_sync_allows_skill_repair_when_referenced_runtime_matches(self):
        self.source.write_text("run scripts/device_wda.sh\n", encoding="utf-8")
        self.add_script(self.repo, "device_wda.sh", "same runtime\n")
        installed = self.install("1.2.3")
        self.add_script(self.cache / "1.2.3", "device_wda.sh", "same runtime\n")

        result = self.run_sync("sync")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(installed.read_text(encoding="utf-8"), self.source.read_text(encoding="utf-8"))


class CloneSkillContractTests(unittest.TestCase):
    def test_remote_xpc_auto_start_contract_matches_command_surface(self):
        skill = (ROOT / "skills" / "autobot-clone-app" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        command = (ROOT / "commands" / "clone.md").read_text(encoding="utf-8")

        for text in (skill, command):
            self.assertIn("CLONE_AUTO_START_TUNNEL=0", text)
            self.assertIn("대상 UDID", text)
            self.assertIn("Xcode", text)
        self.assertIn("macOS 표준 관리자 인증", skill)
        self.assertIn("remotexpc-tunnel.log", skill)


if __name__ == "__main__":
    unittest.main()
