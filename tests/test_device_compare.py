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

    def test_structural_similarity_agrees_with_and_without_a_mask(self):
        # The class mask hits every 8x8 window (x*y % 11 == 0 covers the whole
        # first row and column), so it also exercises the both-paths-say-None
        # case; the band mask leaves windows to actually average.
        band = [[y < 8 for _ in range(self.width)] for y in range(self.height)]
        for name, mask in (("none", None), ("band", band), ("everything", self.mask)):
            with self.subTest(mask=name):
                self.module._ARRAY_CACHE.clear()
                fast = self.module.structural_similarity(self.left, self.right, mask)
                slow = self.without_numpy(
                    lambda: self.module.structural_similarity(self.left, self.right, mask))
                if fast is None or slow is None:
                    self.assertIsNone(fast)
                    self.assertIsNone(slow)
                    continue
                self.assertEqual(fast[1], slow[1])
                self.assertAlmostEqual(fast[0], slow[0], places=9)

    def test_alignment_search_and_shift_agree(self):
        moved = [[self.left[max(0, y - 1)][max(0, x - 2)] for x in range(self.width)]
                 for y in range(self.height)]
        self.module._ARRAY_CACHE.clear()
        fast = self.module.best_offset(self.left, moved, 4)
        slow = self.without_numpy(lambda: self.module.best_offset(self.left, moved, 4))
        self.assertEqual(fast, slow)

        self.module._ARRAY_CACHE.clear()
        fast_rows = self.module.shift_rows(moved, -2, -1)
        slow_rows = self.without_numpy(lambda: self.module.shift_rows(moved, -2, -1))
        self.assertEqual([[tuple(pixel) for pixel in row] for row in fast_rows],
                         [[tuple(pixel) for pixel in row] for row in slow_rows])

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


class TestStructuralSimilarity(unittest.TestCase):
    """SSIM answers the question mismatch cannot: is the structure there.

    Pixel mismatch calls a correct-but-shifted screen broken and calls a screen
    with the right palette in the wrong arrangement fine. SSIM is the number
    that survives anti-aliasing and falls when content moves or disappears.
    """

    def noise(self, width: int, height: int, seed: int):
        import random
        generator = random.Random(seed)
        return [[tuple(generator.randrange(256) for _ in range(3))
                 for _ in range(width)] for _ in range(height)]

    def test_identical_images_score_one(self):
        from scripts.device_compare import structural_similarity

        rows = self.noise(32, 32, 11)
        score = structural_similarity(rows, [list(row) for row in rows])
        self.assertIsNotNone(score)
        self.assertAlmostEqual(score[0], 1.0, places=9)
        self.assertEqual(score[1], 16)

    def test_a_masked_window_is_dropped_whole(self):
        from scripts.device_compare import structural_similarity

        rows = self.noise(16, 16, 12)
        other = self.noise(16, 16, 13)
        # Exclude the top half: 8 rows is exactly one window band of the four.
        mask = [bytearray(b"\x01" * 16) if y < 8 else bytearray(16) for y in range(16)]
        full = structural_similarity(rows, other)
        masked = structural_similarity(rows, other, mask)
        self.assertEqual(full[1], 4)
        self.assertEqual(masked[1], 2)

    def test_returns_none_when_every_window_is_excluded(self):
        from scripts.device_compare import structural_similarity

        rows = self.noise(16, 16, 14)
        mask = [bytearray(b"\x01" * 16) for _ in range(16)]
        self.assertIsNone(structural_similarity(rows, rows, mask))

    def test_reported_on_the_command_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = self.noise(16, 16, 15)
            write_png(str(root / "a.png"), rows)
            write_png(str(root / "b.png"), rows)
            result = subprocess.run(
                ["python3", str(SCRIPT), str(root / "a.png"), str(root / "b.png"),
                 str(root / "out.png")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("structural similarity — SSIM 1.0000", result.stderr)


class TestAlignment(unittest.TestCase):
    """A screen that is right but sits a few points low differs in every pixel.

    Measuring before finding the shift describes the shift, not the screen —
    and the shift itself is a finding worth printing, because it means some
    inset or safe-area value is systematically wrong.
    """

    def shifted_pair(self, dx: int, dy: int):
        import random
        generator = random.Random(2026)
        rows = [[tuple(generator.randrange(256) for _ in range(3))
                 for _ in range(48)] for _ in range(48)]
        moved = [[rows[max(0, y - dy)][max(0, x - dx)] for x in range(48)]
                 for y in range(48)]
        return rows, moved

    def test_finds_the_translation_that_undoes_the_shift(self):
        from scripts.device_compare import best_offset

        rows, moved = self.shifted_pair(3, 2)
        self.assertEqual(best_offset(rows, moved, 8), (-3, -2))

    def test_reports_zero_for_an_aligned_pair(self):
        from scripts.device_compare import best_offset

        rows, _ = self.shifted_pair(0, 0)
        self.assertEqual(best_offset(rows, [list(row) for row in rows], 6), (0, 0))

    def test_align_collapses_the_mismatch_of_a_shifted_reproduction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows, moved = self.shifted_pair(3, 2)
            write_png(str(root / "a.png"), rows)
            write_png(str(root / "b.png"), moved)

            def mismatch(*extra: str) -> float:
                result = subprocess.run(
                    ["python3", str(SCRIPT), str(root / "a.png"), str(root / "b.png"),
                     str(root / "out.png"), *extra], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, msg=result.stderr)
                found = re.search(r"visual diff \w+ — mismatch ([\d.]+)%", result.stderr)
                self.assertIsNotNone(found, msg=result.stderr)
                return float(found.group(1))

            self.assertGreater(mismatch(), 90.0)
            self.assertLess(mismatch("--align", "6"), 30.0)


class TestScoreLog(unittest.TestCase):
    """A regression is only visible against what the same screen scored before."""

    def run_scored(self, root: Path, rendered_rows, *extra: str):
        original = [[(255, 0, 0)] * 16 for _ in range(16)]
        write_png(str(root / "original.png"), original)
        write_png(str(root / "rendered.png"), rendered_rows)
        return subprocess.run(
            ["python3", str(SCRIPT), str(root / "original.png"), str(root / "rendered.png"),
             str(root / "out.png"), "--score-log", str(root / "scores.jsonl"),
             "--label", "home", *extra],
            capture_output=True, text=True)

    def test_records_one_line_per_run_with_the_numbers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.run_scored(root, [[(255, 0, 0)] * 16 for _ in range(16)])
            entries = [json.loads(line)
                       for line in (root / "scores.jsonl").read_text().splitlines()]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["label"], "home")
            self.assertEqual(entries[0]["mismatch"], 0.0)
            self.assertEqual(entries[0]["ssim"], 1.0)
            self.assertTrue(entries[0]["passed"])

    def test_a_failing_gated_run_is_recorded_too(self):
        # A log of successes cannot show a regression, which is what it is for.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.run_scored(root, [[(0, 0, 255)] * 16 for _ in range(16)],
                                     "--max-mismatch", "0.10")
            self.assertEqual(result.returncode, 1)
            entry = json.loads((root / "scores.jsonl").read_text().splitlines()[-1])
            self.assertFalse(entry["passed"])
            self.assertTrue(entry["gated"])
            self.assertEqual(entry["mismatch"], 1.0)


class TestExclusions(unittest.TestCase):
    """Volatile pixels — a clock, an unread badge — are noise, not signal."""

    def test_excluded_regions_leave_the_score_and_are_echoed_with_their_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = [[(255, 0, 0)] * 20 for _ in range(20)]
            rendered = [[(255, 0, 0)] * 20 for _ in range(20)]
            for y in range(20):
                for x in range(10, 20):
                    rendered[y][x] = (0, 0, 255)
            write_png(str(root / "original.png"), original)
            write_png(str(root / "rendered.png"), rendered)
            (root / "exclusions.json").write_text(json.dumps({"regions": [
                {"x": 10, "y": 0, "width": 10, "height": 20, "reason": "clock"}]}),
                encoding="utf-8")
            result = subprocess.run(
                ["python3", str(SCRIPT), str(root / "original.png"),
                 str(root / "rendered.png"), str(root / "out.png"),
                 "--exclusions", str(root / "exclusions.json")],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("exclusion 1", result.stderr)
            self.assertIn("clock", result.stderr)
            self.assertIn("mismatch 0.00%", result.stderr)

    def test_an_unreadable_file_warns_instead_of_silently_excluding_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_png(str(root / "original.png"), [[(0, 0, 0)] * 4 for _ in range(4)])
            write_png(str(root / "rendered.png"), [[(0, 0, 0)] * 4 for _ in range(4)])
            result = subprocess.run(
                ["python3", str(SCRIPT), str(root / "original.png"),
                 str(root / "rendered.png"), str(root / "out.png"),
                 "--exclusions", str(root / "missing.json")],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("exclusions skipped", result.stderr)


class TestAssetCoverageBound(unittest.TestCase):
    """A crop is an asset; a crop the size of the screen is the original itself.

    Arming the mismatch gate without this makes pasting the capture in the
    single cheapest way to pass it.
    """

    def build(self, root: Path, crop_width: int):
        write_png(str(root / "original.png"), [[(255, 0, 0)] * 20 for _ in range(20)])
        write_png(str(root / "rendered.png"), [[(255, 0, 0)] * 20 for _ in range(20)])
        (root / "screen.json").write_text(json.dumps({
            "screen": {"points": {"width": 20, "height": 20},
                       "pixels": {"width": 20, "height": 20}, "scale": 1},
            "elements": [],
        }), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps({"assets": [{
            "sourceMeasurement": str(root / "screen.json"),
            "pixelBounds": {"x": 0, "y": 0, "width": crop_width, "height": 20},
        }]}), encoding="utf-8")

    def run_gated(self, root: Path, *extra: str):
        return subprocess.run(
            ["python3", str(SCRIPT), str(root / "original.png"), str(root / "rendered.png"),
             str(root / "out.png"), "--measure", str(root / "screen.json"),
             "--mask-assets", str(root / "manifest.json"), *extra],
            capture_output=True, text=True)

    def test_a_screen_sized_crop_fails_the_armed_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build(root, 18)  # 90% of the frame
            result = self.run_gated(root, "--max-mismatch", "0.30")
            self.assertEqual(result.returncode, 1)
            self.assertIn("not a reproduction that draws itself", result.stderr)

    def test_a_small_crop_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build(root, 4)  # 20% of the frame
            self.assertEqual(self.run_gated(root, "--max-mismatch", "0.30").returncode, 0)

    def test_it_only_warns_when_the_run_is_not_gating(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build(root, 18)
            result = self.run_gated(root)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("WARN:", result.stderr)
            self.assertIn("not a reproduction that draws itself", result.stderr)
