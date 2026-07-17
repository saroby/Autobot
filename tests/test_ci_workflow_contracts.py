"""Regression coverage for .github/workflows/ci.yml.

Guards against the 0.12.x incident where ci.yml's first step
(`python3 -c "from scripts import spec_loader; ..."`) died with
ModuleNotFoundError on every push for 3+ weeks, silently disabling every
downstream drift/unit check in the job. See tasks/lessons.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Single-line `run: <cmd>` steps only — ci.yml has no multi-line `run: |`
# blocks today. If one is added, this regex simply won't match it and the
# new step goes unchecked rather than failing loudly, so keep this in sync.
_RUN_STEP_RE = re.compile(r"^\s*run:\s*(python3\s+.+)$", re.MULTILINE)

# Steps that invoke the full regression suite (or its runner) recurse into
# this very test process if executed here — skip, they're exercised by
# actually running the suite, not by this contract test.
_SKIP_SUBSTRINGS = ("run_tests.sh", "compileall")


class TestCiWorkflowContracts(unittest.TestCase):

    def _python_run_steps(self) -> list[str]:
        content = CI_YML.read_text(encoding="utf-8")
        return [
            cmd
            for cmd in _RUN_STEP_RE.findall(content)
            if not any(skip in cmd for skip in _SKIP_SUBSTRINGS)
        ]

    def test_ci_yml_has_no_duplicate_spec_loader_validation_step(self):
        # The removed step re-imported spec_loader via `from scripts import
        # spec_loader`, which 404s (scripts/ has no __init__.py, so it isn't
        # importable as a package) — and was 100% redundant with
        # verify_spec_docs.py's `load_spec()`, which already calls
        # validate_spec() internally.
        content = CI_YML.read_text(encoding="utf-8")
        self.assertNotIn("from scripts import spec_loader", content)

    def test_ci_yml_python_run_steps_all_exit_zero(self):
        steps = self._python_run_steps()
        self.assertTrue(steps, "expected at least one python3 run: step in ci.yml")

        for cmd in steps:
            result = subprocess.run(
                cmd, shell=True, cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
            )
            self.assertEqual(
                0,
                result.returncode,
                f"ci.yml step `{cmd}` exited {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
