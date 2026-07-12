"""Tests for scripts/visual_contract.py — screenshot/palette validation
on synthetic fixtures so we exercise the deltaE / variance / size paths
without needing a real simulator launch.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from visual_contract import (  # noqa: E402
    DOMINANT_COLOR_TOLERANCE_DELTAE,
    MIN_SCREENSHOT_BYTES,
    evaluate,
)


def _png_noisy(width: int, height: int, base_rgb: tuple[int, int, int]) -> bytes:
    """Build a valid PNG dominated by `base_rgb` (75% of pixels) but with random
    noise on the remaining 25% so the compressed file lands above
    MIN_SCREENSHOT_BYTES and luminance variance is non-trivial."""
    import random

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    rng = random.Random(42)  # deterministic test fixture
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))

    # Mimic a real iOS screenshot: mostly the base color (UI surface), thin
    # bands of bright chrome (status bar + nav title), tiny amount of darker
    # text noise. Solid colors compress to ~2KB; this mix lands around 25-50KB
    # which is realistic for a downsampled simulator screenshot.
    rows: list[bytes] = []
    chrome = bytes((245, 245, 245))
    text = bytes((30, 30, 30))
    for y in range(height):
        row = [b"\x00"]
        is_chrome = (y % 40) < 2  # ~5% of rows are bright chrome
        for x in range(width):
            if is_chrome:
                row.append(chrome)
                continue
            # Sparse "text" pixels — break monochrome variance without flipping dominant
            if rng.random() < 0.04:
                row.append(text)
                continue
            row.append(bytes(base_rgb))
        rows.append(b"".join(row))
    raw = b"".join(rows)
    idat = chunk(b"IDAT", zlib.compress(raw, level=1))  # low compression keeps size up
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _seed_design_spec(project_root: Path, primary_hex: str) -> None:
    (project_root / ".autobot").mkdir(exist_ok=True)
    payload = {
        "version": 1, "appName": "X",
        "colorTokens": {
            "primary": primary_hex,
            # Pick non-competing palette tokens so the deltaE test isn't a coin flip:
            # secondary deep green, accent saturated orange, surface near-white.
            "secondary": "#0A5C32",
            "accent": "#FF7A1A",
            "surface": "#F5F6FA",
        },
        "typography": {"design": "rounded", "headingWeight": "semibold"},
        "spacing": {"base": 4, "card": 16, "section": 24},
        "visualAnchors": ["autobot.root"],
    }
    (project_root / ".autobot" / "design-spec.json").write_text(json.dumps(payload))


class TestEvaluate(unittest.TestCase):
    def test_missing_screenshot_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = evaluate(Path(tmp))
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["skipReason"], "screenshot_missing")

    def test_too_small_screenshot_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = proj / "tiny.png"
            shot.write_bytes(b"\x00" * (MIN_SCREENSHOT_BYTES // 2))
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "failed")
            self.assertIn("too small", result["reason"])

    def test_solid_blue_screenshot_with_matching_design_passes(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed — full-color analysis unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = proj / "big.png"
            # Large solid blue PNG: dimensions chosen so file > MIN_SCREENSHOT_BYTES.
            shot.write_bytes(_png_noisy(400, 600, (59, 91, 219)))  # #3B5BDB dominant + noise
            _seed_design_spec(proj, "#3B5BDB")
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "passed", result.get("reason"))
            self.assertIsNotNone(result.get("paletteMatch"))
            self.assertEqual(result["paletteMatch"]["closestToken"], "primary")
            self.assertLess(result["paletteMatch"]["deltaE"], DOMINANT_COLOR_TOLERANCE_DELTAE)

    def test_solid_red_screenshot_against_blue_design_fails_dominant(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = proj / "red.png"
            shot.write_bytes(_png_noisy(400, 600, (200, 30, 30)))  # red-dominant
            _seed_design_spec(proj, "#3B5BDB")  # blue expected
            result = evaluate(proj, screenshot=shot)
            # Palette mismatch is informational only (deltaE threshold uncalibrated
            # against real screenshots). The status passes; we surface the
            # mismatch via paletteWarning so the operator can see it in run-summary.
            self.assertEqual(result["status"], "passed")
            self.assertIsNotNone(result.get("paletteWarning"))
            self.assertIn("ΔE", result["paletteWarning"])
            self.assertGreater(
                result["paletteMatch"]["deltaE"],
                28,  # would have failed under the old strict gate
            )

    def test_disabled_via_env_skips(self):
        import os
        os.environ["AUTOBOT_DISABLE_VISUAL_CONTRACT"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = evaluate(Path(tmp))
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(result["skipReason"], "visual_contract_disabled")
        finally:
            del os.environ["AUTOBOT_DISABLE_VISUAL_CONTRACT"]


def _png_solid(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A single-color PNG stored UNCOMPRESSED so it exceeds MIN_SCREENSHOT_BYTES
    while having ~zero luminance variance (the monochrome regression shape)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    idat = chunk(b"IDAT", zlib.compress(raw, level=0))  # level 0 keeps size up
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


class TestEvaluateDarkMode(unittest.TestCase):
    """Dark-appearance render verification — the consumer of the (formerly
    dead) design-spec `darkMode` policy field."""

    def _light(self, proj: Path) -> Path:
        shot = proj / "shot.png"
        shot.write_bytes(_png_noisy(400, 600, (59, 91, 219)))
        _seed_design_spec(proj, "#3B5BDB")
        return shot

    def test_missing_dark_screenshot_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = self._light(proj)
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "passed", result.get("reason"))
            self.assertEqual(result["darkMode"]["status"], "skipped")
            self.assertEqual(result["darkMode"]["skipReason"], "dark_screenshot_missing")

    def test_monochrome_dark_render_fails_dark_check(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = self._light(proj)
            # All-black dark render — the broken-dark-mode regression.
            (proj / "shot-dark.png").write_bytes(_png_solid(200, 300, (0, 0, 0)))
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "passed")  # light render is fine
            self.assertEqual(result["darkMode"]["status"], "failed")
            self.assertIn("dark", result["darkMode"]["reason"])

    def test_healthy_dark_render_passes(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = self._light(proj)
            (proj / "shot-dark.png").write_bytes(_png_noisy(400, 600, (24, 26, 38)))
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["darkMode"]["status"], "passed", result["darkMode"])

    def test_dark_mode_false_opts_out(self):
        import json as _json
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            shot = self._light(proj)
            spec_path = proj / ".autobot" / "design-spec.json"
            payload = _json.loads(spec_path.read_text())
            payload["darkMode"] = False
            spec_path.write_text(_json.dumps(payload))
            (proj / "shot-dark.png").write_bytes(_png_solid(200, 300, (0, 0, 0)))
            result = evaluate(proj, screenshot=shot)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["darkMode"]["status"], "skipped")
            self.assertEqual(result["darkMode"]["skipReason"], "dark_mode_not_declared")


if __name__ == "__main__":
    unittest.main()
