"""Regression coverage for the Axiom bridge gate, peer-review sidecar behavior,
peer architecture review (Phase 1, bi-directional), and Phase 7 self-check.

These tests close the 11 findings from the review pass:
  - axiom_audit_skipped logEvent registered (so soft-skip does not hard-fail)
  - Gate 5->6 axiom_critical_audit_acceptable reports sidecar issues as DEGRADED
  - peer_review_acceptable reports unauditable/contradictory evidence as DEGRADED
  - peer_review_acceptable verifies findingsPath on disk for PASS without hard-failing MVP
  - architecture_peer_review_acceptable bi-directional (Codex-host -> Claude)
  - Phase 7 verify-phase7-axiom self-check 4-way
"""

from __future__ import annotations

import json
import subprocess
import unittest

from conftest import (
    IsolatedProjectCase, PLUGIN_DIR, SCRIPTS_DIR,
    import_runtime_modules, run_pipeline, run_build_log,
)

import_runtime_modules()
from gate_runner import check_architecture_peer_review_acceptable  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# A1: axiom_audit_skipped logEvent must be accepted by build-log.sh
# ─────────────────────────────────────────────────────────────────────────────
class TestAxiomLogEvent(IsolatedProjectCase):

    def test_axiom_audit_skipped_event_accepted(self):
        result = run_build_log(
            "--phase", "5",
            "--event", "axiom_audit_skipped",
            "--detail", '{"reason":"axiom plugin not installed"}',
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        events = [e["event"] for e in self.log_lines()]
        self.assertIn("axiom_audit_skipped", events)

    def test_axiom_audit_completed_event_accepted(self):
        result = run_build_log(
            "--phase", "5",
            "--event", "axiom_audit_completed",
            "--detail", '{"mode":"critical","criticalCount":0,"auditors":["concurrency"]}',
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# B1: axiom_critical_audit_acceptable — 4-way branch
# ─────────────────────────────────────────────────────────────────────────────
class TestAxiomCriticalGate(IsolatedProjectCase):

    def _prepare_phase5(self, *, axiom_installed: bool,
                        audit: dict | None = None,
                        peer_review_skipped: bool = True):
        app_root = self.project_dir / self.APP_NAME
        (app_root / "App").mkdir(parents=True, exist_ok=True)
        (app_root / "Views").mkdir(parents=True, exist_ok=True)
        (app_root / "Services").mkdir(parents=True, exist_ok=True)
        (app_root / "App" / f"{self.APP_NAME}App.swift").write_text(
            "let repository = ItemRepository()\nlet container = ModelContainer.self\n"
        )
        (app_root / "App" / "ServiceStubs.swift").write_text("struct ServiceStubs {}\n")
        (app_root / "Views" / "HomeView.swift").write_text("struct HomeView {}\n")
        (app_root / "Services" / "ItemRepository.swift").write_text("struct ItemRepository {}\n")

        state = self.state()
        state["environment"]["axiom"] = axiom_installed
        meta = {"build_succeeded": True}
        if audit is not None:
            meta["axiom_critical_audit"] = audit
        if peer_review_skipped:
            meta["peerReview"] = {
                "host": "codex", "peer": "claude",
                "verdict": "skipped", "skipReason": "peer_cli_unavailable",
            }
        state["phases"]["5"] = {
            "status": "in_progress", "startedAt": "t",
            "retryCount": 0,
            "metadata": meta,
            "learningsConsumed": ["quality-engineer"],
        }
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, indent=2)
        )

    def _run_gate(self):
        return run_pipeline(
            "run-gate", "--gate", "5->6", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

    def test_axiom_absent_no_metadata_passes(self):
        self._prepare_phase5(axiom_installed=False, audit=None)
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("axiom_audit_skipped_env", result.stdout)

    def test_axiom_installed_no_metadata_degrades(self):
        self._prepare_phase5(axiom_installed=True, audit=None)
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("axiom_audit_missing", result.stdout + result.stderr)

    def test_axiom_installed_critical_zero_passes(self):
        # findings_path file must exist on disk
        findings = self.project_dir / ".autobot" / "axiom-critical.json"
        findings.write_text('{"critical":[],"warning":[]}')
        self._prepare_phase5(
            axiom_installed=True,
            audit={
                "ran": True,
                "auditors": ["concurrency", "swiftdata"],
                "critical_count": 0,
                "findings_path": ".autobot/axiom-critical.json",
            },
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("axiom_critical_clean", result.stdout)

    def test_axiom_installed_critical_positive_degrades(self):
        findings = self.project_dir / ".autobot" / "axiom-critical.json"
        findings.write_text('{"critical":[{"file":"X.swift"}],"warning":[]}')
        self._prepare_phase5(
            axiom_installed=True,
            audit={
                "ran": True,
                "auditors": ["concurrency"],
                "critical_count": 3,
                "findings_path": ".autobot/axiom-critical.json",
            },
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("axiom_critical_present", result.stdout + result.stderr)

    def test_axiom_installed_clean_without_findings_path_degrades(self):
        # Anti-laundering: ran=true + critical_count=0 with NO findings artifact
        # is an unauditable self-report — must not roll up green.
        self._prepare_phase5(
            axiom_installed=True,
            audit={"ran": True, "critical_count": 0},
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("axiom_findings_path_absent", result.stdout + result.stderr)

    def test_axiom_installed_findings_path_missing_degrades(self):
        self._prepare_phase5(
            axiom_installed=True,
            audit={
                "ran": True, "critical_count": 0,
                "findings_path": ".autobot/does-not-exist.json",
            },
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("axiom_findings_missing", result.stdout + result.stderr)

    def test_axiom_installed_not_ran_degrades(self):
        self._prepare_phase5(
            axiom_installed=True,
            audit={"ran": False},
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("axiom_audit_not_run", result.stdout + result.stderr)

    def test_axiom_findings_path_directory_degrades(self):
        # Anti-laundering: a DIRECTORY passes .exists() but is not an auditable
        # artifact — is_file() is required.
        (self.project_dir / ".autobot" / "axiom-critical.json").mkdir(
            parents=True, exist_ok=True)
        self._prepare_phase5(axiom_installed=True, audit={
            "ran": True, "critical_count": 0,
            "findings_path": ".autobot/axiom-critical.json"})
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("axiom_findings_missing", result.stdout + result.stderr)

    def test_axiom_findings_path_dot_degrades(self):
        # findings_path="." resolves to the project dir (a dir) → not a file.
        self._prepare_phase5(axiom_installed=True, audit={
            "ran": True, "critical_count": 0, "findings_path": "."})
        result = self._run_gate()
        self.assertIn("axiom_findings_missing", result.stdout + result.stderr)

    def test_axiom_findings_escapes_project_degrades(self):
        self._prepare_phase5(axiom_installed=True, audit={
            "ran": True, "critical_count": 0,
            "findings_path": "../../../../etc/hosts"})
        result = self._run_gate()
        self.assertIn("axiom_findings_escape_project", result.stdout + result.stderr)

    def test_axiom_findings_corrupt_json_degrades(self):
        (self.project_dir / ".autobot" / "axiom-critical.json").write_text("{not json")
        self._prepare_phase5(axiom_installed=True, audit={
            "ran": True, "critical_count": 0,
            "findings_path": ".autobot/axiom-critical.json"})
        result = self._run_gate()
        self.assertIn("axiom_findings_unparseable", result.stdout + result.stderr)

    def test_axiom_findings_count_mismatch_degrades(self):
        # metadata claims 0 critical but the artifact lists criticals — the
        # one-line-metadata laundering vector.
        (self.project_dir / ".autobot" / "axiom-critical.json").write_text(
            '{"critical":[{"file":"X.swift"}],"warning":[]}')
        self._prepare_phase5(axiom_installed=True, audit={
            "ran": True, "critical_count": 0,
            "findings_path": ".autobot/axiom-critical.json"})
        result = self._run_gate()
        self.assertIn("axiom_findings_count_mismatch", result.stdout + result.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# B2: peer_review_acceptable — skipReason + env-contradiction + findingsPath
# ─────────────────────────────────────────────────────────────────────────────
class TestPeerReviewStrict(IsolatedProjectCase):

    def _prepare(self, *, peer_review: dict, peer_available: bool = False):
        app_root = self.project_dir / self.APP_NAME
        (app_root / "App").mkdir(parents=True, exist_ok=True)
        (app_root / "Views").mkdir(parents=True, exist_ok=True)
        (app_root / "Services").mkdir(parents=True, exist_ok=True)
        (app_root / "App" / f"{self.APP_NAME}App.swift").write_text(
            "let repository = ItemRepository()\nlet container = ModelContainer.self\n"
        )
        (app_root / "App" / "ServiceStubs.swift").write_text("struct ServiceStubs {}\n")
        (app_root / "Views" / "HomeView.swift").write_text("struct HomeView {}\n")
        (app_root / "Services" / "ItemRepository.swift").write_text("struct ItemRepository {}\n")

        state = self.state()
        state["environment"]["peerReviewAvailable"] = peer_available
        state["environment"]["axiom"] = False  # keep axiom out of the way
        state["phases"]["5"] = {
            "status": "in_progress", "startedAt": "t",
            "retryCount": 0,
            "metadata": {"build_succeeded": True, "peerReview": peer_review},
            "learningsConsumed": ["quality-engineer"],
        }
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, indent=2)
        )

    def _run_gate(self):
        return run_pipeline(
            "run-gate", "--gate", "5->6", "--app-name", self.APP_NAME,
            project_dir=self.project_dir,
        )

    def test_skipped_without_reason_degrades(self):
        self._prepare(peer_review={"host": "codex", "peer": "claude", "verdict": "skipped"})
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_skipped_without_reason", result.stdout + result.stderr)

    def test_skip_contradicts_env_available_degrades(self):
        self._prepare(
            peer_review={"host": "codex", "peer": "claude",
                         "verdict": "skipped", "skipReason": "peer_cli_unavailable"},
            peer_available=True,
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_skip_contradicts_env", result.stdout + result.stderr)

    def test_skip_allowlisted_runtime_failure_passes_when_available(self):
        self._prepare(
            peer_review={"host": "codex", "peer": "claude",
                         "verdict": "skipped", "skipReason": "peer_invocation_failed"},
            peer_available=True,
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review_skipped", result.stdout)

    def test_pass_without_findings_path_degrades(self):
        # Anti-laundering: the bridge always writes an artifact, so a PASS with
        # no findingsPath is a self-report a single --metadata line can forge.
        self._prepare(peer_review={"host": "codex", "peer": "claude", "verdict": "PASS"})
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_pass_without_artifact", result.stdout + result.stderr)

    def test_pass_with_findings_path_on_disk_passes(self):
        findings = self.project_dir / ".autobot" / "peer-review"
        findings.mkdir(parents=True, exist_ok=True)
        (findings / "phase-5.json").write_text('{"verdict":"PASS","blockingFindings":[]}')
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/phase-5.json",
        })
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review_pass", result.stdout)
        self.assertNotIn("peer_review_pass_without_artifact", result.stdout)

    def test_pass_with_missing_findings_path_degrades(self):
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/does-not-exist.json",
        })
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_findings_missing", result.stdout + result.stderr)

    def _write_peer_artifact(self, text: str) -> None:
        d = self.project_dir / ".autobot" / "peer-review"
        d.mkdir(parents=True, exist_ok=True)
        (d / "phase-5.json").write_text(text)

    def test_pass_with_directory_findings_path_degrades(self):
        # Anti-laundering: a directory passes .exists() but is not a file.
        (self.project_dir / ".autobot" / "peer-review" / "phase-5.json").mkdir(
            parents=True, exist_ok=True)
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/phase-5.json"})
        result = self._run_gate()
        self.assertIn("peer_review_findings_missing", result.stdout + result.stderr)

    def test_pass_with_corrupt_json_artifact_degrades(self):
        self._write_peer_artifact("not json at all, just prose")
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/phase-5.json"})
        result = self._run_gate()
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_findings_unparseable", result.stdout + result.stderr)

    def test_pass_with_contradicting_verdict_artifact_degrades(self):
        # metadata says PASS but the artifact's own verdict is FAIL — laundering.
        self._write_peer_artifact('{"verdict":"FAIL","blockingFindings":[{"x":1}]}')
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/phase-5.json"})
        result = self._run_gate()
        self.assertIn("peer_review_verdict_mismatch", result.stdout + result.stderr)

    def test_pass_with_fenced_json_artifact_tolerated(self):
        # The peer artifact is a CLI last-message; a ```json fence must NOT
        # false-DEGRADE a genuinely passing review.
        self._write_peer_artifact(
            'Here is my review:\n```json\n'
            '{"verdict":"PASS","blockingFindings":[]}\n```\n')
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/phase-5.json"})
        result = self._run_gate()
        self.assertIn("peer_review_pass", result.stdout)
        self.assertNotIn("peer_review_findings_unparseable", result.stdout)
        self.assertNotIn("peer_review_verdict_mismatch", result.stdout)

    def test_missing_peer_review_skips_when_peer_unavailable(self):
        self._prepare(peer_review={}, peer_available=False)
        state = self.state()
        state["environment"]["peerReviewAvailable"] = False
        state["environment"]["axiom"] = False
        state["phases"]["5"] = {
            "status": "in_progress", "startedAt": "t",
            "retryCount": 0,
            "metadata": {"build_succeeded": True},
            "learningsConsumed": ["quality-engineer"],
        }
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, indent=2)
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review_not_available", result.stdout)
        self.assertNotIn("[DEGRADED] peer_review_acceptable", result.stdout)

    def test_missing_peer_review_degrades_when_peer_available(self):
        self._prepare(peer_review={}, peer_available=True)
        state = self.state()
        state["environment"]["peerReviewAvailable"] = True
        state["environment"]["axiom"] = False
        state["phases"]["5"] = {
            "status": "in_progress", "startedAt": "t",
            "retryCount": 0,
            "metadata": {"build_succeeded": True},
            "learningsConsumed": ["quality-engineer"],
        }
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, indent=2)
        )
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Gate 5->6: DEGRADED", result.stdout)
        self.assertIn("peer_review_missing", result.stdout)


# ─────────────────────────────────────────────────────────────────────────────
# B3: architecture_peer_review_acceptable (bi-directional, Phase 1)
# ─────────────────────────────────────────────────────────────────────────────
class TestArchitecturePeerReview(unittest.TestCase):
    """Direct in-process check of the bi-directional Phase-1 reviewer logic."""

    def _state(self, p1_metadata: dict) -> dict:
        return {
            "environment": {"axiom": False},
            "phases": {"1": {"status": "in_progress", "metadata": p1_metadata}},
        }

    def _passed(self, results: list[dict]) -> bool:
        return all(r.get("passed") or r.get("skipped") for r in results)

    def test_codex_host_to_claude_peerreview_accepted(self):
        from pathlib import Path
        results = check_architecture_peer_review_acceptable(
            Path("/tmp"), "TestApp",
            self._state({"peerReview": {
                "host": "codex", "peer": "claude",
                "verdict": "PASS", "attempt": 1, "blockingFindingsCount": 0,
            }}),
        )
        self.assertTrue(self._passed(results), msg=results)
        self.assertIn("codex", str(results))

    def test_legacy_codexreview_still_accepted(self):
        from pathlib import Path
        results = check_architecture_peer_review_acceptable(
            Path("/tmp"), "TestApp",
            self._state({"codexReview": {
                "verdict": "PASS", "attempt": 1,
                "hardViolationsCount": 0, "softWarningsCount": 0,
            }}),
        )
        self.assertTrue(self._passed(results), msg=results)

    def test_skipped_without_reason_rejected(self):
        from pathlib import Path
        results = check_architecture_peer_review_acceptable(
            Path("/tmp"), "TestApp",
            self._state({"peerReview": {
                "host": "codex", "peer": "claude", "verdict": "skipped",
            }}),
        )
        self.assertFalse(self._passed(results), msg=results)
        self.assertIn("skipped_without_reason", str(results))

    def test_skipped_with_reason_passes(self):
        from pathlib import Path
        results = check_architecture_peer_review_acceptable(
            Path("/tmp"), "TestApp",
            self._state({"peerReview": {
                "host": "codex", "peer": "claude",
                "verdict": "skipped", "skipReason": "peer_cli_unavailable",
            }}),
        )
        self.assertTrue(self._passed(results), msg=results)


# ─────────────────────────────────────────────────────────────────────────────
# B4: verify-phase7-axiom.py self-check (4-way)
# ─────────────────────────────────────────────────────────────────────────────
class TestPhase7Verify(IsolatedProjectCase):

    SCRIPT = SCRIPTS_DIR / "verify-phase7-axiom.py"

    def _write(self, state: dict, log_lines: list[dict] | None = None):
        (self.project_dir / ".autobot" / "build-state.json").write_text(
            json.dumps(state, indent=2)
        )
        log = self.project_dir / ".autobot" / "build-log.jsonl"
        log.write_text("\n".join(json.dumps(l) for l in (log_lines or [])))

    def _run(self):
        return subprocess.run(
            ["python3", str(self.SCRIPT), str(self.project_dir)],
            capture_output=True, text=True,
        )

    def test_axiom_false_no_skip_event_fails(self):
        self._write({"environment": {"axiom": False}, "phases": {}}, [])
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no axiom_audit_skipped event", result.stderr)

    def test_axiom_false_with_skip_event_passes(self):
        self._write(
            {"environment": {"axiom": False}, "phases": {}},
            [{"event": "axiom_audit_skipped", "phase": "7", "ts": "t",
              "detail": {"reason": "no axiom"}}],
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_axiom_true_no_metadata_fails(self):
        self._write({"environment": {"axiom": True}, "phases": {}})
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ran", result.stderr)

    def test_axiom_true_ran_true_passes(self):
        self._write({
            "environment": {"axiom": True},
            "phases": {"7": {"metadata": {"axiom_health_check": {"ran": True}}}},
        })
        result = self._run()
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
