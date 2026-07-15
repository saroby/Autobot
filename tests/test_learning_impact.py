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
    _merge_patterns,
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
                    # no errorSignatureHistory → zero fix attempts → "helped"
                }
            })
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "helped")
            self.assertEqual(summary["summaries"][0]["delta"], 1)

    def test_completed_after_fix_attempts_marks_neutral(self):
        # errorSignatureHistory is the real build-fix-attempt signal. A phase
        # that COMPLETED but only after recording fix-attempt signatures earns
        # "neutral" (0), not "helped". This branch was dead while the grader
        # read the never-written `buildFixAttempts` key (every completed phase
        # graded "helped", inflating scores).
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "5": {
                    "status": "completed",
                    "learningsConsumed": [_consumed("5", "some rule")],
                    "errorSignatureHistory": [
                        {"hash": "deadbeef", "preview": "error: cannot find type 'Foo'"},
                    ],
                }
            })
            summary = grade_build(proj, "build-neutral")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "neutral")
            self.assertEqual(summary["summaries"][0]["delta"], 0)

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

    def test_legacy_string_records_never_mint_new_items(self):
        # Bare agent-name strings (legacy records + the gate-visible name
        # cli.py always appends, incl. first-build sources:[] records) must NOT
        # create new items — that promoted strings like "architect" into
        # active learnings and leaked them to the global store.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed", "learningsConsumed": ["ui-builder"]}
            })
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 0)
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            self.assertEqual(data["items"], [])

    def test_legacy_string_record_still_grades_preexisting_item(self):
        # Items minted by older versions keep being graded via
        # stable_id(phase, agent-name) — only NEW minting is blocked.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed", "learningsConsumed": ["ui-builder"]}
            })
            legacy_id = stable_id("4", "ui-builder")
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {},
                "items": [{"id": legacy_id, "phase": "4", "effect_score": 0,
                           "last_outcome": "untried", "applied_runs": []}],
            }))
            summary = grade_build(proj, "build-001")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "helped")

    def test_per_rule_records_grade_independently_not_per_agent(self):
        # Two different rules from the same agent/phase must grade as DISTINCT
        # learnings (per-rule), and the bare agent-name string present alongside
        # them must NOT also be graded (no double-count, no coarse agent bucket).
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed",
                       "learningsConsumed": [
                           "ui-builder",  # gate string — must be skipped when rules exist
                           _consumed("4", "rule A", "ui-builder"),
                           _consumed("4", "rule B", "ui-builder"),
                       ]},
            })
            summary = grade_build(proj, "build-001")
            ids = {s["id"] for s in summary["summaries"]}
            self.assertEqual(summary["updated"], 2)
            self.assertEqual(ids, {stable_id("4", "rule A"), stable_id("4", "rule B")})
            self.assertNotIn(stable_id("4", "ui-builder"), ids)

    def test_grade_propagates_quarantine_to_rendered_prevention_rules(self):
        # A prevention rule graded "hurt" repeatedly must drop the effect_score
        # of the matching patterns.common_build_errors entry, so the renderer
        # (which reads that store) stops emitting it — closing the "quarantine
        # never reaches the prompt path" hole (W2).
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "5": {"status": "failed",
                       "learningsConsumed": [_consumed("5", "always pin the sdk", "quality-engineer")]},
            })
            # Seed the rendered store with a matching prevention rule.
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {"common_build_errors": [
                    {"pattern": "ModelContainer crash", "frequency": 9,
                     "prevention": "always pin the sdk"},
                ]},
                "items": [],
            }))
            grade_build(proj, "b1")   # hurt -1
            grade_build(proj, "b2")   # hurt -1 → -2 (quarantine threshold)
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            entry = data["patterns"]["common_build_errors"][0]
            self.assertLessEqual(entry.get("effect_score", 0), QUARANTINE_THRESHOLD)


class TestExternalFeedbackMerge(unittest.TestCase):
    """patterns.external_feedback entries key on `theme` (not `pattern`) and
    must merge idempotently on the publish hop, with source_apps unioned so the
    global store can spot the same theme across DIFFERENT apps."""

    def _entry(self, apps: list[str], freq: int = 1, rule: str = "surface primary CTA") -> dict:
        return {"theme": "Onboarding is confusing", "severity": "high",
                "source_apps": apps, "sample_quotes": ["confusing"],
                "suggested_prevention_rule": rule, "frequency": freq}

    def test_same_theme_merges_instead_of_duplicating(self):
        merged = _merge_patterns(
            {"external_feedback": [self._entry(["AppA"], freq=2)]},
            {"external_feedback": [self._entry(["AppB"], freq=1)]},
        )
        entries = merged["external_feedback"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["frequency"], 2)  # max, not sum
        self.assertEqual(entries[0]["source_apps"], ["AppA", "AppB"])  # union

    def test_publish_roundtrip_is_idempotent(self):
        glob = {"external_feedback": [self._entry(["AppA"])]}
        proj = {"external_feedback": [self._entry(["AppA"])]}
        once = _merge_patterns(glob, proj)
        twice = _merge_patterns(once, proj)
        self.assertEqual(once, twice)
        self.assertEqual(len(twice["external_feedback"]), 1)

    def test_distinct_themes_both_survive(self):
        other = dict(self._entry(["AppB"]), theme="Crash on rotation")
        merged = _merge_patterns(
            {"external_feedback": [self._entry(["AppA"])]},
            {"external_feedback": [other]},
        )
        themes = {e["theme"] for e in merged["external_feedback"]}
        self.assertEqual(themes, {"Onboarding is confusing", "Crash on rotation"})


if __name__ == "__main__":
    unittest.main()
