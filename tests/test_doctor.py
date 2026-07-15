from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from doctor import Probe, credential_probe, summarize  # noqa: E402


class TestDoctor(unittest.TestCase):
    def test_ship_profile_blocks_on_missing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = credential_probe(Path(tmp), env={"AUTOBOT_CONFIG_DIR": tmp})
            self.assertEqual(probe.status, "fail")
            self.assertIn("ASC_API_KEY_ID", probe.reason)

    def test_credential_probe_validates_private_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "AuthKey.p8"
            key.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
            probe = credential_probe(Path(tmp), env={
                "ASC_API_KEY_ID": "KEY",
                "ASC_API_ISSUER_ID": "ISSUER",
                "ASC_API_KEY_PATH": str(key),
            })
            self.assertEqual(probe.status, "pass")

    def test_summary_is_machine_actionable(self):
        result = summarize("ship", [
            Probe("xcode", "pass", "installed", "Xcode 26", ""),
            Probe("asc_credentials", "fail", "missing", "", "run setup"),
        ])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["profile"], "ship")
        self.assertEqual(result["checks"][1]["remediation"], "run setup")


if __name__ == "__main__":
    unittest.main()
