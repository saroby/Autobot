"""render-active-learnings.py must NOT render prevention rules that have been
quarantined (effect_score <= QUARANTINE_THRESHOLD). This is the prompt-path half
of the quarantine loop (W2): grade_build drops a hurtful rule's effect_score in
patterns.common_build_errors, and the renderer must then omit it from
active-learnings.md / phase-learnings/*.md.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_render():
    spec = importlib.util.spec_from_file_location(
        "render_active_learnings", SCRIPTS / "render-active-learnings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRenderHonorsQuarantine(unittest.TestCase):
    def setUp(self) -> None:
        self.render = _load_render()

    def test_quarantined_rule_excluded_despite_high_frequency(self):
        patterns = {"common_build_errors": [
            {"pattern": "good rule", "frequency": 3, "prevention": "do X"},
            {"pattern": "bad rule", "frequency": 99, "prevention": "do Y", "effect_score": -2},
        ]}
        seen = {e["pattern"] for e in self.render.top_common_errors(patterns)}
        self.assertIn("good rule", seen)
        self.assertNotIn("bad rule", seen)  # quarantined wins over frequency sort

    def test_entries_above_threshold_still_render(self):
        patterns = {"common_build_errors": [
            {"pattern": "p1", "frequency": 1, "prevention": "x"},                      # no score
            {"pattern": "p2", "frequency": 2, "prevention": "y", "effect_score": 0},   # neutral
            {"pattern": "p3", "frequency": 3, "prevention": "z", "effect_score": -1},  # hurt once, not yet quarantined
        ]}
        seen = {e["pattern"] for e in self.render.top_common_errors(patterns)}
        self.assertEqual(seen, {"p1", "p2", "p3"})

    def test_rendered_markdown_omits_quarantined_rule(self):
        data = {"patterns": {"common_build_errors": [
            {"pattern": "QUARANTINED-ERR", "frequency": 99,
             "prevention": "stale advice", "effect_score": -3},
            {"pattern": "LIVE-ERR", "frequency": 1, "prevention": "good advice"},
        ]}}
        md = self.render.render_markdown(data)
        self.assertIn("LIVE-ERR", md)
        self.assertNotIn("QUARANTINED-ERR", md)


if __name__ == "__main__":
    unittest.main()
