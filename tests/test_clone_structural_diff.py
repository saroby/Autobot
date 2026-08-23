"""clone_structural_diff.py — the mechanical missing-element count, offline.

Step 6-4's dominant failure class is a spec element absent from the render.
These pin the contract: missing gates (exit 1), drift warns, wrappers and
frame-matched unlabeled elements do not false-positive.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_structural_diff.py"


def spec_element(role: str, label: str, x: float, y: float, w: float, h: float) -> dict:
    return {"role": role, "label": label,
            "frame": {"x": x, "y": y, "width": w, "height": h}}


def rendered_node(label: str, x: float, y: float, w: float, h: float,
                  children: list | None = None) -> dict:
    # Shaped like `axe describe-ui` actually writes it: the label lives in
    # `AXLabel`, never in a lowercase `label`. A fixture that invented `label`
    # let the label match pass here while being unreachable against a real
    # render for as long as the code read the wrong key.
    node = {"type": "Button", "AXLabel": label,
            "AXFrame": "{{%s, %s}, {%s, %s}}" % (x, y, w, h),
            "frame": {"x": x, "y": y, "width": w, "height": h}}
    if children:
        node["children"] = children
    return node


def run_diff(elements: list[dict], rendered, *args: str) -> subprocess.CompletedProcess:
    measurement = {
        "screen": {"points": {"width": 375, "height": 812}},
        "elements": elements,
    }
    with tempfile.TemporaryDirectory() as d:
        spec = Path(d) / "screen.json"
        tree = Path(d) / "rendered.tree.json"
        spec.write_text(json.dumps(measurement), encoding="utf-8")
        tree.write_text(json.dumps(rendered), encoding="utf-8")
        return subprocess.run(
            ["python3", str(SCRIPT), str(spec), str(tree), *args],
            capture_output=True, text=True,
        )


class TestStructuralDiff(unittest.TestCase):
    def test_all_present_passes(self):
        r = run_diff([spec_element("AXButton", "계속", 38, 722, 299, 52)],
                     [rendered_node("계속", 38, 722, 299, 52)])
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("OK: all 1 spec elements are present", r.stdout)

    def test_a_missing_element_gates_with_exit_1(self):
        r = run_diff([spec_element("AXButton", "계속", 38, 722, 299, 52),
                      spec_element("AXStaticText", "통계", 20, 100, 60, 18)],
                     [rendered_node("계속", 38, 722, 299, 52)])
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing AXStaticText '통계'", r.stdout)
        self.assertIn("1/2 spec element(s)", r.stdout)

    def test_label_match_with_drift_warns_but_does_not_gate(self):
        r = run_diff([spec_element("AXButton", "계속", 38, 722, 299, 52)],
                     [rendered_node("계속", 38, 640, 299, 52)])
        self.assertEqual(r.returncode, 0, msg=r.stdout)
        self.assertIn("WARN: moved AXButton '계속'", r.stdout)

    def test_unlabeled_spec_element_matches_by_frame(self):
        r = run_diff([spec_element("AXImage", "", 100, 200, 40, 40)],
                     [rendered_node("", 102, 201, 40, 40)])
        self.assertEqual(r.returncode, 0, msg=r.stdout)

    def test_fullscreen_wrappers_are_not_counted(self):
        r = run_diff([spec_element("AXOther", "래퍼", 0, 0, 375, 812),
                      spec_element("AXButton", "계속", 38, 722, 299, 52)],
                     [rendered_node("계속", 38, 722, 299, 52)])
        self.assertEqual(r.returncode, 0, msg=r.stdout)
        self.assertNotIn("래퍼", r.stdout)

    def test_nested_rendered_tree_is_flattened(self):
        r = run_diff([spec_element("AXButton", "계속", 38, 722, 299, 52)],
                     rendered_node("루트", 0, 0, 375, 812,
                                   children=[rendered_node("계속", 38, 722, 299, 52)]))
        self.assertEqual(r.returncode, 0, msg=r.stdout)

    def test_extra_rendered_elements_are_reported_as_info(self):
        r = run_diff([spec_element("AXButton", "계속", 38, 722, 299, 52)],
                     [rendered_node("계속", 38, 722, 299, 52),
                      rendered_node("잉여", 10, 10, 40, 40)])
        self.assertEqual(r.returncode, 0)
        self.assertIn("INFO: extra rendered element '잉여'", r.stdout)


if __name__ == "__main__":
    unittest.main()
