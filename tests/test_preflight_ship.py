"""preflight-ship — the runtime shipping block at the archive entry point.

The anti-laundering policy used to live only in command-markdown bash
snippets (testflight.md / app-review.md); invoking the archive skill directly
or resuming phase 6 bypassed it. pipeline.sh preflight-ship re-proves gate
5->6 FRESH and judges the verdict from the fresh run's own output, so stale
'passed' evidence in build-state.json can never launder an unverified build.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import (
    IsolatedProjectCase,
    PLUGIN_DIR,
    SCRIPTS_DIR,
    _scoped_env,
    run_pipeline,
)


class TestPreflightShipStandalone(unittest.TestCase):
    def test_no_build_state_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline("preflight-ship", project_dir=Path(tmp))
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("ERROR: preflight-ship", result.stderr)
        self.assertIn("build-state.json", result.stderr)


class TestPreflightShipBlocks(IsolatedProjectCase):
    def test_unverified_build_is_blocked(self):
        # Fresh project: gate 5->6 hard-fails (build_succeeded missing) so the
        # preflight must refuse to ship.
        result = run_pipeline("preflight-ship", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: preflight-ship", result.stderr)

    def test_stale_passed_evidence_cannot_launder(self):
        # Plant a stale 'passed' 5->6 evidence blob (e.g. from a previous
        # build). The preflight judges the FRESH re-run, not persisted state,
        # so shipping must still be refused — and the evidence is refreshed.
        state_path = self.project_dir / ".autobot" / "build-state.json"
        state = self.state()
        state["gates"] = {"5->6": {
            "status": "passed", "checkedAt": "2020-01-01T00:00:00Z",
            "fromPhase": "5", "toPhase": "6", "soft": False, "checks": {},
        }}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

        result = run_pipeline("preflight-ship", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: preflight-ship", result.stderr)
        # Fresh evidence replaced the stale 'passed'.
        refreshed = self.state()["gates"]["5->6"]["status"]
        self.assertNotEqual(refreshed, "passed")


@unittest.skipUnless(shutil.which("xcodebuild"), "xcodebuild required (archive.sh probes it before the preflight)")
class TestArchiveScriptRunsPreflight(IsolatedProjectCase):
    """archive.sh must invoke preflight-ship before any xcodebuild work and
    refuse (exit 3) when gate 5->6 is not a clean pass."""

    def test_archive_blocked_on_unverified_build(self):
        # Minimal .xcodeproj so archive.sh input validation passes; the
        # preflight blocks before xcodebuild archive would ever run.
        (self.project_dir / f"{self.APP_NAME}.xcodeproj").mkdir()
        status_file = self.project_dir / ".autobot" / "archive-status.json"
        env = _scoped_env(self.project_dir, {
            "AUTOBOT_ARCHIVE_STATUS_FILE": str(status_file),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR),
        })
        script = PLUGIN_DIR / "skills" / "autobot-archive-build" / "scripts" / "archive.sh"
        result = subprocess.run(
            ["bash", str(script),
             "--project-path", str(self.project_dir),
             "--scheme", self.APP_NAME],
            capture_output=True, text=True, env=env, cwd=self.project_dir,
        )
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("preflight-ship refused", result.stderr)
        status = json.loads(status_file.read_text())
        self.assertEqual(status["result"], "failed")
        self.assertEqual(status["reason"], "preflight_ship_gate_failed")

    def test_dry_run_skips_preflight(self):
        (self.project_dir / f"{self.APP_NAME}.xcodeproj").mkdir()
        env = _scoped_env(self.project_dir, {"CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR)})
        script = PLUGIN_DIR / "skills" / "autobot-archive-build" / "scripts" / "archive.sh"
        result = subprocess.run(
            ["bash", str(script),
             "--project-path", str(self.project_dir),
             "--scheme", self.APP_NAME,
             "--dry-run"],
            capture_output=True, text=True, env=env, cwd=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("dry-run validation passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
