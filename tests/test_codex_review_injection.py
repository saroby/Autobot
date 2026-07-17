"""codex-architecture-review.sh must never execute model output.

The verdict JSON is UNTRUSTED model output. The old parser interpolated it into
Python source (`json.loads('''$verdict_json''')`), so a triple-quote breakout in
the model's last message ran arbitrary code in the review process. The parser
now reads the file via json.load(argv path) inside a quoted heredoc, so the same
payload is inert: it fails to parse (verdict recorded skipped) and nothing runs.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR, run_pipeline

SCRIPT = PLUGIN_DIR / "scripts" / "codex-architecture-review.sh"
APP_NAME = "InjApp"


def _make_stub_codex(path: Path) -> None:
    # A fake `codex` that writes the malicious "last message" to the path given
    # by --output-last-message, then exits 0. The payload is a triple-quote
    # breakout that would run os.system('touch $TEST_SENTINEL') if it were ever
    # interpolated into Python source (the pre-fix bug); as file content read by
    # json.load it is simply invalid JSON. `chr(39)*3` builds the `'''` at stub
    # runtime so this test source contains no literal triple-quote.
    body = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
out = None
for i, a in enumerate(args):
    if a == "--output-last-message" and i + 1 < len(args):
        out = args[i + 1]
try:
    sys.stdin.read()
except Exception:
    pass
sentinel = os.environ["TEST_SENTINEL"]
q = chr(39) * 3
payload = q + '+__import__("os").system("touch ' + sentinel + '")+' + q
if out:
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(payload)
sys.exit(0)
'''
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class TestCodexReviewInjection(unittest.TestCase):
    def test_model_output_triple_quote_breakout_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            # Valid build-state so persist_review's schema-validated mutation works.
            result = run_pipeline(
                "init-build", "--build-id", "build-inj", "--app-name", APP_NAME,
                "--display-name", "Inj", project_dir=proj,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            (proj / ".autobot" / "architecture.md").write_text("# Architecture\n")
            (proj / APP_NAME / "Models").mkdir(parents=True)
            (proj / APP_NAME / "Models" / "ServiceProtocols.swift").write_text("// models\n")

            bin_dir = proj / "bin"
            bin_dir.mkdir()
            _make_stub_codex(bin_dir / "codex")

            sentinel = proj / "PWNED"
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["CLAUDE_PROJECT_DIR"] = str(proj)
            env["TEST_SENTINEL"] = str(sentinel)

            result = subprocess.run(
                ["bash", str(SCRIPT), "--app-name", APP_NAME, "--project-dir", str(proj)],
                capture_output=True, text=True, env=env, cwd=proj,
            )
            sentinel_created = sentinel.exists()
            state = json.loads((proj / ".autobot" / "build-state.json").read_text())

        # 1. No code executed — the breakout sentinel was never created.
        self.assertFalse(sentinel_created, "model output executed — injection not closed")
        # 2. Parse failure is a non-blocking skip, exit 0.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 3. Recorded as an auditable skip with the parse reason.
        review = state["phases"]["1"]["metadata"]["peerReview"]
        self.assertEqual(review["verdict"], "skipped")
        self.assertEqual(review["skipReason"], "codex_response_parse_failed")


if __name__ == "__main__":
    unittest.main()
