"""check-review-status.sh — post-submission verdict retrieval contract.

The pipeline ends at Phase G ("Waiting for Review"); this on-demand script
closes the verdict feedback gap by fetching appStoreVersions/reviewSubmissions
state via the ASC API into .autobot/review-verdict.json. It is deliberately
NOT a controller phase (verdicts arrive hours~days after submit).

Hermetic coverage: the dry-run path exercises everything up to the network
boundary (arg parsing, release_env load, credential checks, real ES256 JWT
signing over a locally generated P-256 key). The verdict JSON schema is pinned
as a source contract — the cross-agent consumers key on these exact fields.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR

SCRIPT = PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "check-review-status.sh"

VERDICT_SCHEMA_KEYS = (
    '"fetchedAt"',
    '"appVersionState"',
    '"reviewSubmissionState"',
    '"guidelineNumbers"',
    '"notes"',
)


class TestCheckReviewStatusContract(unittest.TestCase):
    def test_script_exists_and_is_not_a_controller_phase(self):
        self.assertTrue(SCRIPT.is_file())
        controller = (PLUGIN_DIR / "scripts" / "app_review_controller.py").read_text()
        # Verdicts arrive asynchronously — PHASE_ORDER must stay G-terminal.
        self.assertNotIn("check-review-status", controller)
        self.assertIn('PHASE_ORDER = ("0", "0b", "A", "B", "C", "D1", "D2", "H", "E", "F", "G")', controller)

    def test_script_emits_cross_agent_verdict_schema(self):
        src = SCRIPT.read_text()
        for key in VERDICT_SCHEMA_KEYS:
            self.assertIn(key, src, f"verdict schema key {key} missing")
        self.assertIn(".autobot/review-verdict.json", src)

    @unittest.skipUnless(shutil.which("openssl"), "openssl unavailable")
    def test_dry_run_validates_credentials_and_signs_jwt(self):
        with tempfile.TemporaryDirectory() as tmp, \
                tempfile.TemporaryDirectory() as empty_config:
            root = Path(tmp)
            key_path = root / "AuthKey_TEST.p8"
            gen = subprocess.run(
                ["openssl", "ecparam", "-genkey", "-name", "prime256v1",
                 "-noout", "-out", str(key_path)],
                capture_output=True, text=True,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)
            env = os.environ.copy()
            env.update({
                "ASC_API_KEY_ID": "TESTKEY123",
                "ASC_API_ISSUER_ID": "00000000-0000-0000-0000-000000000000",
                "ASC_API_KEY_PATH": str(key_path),
                "CLAUDE_PROJECT_DIR": str(root),
                "AUTOBOT_CONFIG_DIR": empty_config,
            })
            result = subprocess.run(
                ["bash", str(SCRIPT), "--bundle-id", "com.example.demo", "--dry-run"],
                cwd=root, env=env, capture_output=True, text=True,
            )
            # dry-run must not fabricate a verdict file
            verdict_written = (root / ".autobot" / "review-verdict.json").exists()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run validation passed", result.stdout)
        self.assertFalse(verdict_written)

    def test_missing_credentials_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp, \
                tempfile.TemporaryDirectory() as empty_config:
            root = Path(tmp)
            env = os.environ.copy()
            for key in ("ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_KEY_PATH"):
                env.pop(key, None)
            env.update({
                "CLAUDE_PROJECT_DIR": str(root),
                "AUTOBOT_CONFIG_DIR": empty_config,
            })
            result = subprocess.run(
                ["bash", str(SCRIPT), "--bundle-id", "com.example.demo", "--dry-run"],
                cwd=root, env=env, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("missing ASC API credentials", result.stderr)


if __name__ == "__main__":
    unittest.main()
