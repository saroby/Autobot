"""submit-for-review.sh's build-state parser must not abort the poll loop.

The old `grep|head|tr|awk` pipeline let grep exit 1 on an unrecognized pilot
row; under `set -euo pipefail` that failure propagated into the
`LAST_STATE="$(...)"` assignment and killed the script before the retry logic
could run. extract_build_state() now uses a single awk that always exits 0, so a
no-match leaves LAST_STATE empty and the loop retries.

This extracts the actual function text from the script (no drift) and exercises
it under `set -euo pipefail`.
"""

from __future__ import annotations

import subprocess
import unittest

from conftest import PLUGIN_DIR

SUBMIT_SH = PLUGIN_DIR / "skills" / "autobot-app-review" / "scripts" / "submit-for-review.sh"


def _extract_function(name: str, script_text: str) -> str:
    lines = script_text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}()"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


class TestExtractBuildState(unittest.TestCase):
    def setUp(self) -> None:
        self.fn = _extract_function("extract_build_state", SUBMIT_SH.read_text())

    def _run(self, harness: str) -> subprocess.CompletedProcess:
        script = f"set -euo pipefail\n{self.fn}\n{harness}"
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    def test_no_match_does_not_abort_under_pipefail(self):
        # If the assignment aborted (old bug), "rc=0" would never print and the
        # subprocess would exit non-zero.
        result = self._run(
            "STATE=\"$(printf '%s\\n' 'garbage row with no build state token' "
            "| extract_build_state)\"\n"
            "echo \"rc=$?\"\n"
            "echo \"empty=[$STATE]\""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rc=0", result.stdout)
        self.assertIn("empty=[]", result.stdout)

    def test_recognizes_state_tokens(self):
        cases = {
            "| 1.2 | 34 | VALID |": "valid",
            "Build 34    PROCESSING": "processing",
            "row INVALID": "invalid",
            "old build EXPIRED": "expired",
        }
        for row, expected in cases.items():
            with self.subTest(row=row):
                result = self._run(f"printf '%s\\n' {row!r} | extract_build_state")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_first_row_with_a_token_wins(self):
        result = self._run(
            "printf '%s\\n' 'header build state column' 'row1 INVALID' 'row2 VALID' "
            "| extract_build_state"
        )
        self.assertEqual(result.stdout.strip(), "invalid")


if __name__ == "__main__":
    unittest.main()
