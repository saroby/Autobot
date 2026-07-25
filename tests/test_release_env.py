from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR, import_runtime_modules

import_runtime_modules()

from release_environment import load_release_environment  # noqa: E402


class TestReleaseEnvironment(unittest.TestCase):
    def test_loader_expands_home_without_evaluating_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            config = root / "config"
            project.mkdir()
            config.mkdir()
            marker = root / "executed"
            (project / ".env").write_text(
                'APP_STORE_CONNECT_API_KEY_KEY_FILEPATH="$HOME/.keys/AuthKey.p8"\n'
                f'EVIL="$(touch {marker})"\n'
                f'BASH_ENV="{marker}"\n',
                encoding="utf-8",
            )
            command = (
                f'. "{PLUGIN_DIR / "scripts" / "release_env.sh"}"; '
                f'autobot_load_release_env "{project}"; '
                'printf "%s\\n%s" "$APP_STORE_CONNECT_API_KEY_KEY_FILEPATH" "$EVIL"'
            )
            env = os.environ.copy()
            env["AUTOBOT_CONFIG_DIR"] = str(config)
            env.pop("APP_STORE_CONNECT_API_KEY_KEY_FILEPATH", None)
            env.pop("EVIL", None)
            result = subprocess.run(
                ["bash", "-c", command], env=env, capture_output=True, text=True,
            )
            parsed = load_release_environment(project, env)

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f"{env['HOME']}/.keys/AuthKey.p8")
        self.assertEqual(len(lines), 1)
        self.assertFalse(marker.exists())
        self.assertEqual(parsed["APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"], lines[0])
        self.assertNotIn("EVIL", parsed)
        self.assertNotIn("BASH_ENV", parsed)

    def test_lines_format_masks_fastlane_session_nul_keeps_raw(self):
        # `lines` is the human/LLM diagnostic format — the ~30-day ASC web
        # session cookie must never land in transcripts. `nul` feeds
        # release_env.sh and must stay raw.
        cookie = "COOKIE-SECRET-VALUE"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            config = root / "config"
            project.mkdir()
            config.mkdir()
            (project / ".env").write_text(f'FASTLANE_SESSION="{cookie}"\n', encoding="utf-8")
            env = os.environ.copy()
            env["AUTOBOT_CONFIG_DIR"] = str(config)
            env.pop("FASTLANE_SESSION", None)
            script = PLUGIN_DIR / "scripts" / "release_environment.py"
            lines_run = subprocess.run(
                [sys.executable, str(script), "--project-dir", str(project), "--format", "lines"],
                env=env, capture_output=True, text=True,
            )
            nul_run = subprocess.run(
                [sys.executable, str(script), "--project-dir", str(project), "--format", "nul"],
                env=env, capture_output=True,
            )
        self.assertEqual(lines_run.returncode, 0, lines_run.stderr)
        self.assertNotIn(cookie, lines_run.stdout)
        self.assertIn("FASTLANE_SESSION=***", lines_run.stdout)
        self.assertIn(cookie.encode(), nul_run.stdout)


if __name__ == "__main__":
    unittest.main()
