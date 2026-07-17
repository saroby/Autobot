from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from app_review_controller import (  # noqa: E402
    _artifact_evidence,
    _build_state,
    claim_next_phase,
    complete_phase,
    fail_phase,
    initialize,
    next_phase,
    reconcile,
)


def _seed(project: Path) -> None:
    autobot = project / ".autobot"
    autobot.mkdir()
    (autobot / "build-state.json").write_text(json.dumps({
        "buildId": "build-1",
        "appName": "Demo",
        "displayName": "Demo",
        "bundleId": "com.example.demo",
        "phases": {"5": {"status": "completed", "inputHash": "phase5-hash"}},
    }))


class TestAppReviewController(unittest.TestCase):
    def test_initializes_versioned_machine_and_returns_first_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            self.assertEqual(state["schemaVersion"], 1)
            self.assertEqual(state["buildId"], "build-1")
            self.assertEqual(next_phase(state)["phase"], "0")

    def test_phase_dependencies_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            with self.assertRaises(ValueError):
                complete_phase(project, state, "B", evidence={"manual": True})

    def test_claim_prevents_duplicate_phase_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            first = claim_next_phase(project, state)
            second = claim_next_phase(project, state)
            self.assertEqual(first["phase"], "0")
            self.assertIn("claimToken", first)
            self.assertEqual(second["action"], "busy")
            self.assertNotIn("claimToken", second)

    def test_complete_rejects_stale_claim_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            claim_next_phase(project, state)
            with self.assertRaisesRegex(ValueError, "claim token"):
                complete_phase(project, state, "0", evidence={}, claim_token="stale")

    def test_phase_zero_stays_claimed_when_ship_doctor_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            claim = claim_next_phase(project, state)
            with mock.patch("doctor.run_doctor", return_value={"status": "blocked"}):
                with self.assertRaisesRegex(ValueError, "doctor is blocked"):
                    complete_phase(
                        project,
                        state,
                        "0",
                        evidence={},
                        claim_token=claim["claimToken"],
                    )
            self.assertEqual(state["phases"]["0"]["status"], "in_progress")

    def test_phase_zero_completes_when_ship_doctor_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            claim = claim_next_phase(project, state)
            with mock.patch("doctor.run_doctor", return_value={"status": "ready"}):
                completed = complete_phase(
                    project,
                    state,
                    "0",
                    evidence={},
                    claim_token=claim["claimToken"],
                )
            self.assertEqual(completed["phases"]["0"]["status"], "completed")

    def test_reconcile_does_not_reuse_upload_from_another_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            upload = project / ".autobot" / "upload-status.json"
            upload.write_text(json.dumps({
                "result": "uploaded",
                "buildId": "old-build",
                "bundleId": "com.example.demo",
                "archiveSha256": "abc",
            }))
            reconciled = reconcile(project, state)
            self.assertNotEqual(reconciled["phases"]["F"]["status"], "completed")

    def test_reconcile_without_new_evidence_does_not_rewrite_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            with mock.patch("app_review_controller._write") as write:
                reconciled = reconcile(project, state)
            write.assert_not_called()
            self.assertEqual(reconciled, state)

    def test_submission_evidence_must_match_current_uploaded_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            autobot = project / ".autobot"
            (autobot / "upload-status.json").write_text(json.dumps({
                "result": "uploaded",
                "buildId": "build-1",
                "bundleId": "com.example.demo",
                "artifactSha256": "artifact-new",
            }))
            review = {
                "result": "submitted",
                "buildId": "build-1",
                "bundleId": "com.example.demo",
                "artifactSha256": "artifact-old",
            }
            (autobot / "review-submit-status.json").write_text(json.dumps(review))
            self.assertIsNone(_artifact_evidence(project, "G", _build_state(project)))

            review["artifactSha256"] = "artifact-new"
            (autobot / "review-submit-status.json").write_text(json.dumps(review))
            self.assertIsNotNone(_artifact_evidence(project, "G", _build_state(project)))

    def test_already_uploaded_binary_counts_as_phase_f_evidence(self):
        # ASC's "Redundant Binary Upload" rejection means the binary is already
        # on ASC; upload.sh records result=already_uploaded and the controller
        # must accept it as Phase F success under the same identity checks.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            autobot = project / ".autobot"
            (autobot / "archive-status.json").write_text(json.dumps({
                "buildId": "build-1",
                "bundleId": "com.example.demo",
                "archiveSha256": "archive-digest",
            }))
            upload = {
                "result": "already_uploaded",
                "buildId": "build-1",
                "bundleId": "com.example.demo",
                "inputManifestHash": "phase5-hash",
                "archiveSha256": "archive-digest",
            }
            (autobot / "upload-status.json").write_text(json.dumps(upload))
            self.assertIsNotNone(_artifact_evidence(project, "F", _build_state(project)))

            upload["result"] = "upload_failed"
            (autobot / "upload-status.json").write_text(json.dumps(upload))
            self.assertIsNone(_artifact_evidence(project, "F", _build_state(project)))

    def test_next_returns_halted_after_three_failed_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _seed(project)
            state = initialize(project)
            for attempt in range(3):
                claim = claim_next_phase(project, state)
                self.assertIn("claimToken", claim, f"attempt {attempt} not claimable")
                state = fail_phase(
                    project, state, "0",
                    reason="fastlane_exit_1", claim_token=claim["claimToken"],
                )
            selected = next_phase(state)
            self.assertEqual(selected["action"], "halted")
            self.assertEqual(selected["phase"], "0")
            self.assertEqual(state["phases"]["0"]["attempts"], 3)
            # halted phases must not hand out a new claim token
            self.assertNotIn("claimToken", claim_next_phase(project, state))

    def test_non_retryable_reason_halts_immediately(self):
        for reason in ("name_collision", "auth_failed", "build_number_conflict"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp)
                _seed(project)
                state = initialize(project)
                claim = claim_next_phase(project, state)
                state = fail_phase(
                    project, state, "0",
                    reason=reason, claim_token=claim["claimToken"],
                )
                selected = next_phase(state)
                self.assertEqual(selected["action"], "halted")
                self.assertEqual(selected["reason"], reason)
                self.assertNotIn("claimToken", claim_next_phase(project, state))


if __name__ == "__main__":
    unittest.main()
