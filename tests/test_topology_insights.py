"""Tests for scripts/topology_insights.py — cross-build hotspot rollup.

Pure `rollup()` core: fed a synthetic global-learnings dict, it must rank phase
hotspots by corrective pressure and emit operator-facing candidates. No network,
no real global store.
"""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

from topology_insights import rollup, render_markdown  # noqa: E402


def _item(phase, score, outcome="helped", runs=("b1",)):
    return {
        "id": f"{phase}-{score}-{outcome}",
        "phase": str(phase),
        "effect_score": score,
        "last_outcome": outcome,
        "applied_runs": list(runs),
        "rule_preview": "x",
    }


class RollupTests(unittest.TestCase):
    def test_phase_hotspot_ranking_by_item_count(self):
        # Phase 4 dominates → must rank first with the largest share.
        items = (
            [_item(4, 1) for _ in range(6)]
            + [_item(5, 1) for _ in range(3)]
            + [_item(1, 1)]
        )
        out = rollup({"patterns": {}, "items": items})
        self.assertEqual(out["total_items"], 10)
        top = out["phase_hotspots"][0]
        self.assertEqual(top["phase"], "4")
        self.assertEqual(top["item_count"], 6)
        self.assertEqual(top["share"], 0.6)
        self.assertEqual(top["label"], "Phase 4 · Parallel Coding")

    def test_dominant_phase_yields_high_candidate(self):
        items = [_item(4, 1) for _ in range(4)] + [_item(1, 1)]  # 80% in phase 4
        out = rollup({"patterns": {}, "items": items})
        highs = [c for c in out["candidates"] if c["severity"] == "high"]
        self.assertTrue(highs)
        self.assertEqual(highs[0]["phase"], "4")

    def test_dead_weight_candidate_counts_nonpositive_scores(self):
        # 5 never-helped learnings in one phase → medium candidate.
        items = [_item(5, 0, outcome="neutral") for _ in range(5)]
        out = rollup({"patterns": {}, "items": items})
        row = out["phase_hotspots"][0]
        self.assertEqual(row["dead_or_negative"], 5)
        self.assertTrue(any(c["severity"] == "medium" and c["phase"] == "5" for c in out["candidates"]))

    def test_quarantined_counts_threshold(self):
        items = [_item(4, -2), _item(4, -3), _item(4, 1)]
        out = rollup({"patterns": {}, "items": items})
        row = next(r for r in out["phase_hotspots"] if r["phase"] == "4")
        self.assertEqual(row["quarantined"], 2)  # -2 and -3 are <= threshold

    def test_build_coverage_dedupes_run_ids(self):
        items = [_item(4, 1, runs=("b1", "b2")), _item(4, 1, runs=("b2", "b3"))]
        out = rollup({"patterns": {}, "items": items})
        row = out["phase_hotspots"][0]
        self.assertEqual(row["build_coverage"], 3)  # {b1,b2,b3}

    def test_recurring_build_error_candidate(self):
        patterns = {"common_build_errors": [{"error": "duplicate symbol X", "count": 4}]}
        out = rollup({"patterns": patterns, "items": [_item(4, 1)]})
        self.assertTrue(any("duplicate symbol" in c["evidence"] for c in out["candidates"]))

    def test_empty_store_is_safe(self):
        out = rollup({"patterns": {}, "items": []})
        self.assertEqual(out["total_items"], 0)
        self.assertEqual(out["phase_hotspots"], [])
        self.assertEqual(out["candidates"], [])
        # markdown renders without raising even when empty
        self.assertIn("Cross-Build Pipeline Insights", render_markdown(out))

    def test_malformed_items_ignored(self):
        out = rollup({"patterns": {}, "items": ["nope", None, _item(4, 1)]})
        self.assertEqual(out["total_items"], 3)  # counts raw list length
        self.assertEqual(sum(r["item_count"] for r in out["phase_hotspots"]), 1)  # only the valid dict


if __name__ == "__main__":
    unittest.main()
