"""Public CLI surface regressions that are easy to miss in full simulations."""

from __future__ import annotations

import json
import subprocess
import unittest

from conftest import IsolatedProjectCase, PLUGIN_DIR, SCRIPTS_DIR, run_pipeline, run_runtime


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

    def test_complete_phase_is_not_a_public_bypass(self):
        result = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        before_log_count = len(self.log_lines())

        result = run_pipeline("complete-phase", "--phase", "1", project_dir=self.project_dir)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("removed", result.stdout + result.stderr)
        state = self.state()
        self.assertEqual(state["phases"]["1"]["status"], "in_progress")
        self.assertNotIn("1->2", state.get("gates", {}))
        self.assertEqual(before_log_count, len(self.log_lines()))

        result = run_runtime("complete-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        state = self.state()
        self.assertEqual(state["phases"]["1"]["status"], "in_progress")
        self.assertNotIn("1->2", state.get("gates", {}))

        result = run_runtime(
            "set-phase-status", "--phase", "1", "--to", "completed",
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        state = self.state()
        self.assertEqual(state["phases"]["1"]["status"], "in_progress")
        self.assertNotIn("1->2", state.get("gates", {}))

    def test_advance_phase_metadata_is_visible_to_gate(self):
        app_root = self.project_dir / self.APP_NAME
        (app_root / "App").mkdir(parents=True)
        (app_root / "App" / f"{self.APP_NAME}App.swift").write_text(
            "import SwiftUI\n"
            "import SwiftData\n"
            "@main struct TestAppApp: App {\n"
            "  let repository = TaskRepository()\n"
            "  var body: some Scene { WindowGroup { Text(\"Hi\") }.modelContainer(for: Item.self) }\n"
            "}\n",
            encoding="utf-8",
        )
        (app_root / "App" / "ServiceStubs.swift").write_text("// previews\n", encoding="utf-8")

        state_path = self.project_dir / ".autobot" / "build-state.json"
        state = json.loads(state_path.read_text())
        for phase in ("1", "2", "3", "4"):
            state["phases"][phase] = {"status": "completed", "completedAt": "t", "retryCount": 0}
        state["phases"]["5"] = {
            "status": "in_progress",
            "startedAt": "t",
            "retryCount": 0,
            "learningsConsumed": ["quality-engineer"],
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

        result = run_pipeline(
            "advance-phase", "--phase", "5",
            "--metadata", "build_succeeded=true",
            "--metadata", 'peerReview={"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}',
            project_dir=self.project_dir,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        state = self.state()
        self.assertEqual(state["phases"]["5"]["status"], "completed")
        self.assertTrue(state["phases"]["5"]["metadata"]["build_succeeded"])
        self.assertEqual(state["phases"]["5"]["metadata"]["peerReview"]["verdict"], "skipped")


if __name__ == "__main__":
    unittest.main()
