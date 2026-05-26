"""Tests for scripts/learning_impact.py — effect_score grading + quarantine.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from learning_impact import (  # noqa: E402
    QUARANTINE_THRESHOLD,
    active,
    grade_build,
    quarantined,
    stable_id,
)


def _seed(project_root: Path, *, phases: dict) -> None:
    (project_root / ".autobot").mkdir()
    (project_root / ".autobot" / "build-state.json").write_text(
        json.dumps({"phases": phases})
    )


def _consumed(phase: str, rule: str, agent: str = "test-agent") -> dict:
    return {"id": stable_id(phase, rule), "rule": rule, "agent": agent}


class TestStableId(unittest.TestCase):
    def test_same_phase_and_rule_yields_same_id(self):
        self.assertEqual(stable_id("4", "always do X"), stable_id("4", "always do X"))

    def test_different_phase_yields_different_id(self):
        self.assertNotEqual(stable_id("4", "rule"), stable_id("5", "rule"))

    def test_whitespace_trimmed(self):
        self.assertEqual(stable_id("4", "rule"), stable_id("4", "  rule  "))


class TestGradeBuild(unittest.TestCase):
    def test_completed_phase_with_no_fix_attempts_marks_helped(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {
                    "status": "completed",
                    "learningsConsumed": [_consumed("4", "good rule")],
                    "buildFixAttempts": [],
                }
            })
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "helped")
            self.assertEqual(summary["summaries"][0]["delta"], 1)

    def test_failed_phase_marks_hurt(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "5": {
                    "status": "failed",
                    "learningsConsumed": [_consumed("5", "bad rule")],
                }
            })
            summary = grade_build(proj, "build-002")
            self.assertEqual(summary["summaries"][0]["outcome"], "hurt")
            self.assertEqual(summary["summaries"][0]["delta"], -1)

    def test_circuit_breaker_marks_hurt_minus_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "5": {
                    "status": "failed",
                    "learningsConsumed": [_consumed("5", "dangerous rule")],
                    "circuitBreaker": {"tripped": True},
                }
            })
            summary = grade_build(proj, "build-003")
            self.assertEqual(summary["summaries"][0]["delta"], -2)

    def test_quarantine_after_two_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            consumed = [_consumed("5", "always wrong")]
            _seed(proj, phases={"5": {"status": "failed", "learningsConsumed": consumed}})
            grade_build(proj, "build-001")
            # Re-grade a second build with same hurt outcome accumulates -2 → quarantine
            grade_build(proj, "build-002")
            quar = quarantined(proj)
            self.assertEqual(len(quar), 1)
            self.assertLessEqual(quar[0]["effect_score"], QUARANTINE_THRESHOLD)

    def test_active_filter_removes_quarantined_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            # Phase that helps + phase that hurts twice (will be quarantined)
            _seed(proj, phases={
                "4": {"status": "completed",
                       "learningsConsumed": [_consumed("4", "good rule")],
                       "buildFixAttempts": []},
                "5": {"status": "failed",
                       "learningsConsumed": [_consumed("5", "bad rule")]},
            })
            grade_build(proj, "build-001")
            grade_build(proj, "build-002")
            grade_build(proj, "build-003")

            active_items = active(proj)["items"]
            ids = {i["id"] for i in active_items}
            good_id = stable_id("4", "good rule")
            bad_id = stable_id("5", "bad rule")
            self.assertIn(good_id, ids, "helpful rule must remain active")
            self.assertNotIn(bad_id, ids, "hurtful rule must be quarantined")

    def test_no_consumed_learnings_means_no_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={"3": {"status": "completed"}})
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 0)

    def test_missing_build_state_returns_safe_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = grade_build(Path(tmp), "build-x")
            self.assertEqual(summary["updated"], 0)
            self.assertEqual(summary["reason"], "no_build_state")

    def test_legacy_string_consumed_records_still_grade(self):
        # Older builds recorded learningsConsumed as plain strings (agent names).
        # The grader must still attribute outcomes to them via stable_id(phase, rec).
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed", "learningsConsumed": ["ui-builder"], "buildFixAttempts": []}
            })
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "helped")


if __name__ == "__main__":
    unittest.main()
