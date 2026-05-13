"""Public CLI surface regressions that are easy to miss in full simulations."""

from __future__ import annotations

import json
import subprocess
import unittest

from conftest import IsolatedProjectCase, PLUGIN_DIR, SCRIPTS_DIR, run_pipeline


class TestCliSurfaces(IsolatedProjectCase):

    def test_validate_state_render_docs_is_check_only(self):
        script = (SCRIPTS_DIR / "validate-state.sh").read_text(encoding="utf-8")
        self.assertIn("render_pipeline_docs.py\" --check", script)
        self.assertNotIn("render_pipeline_docs.py\" --write", script)

        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "validate-state.sh"), "render-docs"],
            cwd=PLUGIN_DIR,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("rendered docs are up to date", result.stdout + result.stderr)

    def test_soft_gate_failure_advances_phase_and_records_gate_status(self):
        state_path = self.project_dir / ".autobot" / "build-state.json"
        state = json.loads(state_path.read_text())
        state["phases"]["5"] = {"status": "completed", "completedAt": "t", "retryCount": 0}
        state["phases"]["6"] = {"status": "in_progress", "startedAt": "t", "retryCount": 0}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

        result = run_pipeline("advance-phase", "--phase", "6", project_dir=self.project_dir)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.state()
        self.assertEqual(state["phases"]["6"]["status"], "completed")
        self.assertEqual(state["gates"]["6->7"]["status"], "soft_failed")
        self.assertIn("soft gate 6->7 failed", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
