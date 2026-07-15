from __future__ import annotations

import os
import subprocess
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
                'ASC_API_KEY_PATH="$HOME/.keys/AuthKey.p8"\n'
                f'EVIL="$(touch {marker})"\n'
                f'BASH_ENV="{marker}"\n',
                encoding="utf-8",
            )
            command = (
                f'. "{PLUGIN_DIR / "scripts" / "release_env.sh"}"; '
                f'autobot_load_release_env "{project}"; '
                'printf "%s\\n%s" "$ASC_API_KEY_PATH" "$EVIL"'
            )
            env = os.environ.copy()
            env["AUTOBOT_CONFIG_DIR"] = str(config)
            env.pop("ASC_API_KEY_PATH", None)
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
        self.assertEqual(parsed["ASC_API_KEY_PATH"], lines[0])
        self.assertNotIn("EVIL", parsed)
        self.assertNotIn("BASH_ENV", parsed)


if __name__ == "__main__":
    unittest.main()
