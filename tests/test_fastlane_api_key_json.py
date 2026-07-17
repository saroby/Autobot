"""Regression tests for the App Store Connect API-key JSON that the three
`fastlane deliver`-based scripts hand to `--api_key_path`.

Two root causes guarded here:
  1. The scripts once emitted `{"key_id", "issuer_id", "key_filepath": <path>}`.
     fastlane's `Spaceship::ConnectAPI::Token.from_json_file` does NOT recognize
     `key_filepath` — it hard-requires a `key` field holding the PEM *contents*
     and otherwise raises "App Store Connect API key JSON is missing field(s):
     key", so every metadata upload / screenshot upload / review submission died
     at fastlane login before touching ASC.
  2. The first fix read the PEM into a shell variable and passed it through
     python argv (`emit_json "key=$PEM"`), exposing the private key to
     same-host process listings and any future `set -x`. The scripts now pipe
     the .p8 *path* into a python heredoc that reads the contents itself, so
     the PEM only ever exists in the python process memory and the 0600 file.

The functional test extracts each script's heredoc verbatim and runs it against
a fake .p8, pinning the emitted JSON shape end-to-end (quoting drift included).
Runtime validity through fastlane's real `Token.from_json_file` was verified
out-of-band.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# Every script that builds a fastlane api_key.json for `deliver`.
SCRIPTS = [
    PLUGIN_DIR / "skills" / "autobot-upload-metadata" / "scripts" / "upload-metadata.sh",
    PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "upload-screenshots.sh",
    PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "submit-for-review.sh",
]

HEREDOC_HEADER = (
    'python3 - "$ASC_API_KEY_ID" "$ASC_API_ISSUER_ID" "$ASC_API_KEY_PATH" '
    '> "$API_KEY_JSON" <<\'PY\''
)
KEY_JSON_HEREDOC = re.compile(re.escape(HEREDOC_HEADER) + r"\n(.*?)\nPY\n", re.DOTALL)

FAKE_PEM = "-----BEGIN PRIVATE KEY-----\nfake-p8-body\n-----END PRIVATE KEY-----\n"


class FastlaneApiKeyJsonTests(unittest.TestCase):
    def test_scripts_exist(self):
        for script in SCRIPTS:
            self.assertTrue(script.is_file(), f"missing: {script}")

    def test_key_json_built_from_path_not_shell_variable(self):
        for script in SCRIPTS:
            src = script.read_text()
            with self.subTest(script=script.name):
                # The rejected shape must be gone.
                self.assertNotIn(
                    "key_filepath=",
                    src,
                    f"{script.name} still emits key_filepath — fastlane requires "
                    f"`key` with PEM contents",
                )
                # The PEM must never pass through a shell variable / argv.
                self.assertNotIn(
                    "ASC_API_KEY_CONTENT",
                    src,
                    f"{script.name} reads the .p8 into a shell variable — the "
                    f"PEM lands in process argv (ps-visible, set -x leak)",
                )
                # The heredoc receives the key *path* and reads it in python.
                self.assertIn(
                    HEREDOC_HEADER,
                    src,
                    f"{script.name} does not build the key JSON via the "
                    f"path-arg heredoc pattern",
                )

    def test_heredoc_emits_fastlane_token_json(self):
        for script in SCRIPTS:
            src = script.read_text()
            match = KEY_JSON_HEREDOC.search(src)
            with self.subTest(script=script.name):
                self.assertIsNotNone(match, f"{script.name}: key-JSON heredoc not found")
                with tempfile.TemporaryDirectory() as tmp:
                    p8 = Path(tmp) / "AuthKey_TEST.p8"
                    p8.write_text(FAKE_PEM)
                    result = subprocess.run(
                        [sys.executable, "-", "KEYID12345", "issuer-uuid", str(p8)],
                        input=match.group(1), capture_output=True, text=True,
                    )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["key_id"], "KEYID12345")
                self.assertEqual(payload["issuer_id"], "issuer-uuid")
                self.assertEqual(payload["key"], FAKE_PEM)
                self.assertNotIn("key_filepath", payload)


if __name__ == "__main__":
    unittest.main()
