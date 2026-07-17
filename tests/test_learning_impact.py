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
    # Model the Phase-0-loaded learnings store: every STRUCTURED learning the
    # build reports as consumed must already exist as an items[] entry to be
    # graded. Grade-time minting no longer self-scores (learning_impact.py: a
    # rule first seen at grade time is banked at effect_score 0), so tests that
    # exercise the scoring heuristic pre-seed the item here. Bare agent-name
    # strings are never seeded — they must not mint (see the legacy tests).
    seeded: list[dict] = []
    seen: set[str] = set()
    for phase_id, block in phases.items():
        if not isinstance(block, dict):
            continue
        for rec in block.get("learningsConsumed") or []:
            if not (isinstance(rec, dict) and rec.get("rule")):
                continue
            item_id = rec.get("id") or stable_id(phase_id, rec["rule"])
            if item_id in seen:
                continue
            seen.add(item_id)
            seeded.append({
                "id": item_id, "phase": phase_id, "effect_score": 0,
                "last_outcome": "untried", "applied_runs": [],
                "rule_preview": rec["rule"][:200],
            })
    if seeded:
        (project_root / ".autobot" / "learnings.json").write_text(
            json.dumps({"patterns": {}, "items": seeded})
        )


def _consumed(phase: str, rule: str, agent: str = "test-agent") -> dict:
    return {"id": stable_id(phase, rule), "rule": rule, "agent": agent}


def _find_item(project_root: Path, item_id: str) -> dict:
    data = json.loads((project_root / ".autobot" / "learnings.json").read_text())
    return next(i for i in data["items"] if i["id"] == item_id)


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

    def test_grade_time_mint_does_not_self_score_until_next_build(self):
        # Security: an agent reporting a never-before-seen rule during a clean
        # build must NOT collect +1 in that same build (self-certification). The
        # rule is recorded (score 0, provenance) and only scores when a LATER
        # build actually applies the now-pre-existing rule.
        rule = "novel rule first seen at grade time"
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            # No learnings.json seed → the rule is first seen at grade time.
            (proj / ".autobot" / "build-state.json").write_text(json.dumps({
                "buildId": "build-mint-1",
                "phases": {"4": {"status": "completed",
                                 "learningsConsumed": [_consumed("4", rule)]}},
            }))
            summary = grade_build(proj, "build-mint-1")
            self.assertEqual(summary["updated"], 0)  # nothing scored this pass
            item = _find_item(proj, stable_id("4", rule))
            self.assertEqual(item["effect_score"], 0)
            self.assertEqual(item["minted_by"], "grade_build")

            # A later build (new build id) that applies the now pre-existing rule
            # grades it for real.
            (proj / ".autobot" / "build-state.json").write_text(json.dumps({
                "buildId": "build-mint-2",
                "phases": {"4": {"status": "completed",
                                 "learningsConsumed": [_consumed("4", rule)]}},
            }))
            summary = grade_build(proj, "build-mint-2")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["outcome"], "helped")
            self.assertEqual(_find_item(proj, stable_id("4", rule))["effect_score"], 1)

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

    def test_same_build_id_grades_only_once(self):
        # A retrospective can run twice on one build (fail → resume → complete).
        # The second grade with the SAME build id must be a no-op — one vote
        # per build per item, on items[] AND the propagated pattern stores.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            rule = "always pin the sdk"
            _seed(proj, phases={
                "5": {"status": "failed", "learningsConsumed": [_consumed("5", rule)]},
            })
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {"common_build_errors": [
                    {"pattern": "crash", "frequency": 1, "prevention": rule},
                ]},
                # Pre-existing item so the FIRST grade scores it (grade-time mint
                # no longer self-scores); the second grade of the same build is
                # the no-op under test.
                "items": [{"id": stable_id("5", rule), "phase": "5",
                           "effect_score": 0, "last_outcome": "untried",
                           "applied_runs": []}],
            }))
            first = grade_build(proj, "same-build")
            second = grade_build(proj, "same-build")
            self.assertEqual(first["updated"], 1)
            self.assertEqual(second["updated"], 0)
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            item = next(i for i in data["items"] if i["id"] == stable_id("5", rule))
            self.assertEqual(item["effect_score"], -1)  # not -2
            self.assertEqual(item["applied_runs"], ["same-build"])
            self.assertEqual(
                data["patterns"]["common_build_errors"][0]["effect_score"], -1)

    def test_build_id_defaults_to_state_build_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            (proj / ".autobot" / "build-state.json").write_text(json.dumps({
                "buildId": "state-build",
                "phases": {"4": {"status": "completed",
                                 "learningsConsumed": [_consumed("4", "good rule")]}},
            }))
            # Pre-existing item so grade scores it (mint at grade time no longer
            # self-scores) — this test is about build-id defaulting, not minting.
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {},
                "items": [{"id": stable_id("4", "good rule"), "phase": "4",
                           "effect_score": 0, "last_outcome": "untried",
                           "applied_runs": []}],
            }))
            summary = grade_build(proj)
            self.assertEqual(summary["updated"], 1)
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            self.assertEqual(data["items"][0]["applied_runs"], ["state-build"])

    def test_no_build_id_anywhere_skips_grading(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed",
                      "learningsConsumed": [_consumed("4", "good rule")]},
            })
            summary = grade_build(proj)
            self.assertEqual(summary["updated"], 0)
            self.assertEqual(summary["reason"], "no_build_id")

    def test_operator_override_demotes_helped_to_neutral(self):
        # A phase that only completed via --allow-terminal-restart style
        # operator override is not evidence the learnings helped.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, phases={
                "4": {"status": "completed",
                      "operatorOverrides": 1,
                      "learningsConsumed": [_consumed("4", "good rule")]},
            })
            summary = grade_build(proj, "build-override")
            self.assertEqual(summary["summaries"][0]["outcome"], "neutral")
            self.assertEqual(summary["summaries"][0]["delta"], 0)

    def test_phase_keyed_rule_grades_existing_external_item(self):
        # Agents record rules with a phase key; external-feedback items are
        # keyed stable_id("external", rule). The grading chokepoint must re-key
        # so external items earn a score instead of minting an untried twin.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            rule = "First-run screens must surface the primary CTA above the fold."
            external_id = stable_id("external", rule)
            _seed(proj, phases={
                "4": {"status": "completed", "learningsConsumed": [_consumed("4", rule)]},
            })
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {},
                "items": [{"id": external_id, "phase": "external",
                           "effect_score": 0, "last_outcome": "untried",
                           "applied_runs": [], "rule_preview": rule}],
            }))
            summary = grade_build(proj, "build-ext")
            self.assertEqual(summary["updated"], 1)
            self.assertEqual(summary["summaries"][0]["id"], external_id)
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            self.assertEqual(len(data["items"]), 1)  # no phase-keyed twin
            self.assertEqual(data["items"][0]["effect_score"], 1)
            self.assertEqual(data["items"][0]["last_outcome"], "helped")

    def test_grade_propagates_to_external_feedback_entries(self):
        # patterns.external_feedback quarantine had a reader (_is_quarantined
        # in the renderer) but no writer — grading a hurtful external rule must
        # drop the matching entry's effect_score.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            rule = "First-run screens must surface the primary CTA above the fold."
            _seed(proj, phases={
                "5": {"status": "failed", "learningsConsumed": [_consumed("5", rule)]},
            })
            (proj / ".autobot" / "learnings.json").write_text(json.dumps({
                "patterns": {"external_feedback": [
                    {"theme": "Onboarding is confusing", "severity": "high",
                     "suggested_prevention_rule": rule, "frequency": 3,
                     "approved": False},
                ]},
                "items": [],
            }))
            grade_build(proj, "b1")
            grade_build(proj, "b2")
            data = json.loads((proj / ".autobot" / "learnings.json").read_text())
            entry = data["patterns"]["external_feedback"][0]
            self.assertLessEqual(entry["effect_score"], QUARANTINE_THRESHOLD)

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
