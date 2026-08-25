"""device_compare.py — side-by-side output plus advisory visual metrics."""

from __future__ import annotations

import json
import re
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

    def test_a_fully_masked_comparison_fails_the_gate(self):
        """Nothing left to compare is not a pass — it is an unverified screen.

        Masking is what makes the score meaningful, and masking everything is
        what makes it meaningless. Reporting success there is the hidden
        coverage the skill forbids: the screen was never checked.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, output = self.run_compare(
                root,
                [[(0, 0, 0), (255, 255, 255)]],
                [[(0, 0, 0), (255, 0, 0)]],
                "--mask", "0,0,2,1",
                "--max-mismatch", "0.30",
            )
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("no unmasked pixels", result.stderr)
            self.assertTrue(output.is_file())

    def test_mismatch_above_max_fails_the_gate(self):
        """A reproduction that does not look like the original must fail, not advise.

        `clone_run.sh polish` already counts a non-zero `device_compare.py` as a
        failure, so the convergence loop only exists once this exits non-zero.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result, output = self.run_compare(
                root,
                [[(0, 0, 0), (255, 255, 255)]],
                [[(0, 0, 0), (255, 0, 0)]],
                "--max-mismatch", "0.30",
            )
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            self.assertIn("exceeds", result.stderr)
            self.assertTrue(output.is_file(), "the side-by-side is the evidence for the failure")


if __name__ == "__main__":
    unittest.main()


class TestNumpyFastPathMatchesTheDefinition(unittest.TestCase):
    """The pure-Python loops ARE the metric; numpy is only allowed to be faster.

    This file is stdlib-only by design, so the accelerated path is optional and
    must be indistinguishable. A drift here would silently change every score in
    `clone_run.sh verify` on any machine that happens to have numpy installed.
    """

    def setUp(self):
        import random

        from scripts import device_compare

        self.module = device_compare
        if device_compare._np is None:
            self.skipTest("numpy is not installed — only the definition path exists here")
        random.seed(20260823)
        self.height, self.width = 37, 29
        self.left = [[tuple(random.randrange(256) for _ in range(3))
                      for _ in range(self.width)] for _ in range(self.height)]
        self.right = [[tuple(random.randrange(256) for _ in range(3))
                       for _ in range(self.width)] for _ in range(self.height)]
        self.mask = [[(x * y) % 11 == 0 for x in range(self.width)]
                     for y in range(self.height)]

    def without_numpy(self, call):
        saved = self.module._np
        self.module._np = None
        self.module._ARRAY_CACHE.clear()
        try:
            return call()
        finally:
            self.module._np = saved
            self.module._ARRAY_CACHE.clear()

    def test_metrics_agree_with_and_without_a_mask_and_bounds(self):
        for bounds in (None, (3, 5, 20, 30)):
            for mask in (None, self.mask):
                with self.subTest(bounds=bounds, masked=mask is not None):
                    self.module._ARRAY_CACHE.clear()
                    fast = self.module._detailed_metrics(self.left, self.right, mask, bounds)
                    slow = self.without_numpy(
                        lambda: self.module._detailed_metrics(
                            self.left, self.right, mask, bounds))
                    self.assertEqual(fast, slow)

    def test_heatmap_and_side_by_side_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def render(suffix: str) -> tuple[bytes, bytes]:
                heat = self.module._heatmap(self.left, self.right, self.mask)
                left = self.module.scale_to(self.left, 17, 23)
                right = self.module.scale_to(self.right, 17, 23)
                joined = self.module.join_side_by_side(
                    left, right, 4, self.module.DIVIDER_RGB)
                write_png(str(root / f"heat{suffix}.png"), heat)
                write_png(str(root / f"join{suffix}.png"), joined)
                return ((root / f"heat{suffix}.png").read_bytes(),
                        (root / f"join{suffix}.png").read_bytes())

            self.module._ARRAY_CACHE.clear()
            fast = render("-fast")
            slow = self.without_numpy(lambda: render("-slow"))
            self.assertEqual(fast, slow)


class TestAssetMasking(unittest.TestCase):
    """A crop is cut from the image the comparison measures against.

    Its region is ~0% mismatch by construction, so including it scores crop
    placement rather than reproduction — measured 2026-08-23, crops covered
    18-39% of several screens and accounted for the whole apparent improvement
    of that round.
    """

    def build(self, root: Path, drawn_crop: bool):
        original = [[(255, 0, 0)] * 20 for _ in range(20)]
        # Left half reproduced badly; right half either copied or not.
        rendered = [[(0, 0, 255)] * 20 for _ in range(20)]
        if drawn_crop:
            for y in range(20):
                for x in range(10, 20):
                    rendered[y][x] = (255, 0, 0)
        write_png(str(root / "original.png"), original)
        write_png(str(root / "rendered.png"), rendered)
        (root / "screen.json").write_text(json.dumps({
            "screen": {"points": {"width": 20, "height": 20},
                       "pixels": {"width": 20, "height": 20}, "scale": 1},
            "elements": [],
        }), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps({"assets": [{
            "sourceMeasurement": str(root / "screen.json"),
            "pixelBounds": {"x": 10, "y": 0, "width": 10, "height": 20},
        }]}), encoding="utf-8")

    def mismatch(self, root: Path, *extra: str) -> float:
        result = subprocess.run(
            ["python3", str(SCRIPT), str(root / "original.png"), str(root / "rendered.png"),
             str(root / "out.png"), "--measure", str(root / "screen.json"), *extra],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = re.search(r"visual diff advisory — mismatch ([\d.]+)%", result.stderr)
        self.assertIsNotNone(found, result.stderr)
        return float(found.group(1))

    def test_a_copied_region_flatters_the_total_until_it_is_masked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build(root, drawn_crop=True)
            self.assertAlmostEqual(self.mismatch(root), 50.0, places=1)
            masked = self.mismatch(root, "--mask-assets", str(root / "manifest.json"))
            # Everything the reproduction actually drew is wrong.
            self.assertAlmostEqual(masked, 100.0, places=1)

    def test_masking_only_removes_this_screens_crops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build(root, drawn_crop=True)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["assets"][0]["sourceMeasurement"] = "/elsewhere/other-screen.json"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertAlmostEqual(
                self.mismatch(root, "--mask-assets", str(root / "manifest.json")), 50.0, places=1)
