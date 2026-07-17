"""check-review-status.sh must not leak the ASC bearer token or hang on ASC.

Contract guards (script-text, like tests/test_app_review_docs_contract.py):
  - the JWT is passed via a mode-600 curl config file (-K), never as a
    `-H "Authorization: Bearer <jwt>"` argv token visible in `ps`
  - make_jwt / the HTTP calls are set -e guarded so the documented exit codes
    actually run
  - curl calls are connection-timed and bounded-retry on transient failures
"""

from __future__ import annotations

import subprocess
import unittest

from conftest import PLUGIN_DIR

SCRIPT = PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "check-review-status.sh"
TEXT = SCRIPT.read_text()


class TestCheckReviewStatusContract(unittest.TestCase):
    def test_script_is_valid_bash(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_bearer_token_not_on_curl_argv(self):
        # The pre-fix form `-H "Authorization: Bearer $JWT"` exposed the token to
        # `ps`. The JWT variable must no longer be interpolated into a header
        # argument (it now flows through the -K config file only).
        self.assertNotIn("Bearer $JWT", TEXT)

    def test_bearer_token_passed_via_mode_600_config_file(self):
        self.assertIn('header = "Authorization: Bearer', TEXT)
        self.assertIn('-K "$CURL_CONFIG"', TEXT)
        self.assertIn('chmod 600 "$CURL_CONFIG"', TEXT)
        self.assertIn("umask 077", TEXT)
        self.assertIn("trap cleanup", TEXT)

    def test_make_jwt_is_set_e_guarded(self):
        self.assertIn('if ! JWT="$(make_jwt)"', TEXT)

    def test_curl_calls_are_timed_and_bounded_retry(self):
        self.assertIn("--connect-timeout", TEXT)
        self.assertIn("--max-time", TEXT)
        # transient retry on ASC 429 / 5xx
        self.assertIn("429|5", TEXT)
        self.assertIn("max_retries", TEXT)


if __name__ == "__main__":
    unittest.main()
