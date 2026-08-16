"""device_measure.py — reproduction measurements, offline.

`/autobot:clone` writes SwiftUI from these numbers, so a wrong number becomes a
wrong layout. The multi-line case below is from a real Journal capture, where a
two-line label's frame height read as a 67pt largeTitle before the fix.

PNGs are built here with zlib so the color path is exercised without a fixture
binary or Pillow.
"""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_measure.py"


def png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A minimal single-color 8-bit RGB PNG."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def png_with_patch(width: int, height: int, background: tuple[int, int, int],
                   patch: tuple[int, int, int],
                   rect: tuple[int, int, int, int]) -> bytes:
    """Single-color PNG with one rectangular patch of another color."""
    px, py, pw, ph = rect

    def row(y: int) -> bytes:
        if py <= y < py + ph:
            return (b"\x00" + bytes(background) * px + bytes(patch) * pw
                    + bytes(background) * (width - px - pw))
        return b"\x00" + bytes(background) * width

    raw = b"".join(row(y) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def tree_xml(inner: str, w: int = 375, h: int = 812) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<AppiumAUT>'
        f'<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
        f' enabled="true" visible="true" x="0" y="0" width="{w}" height="{h}">'
        f'{inner}</XCUIElementTypeApplication></AppiumAUT>'
    )


def node(kind: str, label: str, x: int, y: int, w: int, h: int) -> str:
    return (f'<XCUIElementType{kind} type="XCUIElementType{kind}" label="{label}" name="{label}"'
            f' enabled="true" visible="true" x="{x}" y="{y}" width="{w}" height="{h}"/>')


def measure(inner: str, image: bytes | None = None) -> dict:
    with tempfile.TemporaryDirectory() as d:
        tree = Path(d) / "screen.xml"
        tree.write_text(tree_xml(inner), encoding="utf-8")
        argv = ["python3", str(SCRIPT), str(tree)]
        if image is not None:
            png = Path(d) / "screen.png"
            png.write_bytes(image)
            argv.append(str(png))
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        return json.loads(r.stdout)


class TestGeometry(unittest.TestCase):
    def test_frames_pass_through_in_points(self):
        d = measure(node("Button", "계속", 38, 722, 299, 52))
        btn = next(e for e in d["elements"] if e["label"] == "계속")
        self.assertEqual(btn["frame"], {"x": 38.0, "y": 722.0, "width": 299.0, "height": 52.0})

    def test_scale_links_points_to_pixels(self):
        d = measure(node("Button", "계속", 0, 0, 100, 40), png_bytes(1125, 2436, (0, 0, 0)))
        self.assertEqual(d["screen"]["scale"], 3.0)
        self.assertEqual(d["screen"]["points"]["width"], 375.0)

    def test_zero_sized_elements_are_dropped(self):
        d = measure(node("Other", "빈 것", 0, 0, 0, 0))
        self.assertNotIn("빈 것", [e["label"] for e in d["elements"]])


class TestTextStyle(unittest.TestCase):
    def test_single_line_snaps_to_an_ios_style(self):
        d = measure(node("StaticText", "통계", 0, 100, 60, 18))
        t = next(e for e in d["elements"] if e["label"] == "통계")["text"]
        self.assertEqual(t["iosTextStyle"], "footnote")

    def test_wrapped_label_is_divided_by_its_line_count(self):
        # Real capture: "0, 입력 항목\n올해" at h=90 estimated 66.7pt before the fix.
        d = measure(node("StaticText", "입력 항목&#10;올해", 0, 100, 120, 90))
        t = next(e for e in d["elements"] if "\n" in e["label"])["text"]
        self.assertEqual(t["lines"], 2)
        self.assertLess(t["estimatedPointSize"], 40)

    def test_impossibly_tall_text_reports_unreliable_instead_of_guessing(self):
        d = measure(node("StaticText", "한 줄인데 아주 큼", 0, 100, 200, 300))
        t = next(e for e in d["elements"] if e["label"].startswith("한 줄"))["text"]
        self.assertIsNone(t["iosTextStyle"])
        self.assertIn("unreliable", t["note"])

    def test_non_text_roles_get_no_text_estimate(self):
        d = measure(node("Button", "계속", 0, 100, 200, 44))
        self.assertNotIn("text", next(e for e in d["elements"] if e["label"] == "계속"))


class TestColor(unittest.TestCase):
    def test_samples_real_pixels(self):
        d = measure(node("Button", "계속", 10, 10, 100, 40), png_bytes(375, 812, (0x1B, 0x2C, 0x3D)))
        btn = next(e for e in d["elements"] if e["label"] == "계속")
        self.assertEqual(btn["colors"]["background"], "#1B2C3D")
        self.assertEqual(d["palette"][0]["hex"], "#1B2C3D")

    def test_without_an_image_geometry_still_works(self):
        d = measure(node("Button", "계속", 10, 10, 100, 40))
        self.assertIsNone(d["screen"]["pixels"])
        self.assertEqual(d["palette"], [])
        self.assertNotIn("colors", next(e for e in d["elements"] if e["label"] == "계속"))

    def test_broken_image_degrades_instead_of_crashing(self):
        d = measure(node("Button", "계속", 10, 10, 100, 40), b"not a png at all")
        self.assertTrue(any("colors unavailable" in u for u in d["unmeasurable"]))
        self.assertEqual(d["elements"][0]["frame"]["width"], 375.0)


class TestWrapperDropping(unittest.TestCase):
    """A real Journal screen carried 21 unlabelled full-screen wrappers."""

    def test_unlabelled_fullscreen_wrappers_are_dropped(self):
        d = measure(node("Other", "", 0, 0, 375, 812) + node("Button", "계속", 10, 700, 100, 44))
        self.assertEqual(d["droppedWrappers"], 1)
        # "App" is the application root the helper wraps everything in.
        self.assertEqual([e["label"] for e in d["elements"] if e["label"]], ["App", "계속"])

    def test_labelled_fullscreen_containers_survive(self):
        d = measure(node("CollectionView", "일기", 0, 0, 375, 812))
        self.assertIn("일기", [e["label"] for e in d["elements"]])

    def test_children_reattach_to_the_nearest_kept_ancestor(self):
        # Without the transitive remap, dropping a wrapper orphans its children
        # and every layout inference below it disappears.
        inner = (
            f'<XCUIElementTypeOther type="XCUIElementTypeOther" label="" enabled="true"'
            f' visible="true" x="0" y="0" width="375" height="812">'
            f'{node("Button", "위", 10, 100, 100, 40)}{node("Button", "아래", 10, 200, 100, 40)}'
            f'</XCUIElementTypeOther>'
        )
        d = measure(inner)
        self.assertEqual(d["droppedWrappers"], 1)
        kids = [e for e in d["elements"] if e["label"] in ("위", "아래")]
        self.assertEqual({e["parent"] for e in kids}, {0})  # the app root, not -1


class TestLayoutInference(unittest.TestCase):
    """The SKILL promises stack direction and spacing; this is where they come from."""

    def _stacked(self, coords: list[tuple[int, int]]) -> dict:
        inner = "".join(node("Button", f"b{i}", x, y, 80, 40) for i, (x, y) in enumerate(coords))
        return measure(inner)["elements"][0].get("layout", {})

    def test_vertical_children_are_a_vstack_with_measured_spacing(self):
        lay = self._stacked([(10, 100), (10, 160), (10, 220)])
        self.assertEqual(lay["axis"], "vstack")
        self.assertEqual(lay["spacing"], 20.0)  # 160-(100+40)

    def test_horizontal_children_are_an_hstack(self):
        lay = self._stacked([(10, 100), (110, 100), (210, 100)])
        self.assertEqual(lay["axis"], "hstack")
        self.assertEqual(lay["spacing"], 20.0)

    def test_overlapping_children_are_a_zstack(self):
        lay = self._stacked([(10, 100), (10, 100)])
        self.assertEqual(lay["axis"], "zstack")

    def test_slightly_overlapping_children_are_still_a_stack(self):
        # A live "0 / 개의 입력 항목" pair overlapped by 6pt and read as a zstack,
        # which loses the spacing the generated code needs.
        inner = (node("StaticText", "0", 28, 145, 37, 73)
                 + node("StaticText", "개의 입력 항목", 28, 212, 107, 16))
        self.assertEqual(measure(inner)["elements"][0]["layout"]["axis"], "vstack")

    def test_a_card_background_does_not_become_a_sibling_gap(self):
        # The full-size background overlaps every sibling; counting it reported
        # the row's gaps as "-343" instead of the real 14pt.
        inner = (
            '<XCUIElementTypeCell type="XCUIElementTypeCell" label="일기" name="일기"'
            ' enabled="true" visible="true" x="16" y="442" width="343" height="53">'
            + node("Other", "", 16, 442, 343, 53)          # the card's own background
            + node("Image", "아이콘", 30, 455, 28, 27)
            + node("StaticText", "일기", 72, 458, 30, 21)
            + '</XCUIElementTypeCell>'
        )
        cell = next(e for e in measure(inner)["elements"] if e["role"] == "AXCell")
        lay = cell["layout"]
        self.assertEqual(lay["axis"], "hstack")
        self.assertEqual(lay["gaps"], [14.0])

    def test_single_child_gets_no_layout(self):
        self.assertEqual(self._stacked([(10, 100)]), {})


class TestTextColor(unittest.TestCase):
    def test_no_foreground_when_the_frame_is_all_background(self):
        d = measure(node("StaticText", "통계", 10, 10, 100, 20), png_bytes(375, 812, (10, 10, 10)))
        colors = next(e for e in d["elements"] if e["label"] == "통계")["colors"]
        self.assertNotIn("foreground", colors)

    def test_buttons_get_no_foreground_sampling(self):
        d = measure(node("Button", "계속", 10, 10, 100, 40), png_bytes(375, 812, (10, 10, 10)))
        self.assertNotIn("foreground", next(e for e in d["elements"] if e["label"] == "계속")["colors"])


class TestControlFill(unittest.TestCase):
    """Corners and center both missed a floating action button's real color.

    On the live Journal screen the corner sampled the capsule behind it and the
    center sampled the white glyph; the blue fill was in neither.
    """

    def test_controls_report_a_dominant_interior_fill(self):
        d = measure(node("Button", "생성", 10, 10, 100, 40), png_bytes(375, 812, (0x6E, 0x7D, 0xFF)))
        self.assertEqual(next(e for e in d["elements"] if e["label"] == "생성")["colors"]["fill"],
                         "#6E7DFF")

    def test_text_gets_foreground_not_fill(self):
        d = measure(node("StaticText", "제목", 10, 10, 100, 20), png_bytes(375, 812, (10, 10, 10)))
        colors = next(e for e in d["elements"] if e["label"] == "제목")["colors"]
        self.assertNotIn("fill", colors)


class TestScreenNoise(unittest.TestCase):
    """All three came from one live Journal capture whose root layout read as
    'vstack, spacing 147' — four cards 16pt apart, drowned in chrome."""

    def test_scroll_bars_are_dropped(self):
        d = measure(node("Other", "수직 스크롤 막대, 1페이지", 342, 104, 30, 664)
                    + node("Button", "새로운 일기", 311, 402, 50, 41))
        self.assertEqual([e["label"] for e in d["elements"] if e["parent"] == 0], ["새로운 일기"])

    def test_scroll_bar_children_go_with_it(self):
        # The indicator itself carries no label, so only inheriting the parent's
        # verdict removes it — re-parenting put a 3pt bar among the cards.
        inner = (
            '<XCUIElementTypeOther type="XCUIElementTypeOther" label="수직 스크롤 막대, 1페이지"'
            ' name="s" enabled="true" visible="true" x="342" y="104" width="30" height="664">'
            + node("Other", "", 369, 370, 3, 395)
            + '</XCUIElementTypeOther>'
        )
        d = measure(inner)
        self.assertEqual([e["frame"]["width"] for e in d["elements"] if e["parent"] == 0], [])

    def test_the_same_element_twice_is_measured_once(self):
        # WDA reports two windows per screen, so every element arrives duplicated.
        d = measure(node("Cell", "일기", 16, 442, 343, 53) * 2)
        self.assertEqual([e["label"] for e in d["elements"]].count("일기"), 1)


class TestUncoveredRegions(unittest.TestCase):
    """The dominant clone failure is a missing element; a visible area no
    measured frame covers must surface as a warning, not stay silent."""

    BG = (255, 255, 255)
    INK = (30, 90, 200)

    def test_visible_content_without_an_element_is_flagged(self):
        image = png_with_patch(375, 812, self.BG, self.INK, (100, 400, 64, 64))
        d = measure(node("Button", "계속", 0, 100, 100, 40), image)
        regions = d["uncoveredRegions"]
        self.assertEqual(len(regions), 1, msg=str(regions))
        region = regions[0]
        self.assertTrue(80 <= region["x"] <= 110 and 380 <= region["y"] <= 410,
                        msg=str(region))

    def test_a_measured_element_covering_the_patch_clears_the_flag(self):
        image = png_with_patch(375, 812, self.BG, self.INK, (100, 400, 64, 64))
        d = measure(node("Other", "카드", 96, 396, 72, 72), image)
        self.assertEqual(d["uncoveredRegions"], [])

    def test_uniform_background_reports_nothing(self):
        d = measure(node("Button", "계속", 0, 100, 100, 40),
                    png_bytes(375, 812, self.BG))
        self.assertEqual(d["uncoveredRegions"], [])

    def test_system_chrome_bands_are_ignored(self):
        # Status bar content (top 7%) has no tree elements on most screens and
        # must not flag every capture.
        image = png_with_patch(375, 812, self.BG, self.INK, (100, 8, 64, 32))
        d = measure(node("Button", "계속", 0, 100, 100, 40), image)
        self.assertEqual(d["uncoveredRegions"], [])


class TestHonesty(unittest.TestCase):
    def test_declares_what_it_cannot_measure(self):
        d = measure(node("Image", "AppIcon", 0, 0, 60, 60))
        joined = " ".join(d["unmeasurable"])
        self.assertIn("binary assets", joined)
        self.assertIn("font", joined)


if __name__ == "__main__":
    unittest.main()
