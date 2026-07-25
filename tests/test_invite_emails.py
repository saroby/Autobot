"""Regression tests for skills/autobot-invite-testers/scripts/invite.sh email
parsing. Never touches the network — they drive the script only far enough to
exercise the --emails parser, which runs before any JWT/ASC call.

Root cause guarded here: `config.sh get-or testerEmails` emits a JSON array
string (json.dumps of the list), and deployer passes it verbatim to
`--emails`. A plain comma split turned `["a@x.com", "b@x.com"]` into the
tokens `["a@x.com` and `"b@x.com"]`, both of which failed email validation —
so the DOCUMENTED setup path (testerEmails in config.json) silently invited
zero testers, while only the TESTER_EMAIL env fallback worked. The parser now
accepts both a comma string and a JSON array.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_DIR / "skills" / "autobot-invite-testers" / "scripts" / "invite.sh"

# Hermetic sandbox: the script sources ./.env and ${AUTOBOT_CONFIG_DIR}/.env,
# so a machine where /autobot:setup has run would otherwise leak real creds.
_SANDBOX = tempfile.TemporaryDirectory(prefix="autobot-invite-test.")
_FAKE_KEY = Path(_SANDBOX.name) / "AuthKey_FAKE.p8"
_FAKE_KEY.write_text("-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n")


def run(emails, bundle_id="com.axi.x"):
    """Drive invite.sh far enough to run the email parser. Real ASC creds are
    faked with a readable-but-invalid .p8: valid emails pass the parser and
    then die at JWT signing (never 'invalid email')."""
    env = os.environ.copy()
    env["AUTOBOT_CONFIG_DIR"] = _SANDBOX.name
    env["APP_STORE_CONNECT_API_KEY_KEY_ID"] = "FAKEKEY000"
    env["APP_STORE_CONNECT_API_KEY_ISSUER_ID"] = "fake-issuer"
    env["APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"] = str(_FAKE_KEY)
    return subprocess.run(
        ["bash", str(SCRIPT), "--bundle-id", bundle_id, "--emails", emails],
        env=env, cwd=_SANDBOX.name, capture_output=True, text=True,
    )


class InviteEmailParsingTests(unittest.TestCase):
    def _assert_passed_email_validation(self, r):
        # The parser accepted the emails: the run did NOT stop with the
        # email-validation error. (It fails later at JWT signing on the fake
        # key — that is fine; we only assert the parser let it through.)
        self.assertNotIn("invalid email", r.stderr, r.stderr)

    def test_json_array_form_is_accepted(self):
        # config.sh get-or testerEmails → this exact shape.
        r = run('["a@example.com", "b@example.com"]')
        self._assert_passed_email_validation(r)

    def test_single_element_json_array_is_accepted(self):
        r = run('["solo@example.com"]')
        self._assert_passed_email_validation(r)

    def test_comma_string_form_still_works(self):
        # TESTER_EMAIL env fallback / standalone use.
        r = run("a@example.com,b@example.com")
        self._assert_passed_email_validation(r)

    def test_single_email_still_works(self):
        r = run("solo@example.com")
        self._assert_passed_email_validation(r)

    def test_invalid_email_in_json_array_is_rejected_by_clean_token(self):
        # Proves the JSON wrapper is stripped BEFORE validation: the reported
        # bad token is the clean address, not `["not-an-email`.
        r = run('["not-an-email"]')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("invalid email: not-an-email", r.stderr)

    def test_invalid_email_in_comma_string_is_rejected(self):
        r = run("good@example.com,nope")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("invalid email: nope", r.stderr)


if __name__ == "__main__":
    unittest.main()
