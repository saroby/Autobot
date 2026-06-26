"""Cross-runtime peer review bridge contracts."""

from __future__ import annotations

import json
import subprocess
import unittest

from conftest import IsolatedProjectCase, SCRIPTS_DIR, run_pipeline


class TestPeerReviewBridge(IsolatedProjectCase):

    def _write_state(self, state: dict) -> None:
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2)
        )

    def _prepare_gate_5_artifacts(self, *, peer_review: dict | None = None) -> None:
        app_root = self.project_dir / self.APP_NAME
        (app_root / "App").mkdir(parents=True, exist_ok=True)
        (app_root / "Views").mkdir(parents=True, exist_ok=True)
        (app_root / "Services").mkdir(parents=True, exist_ok=True)

        (app_root / "App" / f"{self.APP_NAME}App.swift").write_text(
            "import SwiftUI\nlet repository = ItemRepository()\nlet container = ModelContainer.self\n",
            encoding="utf-8",
        )
        (app_root / "App" / "ServiceStubs.swift").write_text(
            "import Foundation\nstruct ServiceStubs {}\n",
            encoding="utf-8",
        )
        (app_root / "Views" / "HomeView.swift").write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"Home\") } }\n",
            encoding="utf-8",
        )
        (app_root / "Services" / "ItemRepository.swift").write_text(
            "import Foundation\nstruct ItemRepository {}\n",
            encoding="utf-8",
        )

        state = self.state()
        state["phases"]["5"] = {
            "status": "in_progress",
            "startedAt": "t",
            "retryCount": 0,
            "metadata": {"build_succeeded": True},
            "learningsConsumed": ["quality-engineer"],
        }
        if peer_review is not None:
            state["phases"]["5"]["metadata"]["peerReview"] = peer_review
        self._write_state(state)

    def test_record_environment_accepts_peer_runtime_fields(self):
        result = run_pipeline(
            "record-environment",
            "--runtimeHost", "codex",
            "--peerAi", "claude",
            "--peerReviewAvailable", "false",
            project_dir=self.project_dir,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        env = self.state()["environment"]
        self.assertEqual(env["runtimeHost"], "codex")
        self.assertEqual(env["peerAi"], "claude")
        self.assertFalse(env["peerReviewAvailable"])

    def test_gate_5_skips_missing_peer_review_when_peer_unavailable(self):
        self._prepare_gate_5_artifacts()

        result = run_pipeline(
            "run-gate", "--gate", "5->6", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review_not_available", result.stdout + result.stderr)
        self.assertNotIn("[DEGRADED] peer_review_acceptable", result.stdout + result.stderr)

    def test_gate_5_accepts_skipped_peer_review(self):
        self._prepare_gate_5_artifacts(peer_review={
            "host": "codex",
            "peer": "claude",
            "verdict": "skipped",
            "skipReason": "peer_cli_unavailable",
        })

        result = run_pipeline(
            "run-gate", "--gate", "5->6", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review", result.stdout + result.stderr)

    def test_detect_peer_ai_maps_codex_to_claude(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "detect-peer-ai.sh"), "--host", "codex", "--format", "json"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["runtimeHost"], "codex")
        self.assertEqual(data["peerAi"], "claude")

    def test_list_checks_recognizes_peer_and_state_contains_checks(self):
        result = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "validate-state.sh"), "list-checks", "--gate", "5->6"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("✓ peer_review_acceptable", result.stdout)
        self.assertIn("✓ quality_engineer_consumed_learnings", result.stdout)
        self.assertNotIn("? (state_field_contains)", result.stdout)


if __name__ == "__main__":
    unittest.main()
