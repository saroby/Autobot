"""Tests for scripts/run_summary.py — JSON + Markdown report generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from run_summary import build_summary, render_markdown, write_summary  # noqa: E402


def _seed(project_root: Path, *, state: dict, events: list[dict]) -> None:
    (project_root / ".autobot").mkdir()
    (project_root / ".autobot" / "build-state.json").write_text(json.dumps(state))
    (project_root / ".autobot" / "build-log.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )


class TestOverallStatus(unittest.TestCase):
    def test_all_terminal_successes_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {"0": {"status": "completed"}, "1": {"status": "completed"}}
            }, events=[])
            summary = build_summary(proj)
            self.assertEqual(summary["status"], "completed")

    def test_any_failed_phase_marks_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b2", "appName": "X",
                "phases": {"0": {"status": "completed"}, "5": {"status": "failed"}}
            }, events=[])
            summary = build_summary(proj)
            self.assertEqual(summary["status"], "failed")

    def test_in_progress_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b3", "appName": "X",
                "phases": {"4": {"status": "in_progress"}}
            }, events=[])
            summary = build_summary(proj)
            self.assertEqual(summary["status"], "in_progress")


class TestPhaseDurations(unittest.TestCase):
    def test_start_to_complete_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={"buildId": "b1", "appName": "X", "phases": {}}, events=[
                {"ts": "2026-05-26T00:00:00Z", "event": "start", "phase": 1, "buildId": "b1"},
                {"ts": "2026-05-26T00:01:00Z", "event": "complete", "phase": 1, "buildId": "b1"},
            ])
            summary = build_summary(proj)
            self.assertEqual(summary["phases"]["1"]["durationSeconds"], 60.0)

    def test_events_are_scoped_to_current_build_with_bounded_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "current", "appName": "X",
                "startedAt": "2026-05-26T00:10:00Z",
                "phases": {"5": {"status": "completed"}},
            }, events=[
                {"ts": "2026-05-26T00:00:00Z", "event": "start", "phase": 1, "buildId": "old"},
                {"ts": "2026-05-26T00:01:00Z", "event": "gate_fail", "phase": 1,
                 "detail": "old tagged failure", "buildId": "old"},
                {"ts": "2026-05-26T00:05:00Z", "event": "gate_fail", "phase": 2,
                 "detail": "legacy before current run"},
                {"ts": "2026-05-26T00:11:00Z", "event": "start", "phase": 5},
                {"ts": "2026-05-26T00:12:00Z", "event": "complete", "phase": 5,
                 "buildId": "current"},
            ])

            summary = build_summary(proj)

            self.assertEqual(set(summary["phases"]), {"5"})
            self.assertEqual(summary["phases"]["5"]["durationSeconds"], 60.0)
            self.assertEqual(summary["gateLedger"], [])
            self.assertEqual(summary["failureFootprint"]["events"], [])

    def test_legacy_events_are_excluded_without_a_parseable_run_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={"buildId": "b1", "appName": "X", "phases": {}}, events=[
                {"ts": "2026-05-26T00:00:00Z", "event": "start", "phase": 1},
                {"ts": "2026-05-26T00:01:00Z", "event": "complete", "phase": 1},
            ])
            self.assertEqual(build_summary(proj)["phases"], {})


class TestFailureFootprint(unittest.TestCase):
    def test_failure_event_and_resume_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {"5": {"status": "failed"}}
            }, events=[
                {"ts": "2026-05-26T00:00:00Z", "event": "fail", "phase": 5,
                 "detail": "boom", "buildId": "b1"},
            ])
            summary = build_summary(proj)
            footprint = summary["failureFootprint"]
            self.assertEqual(footprint["failedPhase"], "5")
            self.assertEqual(footprint["resumeCommand"], "/autobot:resume 5")
            self.assertEqual(len(footprint["events"]), 1)
            self.assertEqual(footprint["primaryFailure"], footprint["events"][0])

    def test_latest_failure_is_primary_and_events_are_latest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {"5": {"status": "failed"}},
            }, events=[
                {"ts": "2026-05-26T00:01:00Z", "event": "gate_fail", "phase": 4,
                 "detail": "first", "buildId": "b1"},
                {"ts": "2026-05-26T00:03:00Z", "event": "fail", "phase": 5,
                 "detail": "latest", "buildId": "b1"},
                {"ts": "2026-05-26T00:02:00Z", "event": "circuit_breaker_triggered", "phase": 5,
                 "detail": "middle", "buildId": "b1"},
            ])

            footprint = build_summary(proj)["failureFootprint"]

            self.assertEqual(footprint["primaryFailure"]["detail"], "latest")
            self.assertEqual(
                [event["detail"] for event in footprint["events"]],
                ["latest", "middle", "first"],
            )

    def test_no_failure_means_default_resume_no_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={"buildId": "b1", "appName": "X", "phases": {}}, events=[])
            summary = build_summary(proj)
            footprint = summary["failureFootprint"]
            self.assertIsNone(footprint["failedPhase"])
            self.assertIsNone(footprint["primaryFailure"])
            self.assertEqual(footprint["resumeCommand"], "/autobot:resume")


class TestOperationalLedger(unittest.TestCase):
    def test_phase_ledger_contains_state_and_real_fix_attempt_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {
                    "5": {
                        "status": "failed",
                        "retryCount": 2,
                        "error": "compile failed",
                        "errorSignatureHistory": [
                            {"hash": "a"}, {"hash": "b"}, {"hash": "c"},
                        ],
                    },
                },
            }, events=[])

            summary = build_summary(proj)
            phase = summary["phases"]["5"]

            self.assertEqual(phase["status"], "failed")
            self.assertEqual(phase["retryCount"], 2)
            self.assertEqual(phase["maxRetry"], 2)
            self.assertEqual(phase["error"], "compile failed")
            self.assertEqual(phase["buildFixAttempts"], 3)
            markdown = render_markdown(summary)
            self.assertIn("| 5 | failed |", markdown)
            self.assertIn("| 2/2 | 3 |", markdown)

    def test_axiom_quality_signals_use_canonical_metadata_keys(self):
        critical = {"ran": True, "critical_count": 0}
        health = {"ran": True, "findings_path": ".autobot/axiom-health.json"}
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {
                    "5": {"status": "completed", "metadata": {"axiom_critical_audit": critical}},
                    "7": {"status": "completed", "metadata": {"axiom_health_check": health}},
                },
            }, events=[])

            signals = build_summary(proj)["qualitySignals"]

            self.assertEqual(signals["axiomCriticalAudit"], critical)
            self.assertEqual(signals["axiomAudit"], critical)
            self.assertEqual(signals["axiomHealthCheck"], health)
            self.assertEqual(build_summary(proj)["schemaVersion"], 1)

    def test_legacy_axiom_audit_remains_available(self):
        legacy = {"ran": True, "finding_count": 2}
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {
                    "5": {"status": "completed", "metadata": {"axiomAudit": legacy}},
                },
            }, events=[])

            summary = build_summary(proj)

            self.assertEqual(summary["schemaVersion"], 1)
            self.assertEqual(summary["qualitySignals"]["axiomAudit"], legacy)
            self.assertIsNone(summary["qualitySignals"]["axiomCriticalAudit"])


class TestRenderMarkdown(unittest.TestCase):
    def test_includes_failure_section_only_when_present(self):
        clean_summary = {
            "buildId": "b1", "appName": "X", "phases": {}, "gateLedger": [],
            "buildAttempts": [], "qualitySignals": {}, "learnings": {},
            "failureFootprint": {"events": [], "resumeCommand": "/autobot:resume", "failedPhase": None},
            "status": "completed",
        }
        md = render_markdown(clean_summary)
        self.assertNotIn("## Failure Footprint", md)

        bad_summary = dict(clean_summary)
        bad_summary["failureFootprint"] = {
            "events": [{"ts": "T", "phase": 5, "event": "fail", "detail": "x"}],
            "resumeCommand": "/autobot:resume 5",
            "failedPhase": "5",
        }
        md_bad = render_markdown(bad_summary)
        self.assertIn("## Failure Footprint", md_bad)
        self.assertIn("/autobot:resume 5", md_bad)


class TestWriteSummary(unittest.TestCase):
    def test_writes_json_and_md_and_updates_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "build-xyz", "appName": "Demo", "phases": {"0": {"status": "completed"}}
            }, events=[])
            result = write_summary(proj)
            json_path = Path(result["_paths"]["json"])
            md_path = Path(result["_paths"]["md"])
            latest = Path(result["_paths"]["latest"])
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            self.assertTrue(latest.exists() or latest.is_symlink())

    def test_status_in_summary_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, state={
                "buildId": "b1", "appName": "X",
                "phases": {"5": {"status": "failed"}}
            }, events=[])
            result = write_summary(proj)
            self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
