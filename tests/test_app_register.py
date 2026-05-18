"""Regression tests for skills/autobot-register-app/scripts/register-app.sh.

These tests never touch the network — they only exercise input validation,
JSON injection defense, and the --dry-run path. All require python3 + bash
(both already hard deps for the test suite).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_DIR / "skills" / "autobot-register-app" / "scripts" / "register-app.sh"


def run(args, env_extra=None, strip_creds=False):
    env = os.environ.copy()
    if strip_creds:
        for k in ("ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_KEY_PATH"):
            env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
    )


class InputValidationTests(unittest.TestCase):
    def test_invalid_bundle_id_exits_1(self):
        r = run(["--bundle-id", "NoDots", "--display-name", "Ok"], strip_creds=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR: bundle ID", r.stderr)

    def test_bundle_id_prefix_lowercased_last_segment_preserved(self):
        # Prefix segments are forced lowercase; the LAST segment preserves the
        # caller's case so PascalCase app names round-trip. Verified via the
        # --dry-run status JSON.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            key = tmp / "fake.p8"
            key.write_text("not-a-real-key")
            status = tmp / "status.json"
            env = {
                "ASC_API_KEY_ID": "K",
                "ASC_API_ISSUER_ID": "I",
                "ASC_API_KEY_PATH": str(key),
                "AUTOBOT_REGISTER_STATUS_FILE": str(status),
                "PATH": "/usr/bin:/bin",
            }
            r = run(
                [
                    "--bundle-id",
                    "Com.AXI.MyApp",
                    "--display-name",
                    "Ok",
                    "--dry-run",
                ],
                env_extra=env,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = json.loads(status.read_text())
            self.assertEqual(data["bundle_id"], "com.axi.MyApp")

    def test_bundle_id_without_dot_rejected(self):
        # No dot means there is no separable last segment; must fail validation.
        r = run(
            ["--bundle-id", "NoDots", "--display-name", "Ok"],
            strip_creds=True,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR: bundle ID", r.stderr)

    def test_display_name_too_short(self):
        r = run(["--bundle-id", "com.axi.x", "--display-name", "a"], strip_creds=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("out of range", r.stderr)

    def test_display_name_too_long(self):
        r = run(
            ["--bundle-id", "com.axi.x", "--display-name", "x" * 31],
            strip_creds=True,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("out of range", r.stderr)

    def test_korean_display_name_counted_as_chars(self):
        # "앱이름" is 3 chars but 9 bytes — must NOT be byte-counted.
        # Force C locale to expose any bash ${#var} regressions.
        env = {"LC_ALL": "C", "LANG": "C"}
        r = run(
            ["--bundle-id", "com.axi.x", "--display-name", "앱이름"],
            env_extra=env,
            strip_creds=True,
        )
        # Should pass length validation and fail later on missing creds (exit 2)
        self.assertEqual(r.returncode, 2, msg=r.stderr)

    def test_invalid_team_id_format(self):
        r = run(
            ["--bundle-id", "com.axi.x", "--display-name", "Ok", "--team-id", "short"],
            strip_creds=True,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("team ID", r.stderr)

    def test_invalid_sku_with_space(self):
        env = {
            "ASC_API_KEY_ID": "x",
            "ASC_API_ISSUER_ID": "y",
            "ASC_API_KEY_PATH": "/dev/null",
        }
        r = run(
            ["--bundle-id", "com.axi.x", "--display-name", "Ok", "--sku", "has space"],
            env_extra=env,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("SKU", r.stderr)

    def test_invalid_language_code(self):
        env = {
            "ASC_API_KEY_ID": "x",
            "ASC_API_ISSUER_ID": "y",
            "ASC_API_KEY_PATH": "/dev/null",
        }
        r = run(
            [
                "--bundle-id",
                "com.axi.x",
                "--display-name",
                "Ok",
                "--language",
                "not-a-code",
            ],
            env_extra=env,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("language code", r.stderr)

    def test_invalid_app_version(self):
        env = {
            "ASC_API_KEY_ID": "x",
            "ASC_API_ISSUER_ID": "y",
            "ASC_API_KEY_PATH": "/dev/null",
        }
        r = run(
            [
                "--bundle-id",
                "com.axi.x",
                "--display-name",
                "Ok",
                "--app-version",
                "1.0-beta",
            ],
            env_extra=env,
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("app version", r.stderr)

    def test_missing_flag_value(self):
        r = run(["--bundle-id"], strip_creds=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a value", r.stderr)

    def test_flag_followed_by_another_flag(self):
        r = run(["--bundle-id", "--display-name", "Ok"], strip_creds=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a value", r.stderr)


class CredentialsAndDryRunTests(unittest.TestCase):
    def test_missing_credentials_exits_2(self):
        r = run(["--bundle-id", "com.axi.x", "--display-name", "Ok"], strip_creds=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing ASC API credentials", r.stderr)

    def test_unreadable_key_path_exits_2(self):
        env = {
            "ASC_API_KEY_ID": "x",
            "ASC_API_ISSUER_ID": "y",
            "ASC_API_KEY_PATH": "/nonexistent/path.p8",
        }
        r = run(
            ["--bundle-id", "com.axi.x", "--display-name", "Ok"], env_extra=env
        )
        self.assertEqual(r.returncode, 2)
        self.assertIn("not readable", r.stderr)

    def test_dry_run_does_not_call_fastlane(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            key = tmp / "fake.p8"
            key.write_text("not-a-real-key")
            status = tmp / "status.json"
            env = {
                "ASC_API_KEY_ID": "K",
                "ASC_API_ISSUER_ID": "I",
                "ASC_API_KEY_PATH": str(key),
                "AUTOBOT_REGISTER_STATUS_FILE": str(status),
                # Ensure fastlane is NOT found — proves we never tried to call it.
                "PATH": "/usr/bin:/bin",
            }
            r = run(
                [
                    "--bundle-id",
                    "com.axi.testapp",
                    "--display-name",
                    "테스트 앱",
                    "--team-id",
                    "A1B2C3D4E5",
                    "--dry-run",
                ],
                env_extra=env,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("DRY RUN", r.stdout)
            self.assertTrue(status.is_file())
            data = json.loads(status.read_text())
            self.assertEqual(data["result"], "dry_run")
            self.assertEqual(data["display_name"], "테스트 앱")
            self.assertEqual(data["team_id"], "A1B2C3D4E5")


class JsonInjectionDefenseTests(unittest.TestCase):
    def test_hostile_strings_do_not_corrupt_status_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            key = tmp / "fake.p8"
            key.write_text("not-a-real-key")
            status = tmp / "status.json"
            hostile_name = 'evil","admin":true,"x'  # would inject a field if naive
            env = {
                "ASC_API_KEY_ID": "K",
                "ASC_API_ISSUER_ID": "I",
                "ASC_API_KEY_PATH": str(key),
                "AUTOBOT_REGISTER_STATUS_FILE": str(status),
                "PATH": "/usr/bin:/bin",
            }
            # display name max 30 chars — the hostile string is under that
            r = run(
                [
                    "--bundle-id",
                    "com.axi.x",
                    "--display-name",
                    hostile_name,
                    "--dry-run",
                ],
                env_extra=env,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = json.loads(status.read_text())
            self.assertEqual(data["display_name"], hostile_name)
            self.assertNotIn("admin", data)


if __name__ == "__main__":
    unittest.main()
