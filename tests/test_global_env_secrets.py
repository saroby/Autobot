"""Global secrets .env — set-once via /autobot:setup, read by the deploy path.

Two layers:
1. config.sh set-env / get-env / env-path — the SSOT writer for ~/.autobot/.env
   (KEY='value', chmod 600, upsert, single-quote escaping).
2. The deploy scripts (register-app.sh) load .env WITHOUT clobbering already-set
   vars, with precedence: inherited env > project ./.env > global ~/.autobot/.env.

Both are exercised through bash + python3 only (no network); register-app.sh
--dry-run validates credentials + .p8 readability but never invokes fastlane,
so .p8 *path* precedence is observable via the exit/validation outcome.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
CONFIG_SH = PLUGIN_DIR / "skills" / "autobot-setup" / "scripts" / "config.sh"
REGISTER_SH = PLUGIN_DIR / "skills" / "autobot-register-app" / "scripts" / "register-app.sh"


def config(args, *, config_dir=None, env_file=None):
    env = os.environ.copy()
    if config_dir is not None:
        env["AUTOBOT_CONFIG_DIR"] = str(config_dir)
    if env_file is not None:
        env["AUTOBOT_ENV_FILE"] = str(env_file)
    return subprocess.run(
        ["bash", str(CONFIG_SH), *args], env=env, capture_output=True, text=True
    )


class ConfigSetEnvTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _set(self, k, v):
        r = config(["set-env", k, v], config_dir=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)

    def _get(self, k):
        return config(["get-env", k], config_dir=self.dir)

    def test_round_trip(self):
        self._set("ASC_API_KEY_ID", "ABC123XYZ0")
        r = self._get("ASC_API_KEY_ID")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "ABC123XYZ0")

    def test_single_quote_in_value_round_trips(self):
        self._set("ASC_API_ISSUER_ID", "iss'uer-x")
        r = self._get("ASC_API_ISSUER_ID")
        self.assertEqual(r.stdout.strip(), "iss'uer-x")

    def test_tilde_path_preserved_unexpanded(self):
        self._set("ASC_API_KEY_PATH", "~/.appstoreconnect/AuthKey_X.p8")
        r = self._get("ASC_API_KEY_PATH")
        self.assertEqual(r.stdout.strip(), "~/.appstoreconnect/AuthKey_X.p8")

    def test_upsert_keeps_single_line(self):
        self._set("ASC_API_KEY_ID", "FIRST00000")
        self._set("ASC_API_KEY_ID", "SECOND1111")
        env_path = self.dir / ".env"
        lines = [ln for ln in env_path.read_text().splitlines() if ln.startswith("ASC_API_KEY_ID=")]
        self.assertEqual(len(lines), 1, f"expected one line, got {lines}")
        self.assertEqual(self._get("ASC_API_KEY_ID").stdout.strip(), "SECOND1111")

    def test_file_is_chmod_600(self):
        self._set("ASC_API_KEY_ID", "X000000000")
        mode = stat.S_IMODE((self.dir / ".env").stat().st_mode)
        self.assertEqual(mode, 0o600, f"expected 600, got {oct(mode)}")

    def test_lines_are_sourceable_and_grep_detectable(self):
        # KEY='value' (no `export`) so `set -a; . file` exports AND load-learnings'
        # `^KEY=` detection matches.
        self._set("ASC_API_KEY_ID", "DETECT0000")
        env_path = self.dir / ".env"
        probe = subprocess.run(
            ["bash", "-c", f'set -a; . "{env_path}"; set +a; printf "%s" "$ASC_API_KEY_ID"'],
            capture_output=True, text=True,
        )
        self.assertEqual(probe.stdout, "DETECT0000")
        grep = subprocess.run(["grep", "-Eq", "^[[:space:]]*ASC_API_KEY_ID=", str(env_path)])
        self.assertEqual(grep.returncode, 0, "load-learnings ^KEY= detection must match")

    def test_invalid_key_rejected(self):
        r = config(["set-env", "bad key!", "x"], config_dir=self.dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid env key", r.stderr)

    def test_missing_key_exits_1(self):
        r = self._get("NEVER_SET")
        self.assertEqual(r.returncode, 1)

    def test_env_path_points_into_config_dir(self):
        r = config(["env-path"], config_dir=self.dir)
        self.assertEqual(r.stdout.strip(), str(self.dir / ".env"))


@unittest.skipUnless(REGISTER_SH.is_file(), "register-app.sh missing")
class DeployEnvPrecedenceTests(unittest.TestCase):
    """register-app.sh --dry-run: precedence env > project .env > global .env.

    Probe: seed FASTLANE_USER with a different value per layer. The dry-run
    output prints the resolved `--username <value>`, directly exposing which
    layer won. (The old probe — readable vs unreadable .p8 — died with the
    ASC-key requirement: app registration now authenticates via Apple ID web
    session, not the API key.)
    """

    def _run(self, workdir, gdir, env_extra=None):
        env = os.environ.copy()
        for k in ("FASTLANE_USER", "APPLE_ID", "FASTLANE_SESSION"):
            env.pop(k, None)
        env["AUTOBOT_CONFIG_DIR"] = str(gdir)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", str(REGISTER_SH), "--bundle-id", "com.axi.t",
             "--display-name", "Test", "--team-id", "A1B2C3D4E5", "--dry-run"],
            cwd=str(workdir), env=env, capture_output=True, text=True,
        )

    def _assert_username(self, r, expected):
        self.assertIn("dry-run validation passed", r.stdout, r.stdout + r.stderr)
        self.assertIn(f"--username {expected}", r.stdout, r.stdout)

    def test_global_env_alone_is_used(self):
        with tempfile.TemporaryDirectory() as g, tempfile.TemporaryDirectory() as w:
            g, w = Path(g), Path(w)
            config(["set-env", "FASTLANE_USER", "global@example.com"], config_dir=g)
            r = self._run(w, g)
            self._assert_username(r, "global@example.com")

    def test_inherited_env_beats_global(self):
        with tempfile.TemporaryDirectory() as g, tempfile.TemporaryDirectory() as w:
            g, w = Path(g), Path(w)
            config(["set-env", "FASTLANE_USER", "global@example.com"], config_dir=g)
            r = self._run(w, g, env_extra={"FASTLANE_USER": "env@example.com"})
            self._assert_username(r, "env@example.com")

    def test_export_form_project_env_is_loaded(self):
        # signing-guide.md tells users to write `export KEY=...`. A hand-written
        # project .env in that form must still be picked up (regression: the
        # loader strips a leading `export ` before extracting the key).
        with tempfile.TemporaryDirectory() as g, tempfile.TemporaryDirectory() as w:
            g, w = Path(g), Path(w)
            (w / ".env").write_text(
                "# project creds\n"
                'export FASTLANE_USER="proj@example.com"\n'
            )
            r = self._run(w, g)  # global config dir empty → only project .env supplies the Apple ID
            self._assert_username(r, "proj@example.com")

    def test_project_env_beats_global(self):
        with tempfile.TemporaryDirectory() as g, tempfile.TemporaryDirectory() as w:
            g, w = Path(g), Path(w)
            config(["set-env", "FASTLANE_USER", "global@example.com"], config_dir=g)
            # Project ./.env (written via AUTOBOT_ENV_FILE override) wins over global.
            config(["set-env", "FASTLANE_USER", "proj@example.com"], env_file=w / ".env")
            r = self._run(w, g)
            self._assert_username(r, "proj@example.com")


if __name__ == "__main__":
    unittest.main()
