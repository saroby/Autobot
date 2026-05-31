"""The screen-fill / layout-fidelity spine.

Covers the two halves that close the "low quality ships with every gate green"
hole for layout requirements:

  1. INTAKE (gate 1->2): when the user's verbatim idea asks for a screen-filling
     / pixel-fidelity layout, the feature-spec MUST encode it as an acceptance —
     `assess_idea_layout_capture` / `check_idea_layout_requirements_captured`.
  2. VERDICT (gate 5->6): the rendered screenshot must actually fill the screen —
     `visual_contract.evaluate` measures content bounding-box span and HARD-FAILS
     a letterboxed window when the idea required full-screen, while never touching
     apps that didn't ask for it.
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

import visual_contract  # noqa: E402
from intent_spec import (  # noqa: E402
    POSTCONDITION_KINDS,
    assess_idea_layout_capture,
    layout_intent_signal,
)


# --- minimal PNG writer (RGB, no filter) ------------------------------------
def _png(width: int, height: int, pixel) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    rows = []
    for y in range(height):
        row = [b"\x00"]
        for x in range(width):
            row.append(bytes(pixel(x, y)))
        rows.append(b"".join(row))
    # level=0 (stored) so solid fixtures still exceed MIN_SCREENSHOT_BYTES — the
    # downsampled occupancy analysis is unaffected by compression level.
    idat = chunk(b"IDAT", zlib.compress(b"".join(rows), level=0))
    return sig + ihdr + idat + chunk(b"IEND", b"")


# NOTE: use SOLID regions, not per-pixel noise — the occupancy analyzer
# downsamples (80x160), so high-frequency noise averages out to a flat blur
# (real screenshots have solid windows/bars that survive downsampling, which is
# exactly why a real letterboxed window is caught).
def _letterboxed_png(fill_fraction: float) -> bytes:
    """A solid window across the TOP `fill_fraction` of a tall frame; the rest is
    a solid dark letterbox — the classic fixed-window-in-a-void defect."""
    W, H = 300, 600
    cutoff = int(H * fill_fraction)
    bg = (20, 20, 24)

    def px(x, y):
        if y >= cutoff:
            return bg
        # window body with a couple of solid sub-bands so it isn't monochrome
        if y < cutoff * 0.25:
            return (60, 90, 180)      # title bar
        if (y // 8) % 2 == 0:
            return (150, 150, 158)    # chrome
        return (0, 200, 80)           # "LCD" strip
    return _png(W, H, px)


def _full_png() -> bytes:
    """Solid colored bands spanning the WHOLE height — a screen-filling app."""
    W, H = 300, 600
    bands = [(40, 60, 120), (150, 150, 158), (0, 170, 90), (200, 70, 70), (90, 90, 100)]

    def px(x, y):
        return bands[(y // 40) % len(bands)]
    return _png(W, H, px)


def _seed(project_root: Path, idea: str, features: list | None = None) -> None:
    a = project_root / ".autobot"
    a.mkdir(parents=True, exist_ok=True)
    (a / "build-state.json").write_text(json.dumps(
        {"buildId": "b1", "appName": "X", "idea": idea}))
    if features is not None:
        (a / "feature-spec.json").write_text(json.dumps({"features": features}))


_FILL_IDEA = "윈도우 윈앰프 UI 를 그대로. 탭없이 화면을 꽉 채우는 형태."
_PLAIN_IDEA = "a simple to-do list with categories"


class TestLayoutIntentSignal(unittest.TestCase):
    def test_detects_korean_and_english_fill_clauses(self):
        self.assertIsNotNone(layout_intent_signal(_FILL_IDEA))
        self.assertIsNotNone(layout_intent_signal("must be edge-to-edge full-screen"))
        self.assertIsNotNone(layout_intent_signal("pixel-perfect replica"))

    def test_ignores_apps_that_never_asked(self):
        self.assertIsNone(layout_intent_signal(_PLAIN_IDEA))
        self.assertIsNone(layout_intent_signal("track workouts and share with friends"))

    def test_layout_keywords_in_non_layout_sense_do_not_fire(self):
        # Regression: a bare layout keyword used in an unrelated sense must NOT
        # be read as a screen-fill clause — otherwise gate 1->2 forces a bogus
        # occupies_screen_fraction P0 and the autonomous build halts on an app
        # that never asked to fill the screen.
        self.assertIsNone(layout_intent_signal("입력한 메모를 그대로 저장하는 앱"))
        self.assertIsNone(layout_intent_signal("정확히 그대로 복사해 붙여넣기"))
        self.assertIsNone(layout_intent_signal("픽셀 아트를 그리는 드로잉 앱"))
        self.assertIsNone(layout_intent_signal("fill out the registration form quickly"))
        self.assertIsNone(layout_intent_signal("save exactly the same data each time"))

    def test_layout_keywords_in_layout_context_still_fire(self):
        # …but the SAME words DO count when they carry a layout/fidelity meaning.
        self.assertIsNotNone(layout_intent_signal("윈앰프 UI 를 그대로 재현"))
        self.assertIsNotNone(layout_intent_signal("디자인 그대로 옮겨줘"))
        self.assertIsNotNone(layout_intent_signal("픽셀 단위로 동일하게"))
        self.assertIsNotNone(layout_intent_signal("fills the screen completely"))
        self.assertIsNotNone(layout_intent_signal("looks exactly like Winamp"))

    def test_new_postcondition_kinds_registered(self):
        self.assertIn("occupies_screen_fraction", POSTCONDITION_KINDS)
        self.assertIn("matches_visual_reference", POSTCONDITION_KINDS)


class TestIdeaLayoutCapture(unittest.TestCase):
    def test_fill_idea_without_layout_acceptance_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _FILL_IDEA, features=[{
                "id": "playback", "title": "Play", "priority": "P0",
                "screen": "Main", "anchor": "autobot.primaryCTA",
                "acceptance": [{"id": "p", "kind": "flow",
                                "steps": [{"action": "tap", "anchor": "autobot.primaryCTA"}],
                                "postcondition": {"kind": "setting_stored", "params": {}}}],
            }])
            ok, problems = assess_idea_layout_capture(proj)
            self.assertFalse(ok)
            self.assertTrue(problems)

    def test_fill_idea_with_layout_acceptance_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _FILL_IDEA, features=[{
                "id": "fullscreen-window", "title": "Full-screen player window",
                "priority": "P0", "screen": "Main", "anchor": "autobot.root",
                "acceptance": [{"id": "fills", "kind": "flow", "steps": [],
                                "postcondition": {"kind": "occupies_screen_fraction",
                                                  "params": {"min": 0.85, "axis": "both"}}}],
            }])
            ok, problems = assess_idea_layout_capture(proj)
            self.assertTrue(ok, problems)

    def test_plain_idea_benign_passes_without_layout_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _PLAIN_IDEA, features=[{
                "id": "add", "title": "Add", "priority": "P0", "screen": "List",
                "anchor": "autobot.primaryCTA",
                "acceptance": [{"id": "a", "kind": "flow",
                                "steps": [{"action": "tap", "anchor": "autobot.primaryCTA"}],
                                "postcondition": {"kind": "count_increased", "params": {}}}],
            }])
            ok, problems = assess_idea_layout_capture(proj)
            self.assertTrue(ok, problems)


class TestOccupancyGate(unittest.TestCase):
    def setUp(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed — occupancy analysis unavailable")

    def test_letterboxed_window_with_fill_idea_hard_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _FILL_IDEA)  # idea-signal path (no feature-spec needed)
            shot = proj / "shot.png"
            shot.write_bytes(_letterboxed_png(0.15))  # window fills top 15%
            r = visual_contract.evaluate(proj, screenshot=shot)
            self.assertEqual(r["status"], "failed", r)
            self.assertIn("screen-fill", r["reason"])
            self.assertIsNotNone(r.get("fillRequirement"))
            self.assertFalse(r["fillRequirement"]["met"])

    def test_full_screen_with_fill_idea_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _FILL_IDEA)
            shot = proj / "shot.png"
            shot.write_bytes(_full_png())
            r = visual_contract.evaluate(proj, screenshot=shot)
            self.assertEqual(r["status"], "passed", r.get("reason"))
            self.assertTrue(r["fillRequirement"]["met"])

    def test_letterboxed_window_without_fill_idea_passes(self):
        # An app that never asked to fill the screen is NEVER failed on occupancy.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, _PLAIN_IDEA)
            shot = proj / "shot.png"
            shot.write_bytes(_letterboxed_png(0.15))
            r = visual_contract.evaluate(proj, screenshot=shot)
            self.assertEqual(r["status"], "passed", r.get("reason"))
            self.assertIsNone(r.get("fillRequirement"))


if __name__ == "__main__":
    unittest.main()
