"""device_compare.py — side-by-side output plus advisory visual metrics."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.device_compare import MASKED_RGB, PNG, rows_rgb, write_png


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_compare.py"


class TestDeviceCompare(unittest.TestCase):
    def run_compare(self, root: Path, original_rows, rendered_rows, *extra: str):
        original = root / "original.png"
        rendered = root / "rendered.png"
        output = root / "compare.png"
        write_png(str(original), original_rows)
        write_png(str(rendered), rendered_rows)
        result = subprocess.run(
            ["python3", str(SCRIPT), str(original), str(rendered), str(output), *extra],
            capture_output=True, text=True,
        )
        return result, output

    def test_three_argument_cli_reports_advisory_metrics_for_same_size_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, output = self.run_compare(
                root,
                [[(0, 0, 0), (255, 255, 255)]],
                [[(0, 0, 0), (255, 0, 0)]],
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("visual diff advisory", result.stderr)
            self.assertIn("mismatch 50.00%", result.stderr)
            self.assertTrue(output.is_file())

    def test_skips_metrics_for_different_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.png"
            rendered = root / "rendered.png"
            output = root / "compare.png"
            write_png(str(original), [[(0, 0, 0)]])
            write_png(str(rendered), [[(0, 0, 0), (0, 0, 0)]])
            result = subprocess.run(
                ["python3", str(SCRIPT), str(original), str(rendered), str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("metrics skipped", result.stderr)
            self.assertIn("regional diff metrics skipped", result.stderr)

    def test_writes_deterministic_heatmap_for_same_size_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            heatmap = root / "heatmap.png"
            result, _ = self.run_compare(
                root,
                [[(0, 0, 0), (0, 0, 0)]],
                [[(0, 0, 0), (255, 255, 255)]],
                "--heatmap", str(heatmap),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(rows_rgb(PNG(str(heatmap))), [[(0, 0, 0), (255, 0, 0)]])
            first_bytes = heatmap.read_bytes()

            second = root / "heatmap-second.png"
            result, _ = self.run_compare(
                root,
                [[(0, 0, 0), (0, 0, 0)]],
                [[(0, 0, 0), (255, 255, 255)]],
                "--heatmap", str(second),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(first_bytes, second.read_bytes())

    def test_scales_measured_frames_and_classifies_regions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            measure = root / "screen.json"
            measure.write_text(json.dumps({
                "screen": {"scale": 2},
                "elements": [
                    {"role": "AXButton", "label": "high", "frame":
                        {"x": 0, "y": 0, "width": 1, "height": 1}},
                    {"role": "AXCell", "label": "medium", "frame":
                        {"x": 1, "y": 0, "width": 2, "height": 1}},
                    {"role": "AXStaticText", "label": "low", "frame":
                        {"x": 3, "y": 0, "width": 1, "height": 1}},
                ],
            }), encoding="utf-8")
            original = [[(0, 0, 0)] * 8 for _ in range(2)]
            rendered = [[(255, 255, 255), (255, 255, 255), (255, 0, 0)]
                        + [(0, 0, 0)] * 5 for _ in range(2)]
            result, _ = self.run_compare(
                root, original, rendered, "--measure", str(measure),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('[high] element 0 role=AXButton label="high" frame_px=0,0,2,2',
                          result.stderr)
            self.assertIn('[medium] element 1 role=AXCell label="medium" frame_px=2,0,4,2',
                          result.stderr)
            self.assertIn('[low] element 2 role=AXStaticText label="low" frame_px=6,0,2,2',
                          result.stderr)
            self.assertIn("3 regions: high 1, medium 1, low 1", result.stderr)

    def test_repeated_masks_affect_metrics_and_heatmap_but_not_side_by_side(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            heatmap = root / "heatmap.png"
            result, output = self.run_compare(
                root,
                [[(0, 0, 0)] * 3],
                [[(255, 255, 255), (255, 255, 255), (0, 0, 0)]],
                "--mask", "0,0,1,1", "--mask", "1,0,1,1",
                "--heatmap", str(heatmap),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("mismatch 0.00%", result.stderr)
            self.assertIn("2/3 pixels excluded", result.stderr)
            self.assertIn("side-by-side evidence remains unmasked", result.stderr)
            self.assertEqual(rows_rgb(PNG(str(heatmap))),
                             [[MASKED_RGB, MASKED_RGB, (0, 0, 0)]])
            comparison = rows_rgb(PNG(str(output)))
            self.assertEqual(comparison[0][3 + 8], (255, 255, 255))

    def test_system_chrome_is_masked_only_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = [[(0, 0, 0)] * 10 for _ in range(10)]
            rendered = [[(255, 255, 255)] * 10]
            rendered += [[(0, 0, 0)] * 10 for _ in range(8)]
            rendered += [[(255, 255, 255)] * 10]

            default_result, _ = self.run_compare(root, original, rendered)
            self.assertEqual(default_result.returncode, 0, msg=default_result.stderr)
            self.assertIn("mismatch 20.00%", default_result.stderr)
            self.assertNotIn("system chrome masking", default_result.stderr)

            masked_result, _ = self.run_compare(
                root, original, rendered, "--mask-system-chrome",
            )
            self.assertEqual(masked_result.returncode, 0, msg=masked_result.stderr)
            self.assertIn("system chrome masking explicitly requested", masked_result.stderr)
            self.assertIn("mismatch 0.00%", masked_result.stderr)

    def test_clamps_partial_regions_and_skips_regions_outside_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            measure = root / "screen.json"
            measure.write_text(json.dumps({
                "screen": {"scale": 2},
                "elements": [
                    {"role": "AXOther", "label": "partial", "frame":
                        {"x": -1, "y": 0, "width": 2, "height": 1}},
                    {"role": "AXOther", "label": "outside", "frame":
                        {"x": 10, "y": 10, "width": 1, "height": 1}},
                ],
            }), encoding="utf-8")
            result, output = self.run_compare(
                root,
                [[(0, 0, 0)] * 4 for _ in range(2)],
                [[(0, 0, 0)] * 4 for _ in range(2)],
                "--measure", str(measure),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('label="partial" frame_px=0,0,2,2', result.stderr)
            self.assertIn('label="outside" — frame is outside image bounds', result.stderr)
            self.assertIn("1 regions: high 0, medium 0, low 1", result.stderr)
            self.assertTrue(output.is_file())

    def test_different_dimensions_skip_regional_metrics_and_heatmap_but_write_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            measure = root / "screen.json"
            heatmap = root / "heatmap.png"
            measure.write_text("{}", encoding="utf-8")
            result, output = self.run_compare(
                root,
                [[(0, 0, 0)]],
                [[(0, 0, 0), (0, 0, 0)]],
                "--measure", str(measure), "--heatmap", str(heatmap),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("regional diff metrics skipped", result.stderr)
            self.assertIn("diff heatmap skipped", result.stderr)
            self.assertTrue(output.is_file())
            self.assertFalse(heatmap.exists())


if __name__ == "__main__":
    unittest.main()
