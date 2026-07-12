"""Regression tests for the App Store Connect API-key JSON that the three
`fastlane deliver`-based scripts hand to `--api_key_path`.

Root cause guarded here: the scripts emitted `{"key_id", "issuer_id",
"key_filepath": <path>}`. fastlane's `Spaceship::ConnectAPI::Token.from_json_file`
does NOT recognize `key_filepath` — it hard-requires a `key` field holding the
PEM *contents* and otherwise raises

    App Store Connect API key JSON is missing field(s): key

so every metadata upload / screenshot upload / review submission died at
fastlane login before touching ASC. The fix reads the .p8 contents into
`ASC_API_KEY_CONTENT` and emits them under `key`.

These are source-contract tests (hermetic, no network, no fastlane): they pin
the construction so a future edit cannot silently revert to `key_filepath`.
Runtime validity (the emitted JSON actually loads through fastlane's real
`Token.from_json_file` with a real .p8) was verified out-of-band.
"""

from __future__ import annotations

import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent

# Every script that builds a fastlane api_key.json for `deliver`.
SCRIPTS = [
    PLUGIN_DIR / "skills" / "autobot-upload-metadata" / "scripts" / "upload-metadata.sh",
    PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "upload-screenshots.sh",
    PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "submit-for-review.sh",
]


class FastlaneApiKeyJsonTests(unittest.TestCase):
    def test_scripts_exist(self):
        for script in SCRIPTS:
            self.assertTrue(script.is_file(), f"missing: {script}")

    def test_emit_key_content_not_filepath(self):
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
                # The JSON must carry the PEM contents under `key`.
                self.assertIn(
                    'key=$ASC_API_KEY_CONTENT',
                    src,
                    f"{script.name} does not emit `key` with the PEM contents",
                )
                # And that content must be read from the .p8 file.
                self.assertIn(
                    'ASC_API_KEY_CONTENT="$(cat "$ASC_API_KEY_PATH")"',
                    src,
                    f"{script.name} does not read the .p8 contents into "
                    f"ASC_API_KEY_CONTENT",
                )


if __name__ == "__main__":
    unittest.main()
