"""Regression coverage for the Axiom bridge gate, peer-review strictness,
peer architecture review (Phase 1, bi-directional), and Phase 7 self-check.

These tests close the 11 findings from the review pass:
  - axiom_audit_skipped logEvent registered (so soft-skip does not hard-fail)
  - Gate 5->6 axiom_critical_audit_acceptable 4-way branch
  - peer_review_acceptable requires skipReason
  - peer_review_acceptable rejects skip when env says peer is available
  - peer_review_acceptable verifies findingsPath on disk for PASS
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

    def test_axiom_installed_no_metadata_fails(self):
        self._prepare_phase5(axiom_installed=True, audit=None)
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
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

    def test_axiom_installed_critical_positive_fails(self):
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
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("axiom_critical_present", result.stdout + result.stderr)

    def test_axiom_installed_findings_path_missing_fails(self):
        self._prepare_phase5(
            axiom_installed=True,
            audit={
                "ran": True, "critical_count": 0,
                "findings_path": ".autobot/does-not-exist.json",
            },
        )
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("axiom_findings_missing", result.stdout + result.stderr)

    def test_axiom_installed_not_ran_fails(self):
        self._prepare_phase5(
            axiom_installed=True,
            audit={"ran": False},
        )
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("axiom_audit_not_run", result.stdout + result.stderr)


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

    def test_skipped_without_reason_rejected(self):
        self._prepare(peer_review={"host": "codex", "peer": "claude", "verdict": "skipped"})
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peer_review_skipped_without_reason", result.stdout + result.stderr)

    def test_skip_contradicts_env_available(self):
        self._prepare(
            peer_review={"host": "codex", "peer": "claude",
                         "verdict": "skipped", "skipReason": "peer_cli_unavailable"},
            peer_available=True,
        )
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
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

    def test_pass_without_findings_path_passes(self):
        # PASS without findingsPath is acceptable (inline review may have no artifact).
        self._prepare(peer_review={"host": "codex", "peer": "claude", "verdict": "PASS"})
        result = self._run_gate()
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("peer_review_pass", result.stdout)

    def test_pass_with_missing_findings_path_rejected(self):
        self._prepare(peer_review={
            "host": "codex", "peer": "claude", "verdict": "PASS",
            "findingsPath": ".autobot/peer-review/does-not-exist.json",
        })
        result = self._run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("peer_review_findings_missing", result.stdout + result.stderr)


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
