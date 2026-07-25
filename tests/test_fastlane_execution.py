"""Execution tests for the deliver-based ASC integration scripts:
upload-metadata.sh, upload-screenshots.sh, submit-for-review.sh.

Weakness audit finding: these three scripts (skills/autobot-upload-metadata,
skills/autobot-app-review) were only ever covered by source-substring tests
(test_fastlane_api_key_json.py) — never actually executed. A quoting
regression in the `--api_key_path` JSON heredoc (e.g. `key='$ASC_API_KEY_CONTENT'`
instead of the real embed) would pass every substring assertion while
breaking every real `fastlane deliver` call.

Pattern: combine two patterns already proven elsewhere in this suite —
  - tests/test_release_artifact_scripts.py's _make_executable + PATH-stub
    trick, applied here to a fake `fastlane` that dumps its argv to JSON and
    copies whatever file `--api_key_path` points at out of the doomed
    mktemp workdir (the real script rm -rf's it on exit).
  - tests/test_invite_emails.py's AUTOBOT_CONFIG_DIR sandbox + fake .p8, so
    these tests never source a real ~/.autobot/.env or touch the network.

Each script's own `command -v fastlane` gate (upload-metadata.sh:182,
upload-screenshots.sh:178, submit-for-review.sh:212) sees the stub and skips
the brew-install branch entirely, so the full script runs to completion with
no real fastlane involved. submit-for-review.sh's build-processing poll is
bypassed with --skip-wait (a real flag, not a test-only shim) so only the
final `fastlane deliver` call happens.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR

FAKE_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "not-a-real-key-but-has-content-to-prove-shell-expansion\n"
    "-----END PRIVATE KEY-----\n"
)


def _make_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_fastlane_stub(path: Path) -> None:
    # Records argv (for flag assertions) and — if --api_key_path is present —
    # copies that file out before the real script's `trap cleanup EXIT`
    # rm -rf's its mktemp workdir out from under us.
    body = f'''#!{sys.executable}
import json, os, shutil, sys
argv = sys.argv[1:]
dump = os.environ.get("FASTLANE_STUB_ARGV_DUMP")
if dump:
    with open(dump, "w", encoding="utf-8") as f:
        json.dump(argv, f)
if "--api_key_path" in argv:
    key_path = argv[argv.index("--api_key_path") + 1]
    copy_to = os.environ.get("FASTLANE_STUB_KEY_COPY")
    if copy_to:
        shutil.copy(key_path, copy_to)
output = os.environ.get("FASTLANE_STUB_OUTPUT", "STUB_FASTLANE_OK")
if output:
    print(output)
sys.exit(int(os.environ.get("FASTLANE_STUB_EXIT", "0")))
'''
    _make_executable(path, body)


class _FastlaneScriptCase(unittest.TestCase):
    """Shared sandbox: fake fastlane on PATH, fake .p8, isolated config dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="autobot-fastlane-exec.")
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        _make_fastlane_stub(self.bin_dir / "fastlane")

        self.fake_key = self.root / "AuthKey_FAKE.p8"
        self.fake_key.write_text(FAKE_PEM)

        self.argv_dump = self.root / "fastlane-argv.json"
        self.key_copy = self.root / "api-key-copy.json"

        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{self.bin_dir}:{self.env['PATH']}",
            "AUTOBOT_CONFIG_DIR": str(self.root / "autobot-config"),
            "CLAUDE_PROJECT_DIR": str(self.root),
            "APP_STORE_CONNECT_API_KEY_KEY_ID": "FAKEKEY000",
            "APP_STORE_CONNECT_API_KEY_ISSUER_ID": "fake-issuer",
            "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH": str(self.fake_key),
            "FASTLANE_STUB_ARGV_DUMP": str(self.argv_dump),
            "FASTLANE_STUB_KEY_COPY": str(self.key_copy),
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _argv(self) -> list[str]:
        return json.loads(self.argv_dump.read_text())

    def _assert_key_json_expanded(self) -> None:
        # Proves the shell actually expanded APP_STORE_CONNECT_API_KEY_KEY_FILEPATH and the
        # script's python embed read the real file — not a literal
        # '$ASC_API_KEY_CONTENT' or similar quoting regression.
        data = json.loads(self.key_copy.read_text())
        self.assertEqual(data["key"], FAKE_PEM)
        self.assertEqual(data["key_id"], "FAKEKEY000")
        self.assertEqual(data["issuer_id"], "fake-issuer")


class TestUploadMetadataScript(_FastlaneScriptCase):
    SCRIPT = PLUGIN_DIR / "skills/autobot-upload-metadata/scripts/upload-metadata.sh"

    def _write_metadata(self) -> Path:
        metadata = self.root / "fastlane" / "metadata"
        (metadata / "en-US").mkdir(parents=True)
        (metadata / "en-US" / "name.txt").write_text("Demo App")
        return metadata

    def test_deliver_invocation_and_key_expansion(self):
        metadata = self._write_metadata()
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--metadata-path", str(metadata)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv = self._argv()
        self.assertIn("--skip_binary_upload", argv)
        self.assertIn("--skip_screenshots", argv)
        self.assertIn("--skip_app_version_update", argv)
        self.assertIn("--force", argv)
        precheck_idx = argv.index("--precheck_include_in_app_purchases")
        self.assertEqual(argv[precheck_idx + 1], "false")
        self.assertIn("--app_identifier", argv)
        self.assertEqual(argv[argv.index("--app_identifier") + 1], "com.example.demo")
        self.assertIn("--api_key_path", argv)
        self._assert_key_json_expanded()

    def test_dry_run_does_not_invoke_fastlane(self):
        metadata = self._write_metadata()
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--metadata-path", str(metadata), "--dry-run"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run validation passed", result.stdout)
        self.assertFalse(self.argv_dump.exists(), "dry-run must not call fastlane")

    def test_first_version_workaround_does_not_skip_age_rating(self):
        metadata = self._write_metadata()
        (metadata / "app_store_rating_config.json").write_text("{}")
        status_path = self.root / "metadata-status.json"
        self.env.update({
            "AUTOBOT_METADATA_UPLOAD_STATUS_FILE": str(status_path),
            "FASTLANE_STUB_EXIT": "1",
            "FASTLANE_STUB_OUTPUT": (
                "Uploading metadata to App Store Connect for localized version 'en-US'\n"
                "No data\n"
                "fetch_app_store_review_detail"
            ),
        })

        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--metadata-path", str(metadata)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )

        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        status = json.loads(status_path.read_text())
        self.assertEqual(status["result"], "failed")
        self.assertNotEqual(status["reason"], "first_version_review_detail_bug")

    def test_first_version_workaround_requires_and_accepts_age_rating(self):
        metadata = self._write_metadata()
        (metadata / "app_store_rating_config.json").write_text("{}")
        status_path = self.root / "metadata-status.json"
        self.env.update({
            "AUTOBOT_METADATA_UPLOAD_STATUS_FILE": str(status_path),
            "FASTLANE_STUB_EXIT": "1",
            "FASTLANE_STUB_OUTPUT": (
                "Uploading metadata to App Store Connect for localized version 'en-US'\n"
                "Setting the app's age rating...\n"
                "No data\n"
                "fetch_app_store_review_detail"
            ),
        })

        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--metadata-path", str(metadata)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        status = json.loads(status_path.read_text())
        self.assertEqual(status["result"], "uploaded")
        self.assertEqual(status["reason"], "first_version_review_detail_bug")


class TestUploadScreenshotsScript(_FastlaneScriptCase):
    SCRIPT = PLUGIN_DIR / "skills/autobot-app-review/scripts/upload-screenshots.sh"

    def _write_screenshots(self) -> Path:
        shots = self.root / "fastlane" / "screenshots"
        (shots / "en-US").mkdir(parents=True)
        (shots / "en-US" / "01_hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return shots

    def test_deliver_invocation_and_key_expansion(self):
        shots = self._write_screenshots()
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--screenshots-path", str(shots)],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv = self._argv()
        self.assertIn("--skip_binary_upload", argv)
        self.assertIn("--skip_metadata", argv)
        self.assertIn("--skip_app_version_update", argv)
        self.assertIn("--force", argv)
        self.assertIn("--overwrite_screenshots", argv)  # default OVERWRITE=1
        self.assertIn("--screenshots_path", argv)
        self.assertEqual(argv[argv.index("--screenshots_path") + 1], str(shots))
        self.assertIn("--api_key_path", argv)
        self._assert_key_json_expanded()

    def test_dry_run_does_not_invoke_fastlane(self):
        shots = self._write_screenshots()
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo",
             "--screenshots-path", str(shots), "--dry-run"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run validation passed", result.stdout)
        self.assertFalse(self.argv_dump.exists(), "dry-run must not call fastlane")


class TestSubmitForReviewScript(_FastlaneScriptCase):
    SCRIPT = PLUGIN_DIR / "skills/autobot-app-review/scripts/submit-for-review.sh"

    def test_deliver_invocation_and_key_expansion(self):
        # --skip-wait bypasses the `fastlane pilot builds` polling phase (real
        # flag, documented in the script's own usage text) so the stub is
        # only asked to stand in for the final `fastlane deliver` call.
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo", "--skip-wait"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv = self._argv()
        self.assertIn("--skip_binary_upload", argv)
        self.assertIn("--skip_metadata", argv)
        self.assertIn("--skip_screenshots", argv)
        self.assertIn("--skip_app_version_update", argv)
        self.assertIn("--force", argv)
        self.assertIn("--submit_for_review", argv)
        self.assertIn("--submission_information", argv)
        # AUTOMATIC_RELEASE defaults to 1 -> "--automatic_release true" appended
        # unquoted, so bash word-splits it into two argv entries.
        self.assertIn("--automatic_release", argv)
        self.assertEqual(argv[argv.index("--automatic_release") + 1], "true")
        precheck_idx = argv.index("--precheck_include_in_app_purchases")
        self.assertEqual(argv[precheck_idx + 1], "false")
        self.assertIn("--api_key_path", argv)
        self._assert_key_json_expanded()

    def test_dry_run_does_not_invoke_fastlane(self):
        result = subprocess.run(
            ["bash", str(self.SCRIPT), "--bundle-id", "com.example.demo", "--dry-run"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run validation passed", result.stdout)
        self.assertFalse(self.argv_dump.exists(), "dry-run must not call fastlane")


if __name__ == "__main__":
    unittest.main()
