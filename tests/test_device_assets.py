"""Unit coverage for screenshot-backed clone asset extraction."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import device_assets  # noqa: E402
from device_compare import write_png  # noqa: E402
from device_measure import PNG  # noqa: E402


def measurement(path: Path, screenshot: Path, elements: list[dict], scale: float = 1.0) -> None:
    value = {
        "source": {"tree": str(screenshot.with_suffix(".xml")), "image": str(screenshot)},
        "screen": {
            "points": {"width": 4, "height": 4},
            "pixels": {"width": 8, "height": 8},
            "scale": scale,
        },
        "elements": elements,
        "unmeasurable": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TestDeviceAssets(unittest.TestCase):
    def test_crop_geometry_uses_point_to_pixel_scale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "source.png"
            rows = [[(x, y, 0) for x in range(8)] for y in range(8)]
            write_png(str(screenshot), rows)
            measured = root / "screens" / "home.json"
            measurement(measured, screenshot, [{
                "role": "AXImage",
                "label": "avatar",
                "frame": {"x": 0.5, "y": 1, "width": 2, "height": 1.5},
            }], scale=2.0)

            result = device_assets.extract_assets(measured, assets_dir=root / "assets")

            self.assertEqual((result["selected"], result["unique"]), (1, 1))
            output = root / "assets" / result["entries"][0]["outputPath"]
            crop = PNG(str(output))
            self.assertEqual((crop.width, crop.height), (4, 3))
            self.assertEqual(crop.hex_at(0, 0), "#010200")
            self.assertEqual(crop.hex_at(3, 2), "#040400")
            self.assertEqual(
                result["entries"][0]["pixelBounds"],
                {"x": 1, "y": 2, "width": 4, "height": 3},
            )

    def test_selected_index_can_add_a_non_image_element(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screenshot = root / "source.png"
            write_png(str(screenshot), [[(1, 2, 3)] * 4 for _ in range(4)])
            measured = root / "screens" / "home.json"
            measurement(measured, screenshot, [{
                "role": "AXOther",
                "label": "custom drawing",
                "frame": {"x": 0, "y": 0, "width": 2, "height": 2},
            }])

            result = device_assets.extract_assets(
                measured, assets_dir=root / "assets", indices={0}
            )

            self.assertEqual(result["selected"], 1)
            self.assertEqual(result["entries"][0]["element"]["role"], "AXOther")

    def test_deduplicates_crops_merges_manifest_and_writes_valid_imagesets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            catalog = root / "Assets.xcassets"
            red = root / "red.png"
            write_png(str(red), [[(255, 0, 0)] * 4 for _ in range(2)])
            first = root / "screens" / "first.json"
            measurement(first, red, [
                {"role": "AXImage", "label": "left", "frame": {"x": 0, "y": 0, "width": 2, "height": 2}},
                {"role": "AXImage", "label": "right", "frame": {"x": 2, "y": 0, "width": 2, "height": 2}},
            ])

            first_result = device_assets.extract_assets(
                first, assets_dir=assets, assets_catalog=catalog
            )

            self.assertEqual(first_result["unique"], 1)
            self.assertEqual(len(list((assets / "crops").glob("*.png"))), 1)
            self.assertEqual(
                first_result["entries"][0]["sha256"], first_result["entries"][1]["sha256"]
            )
            self.assertEqual(len(list(catalog.glob("*.imageset"))), 1)
            imageset = next(catalog.glob("*.imageset"))
            contents = json.loads((imageset / "Contents.json").read_text(encoding="utf-8"))
            self.assertEqual(contents["info"], {"author": "xcode", "version": 1})
            self.assertEqual(contents["images"][0]["idiom"], "universal")
            self.assertEqual(contents["images"][0]["scale"], "1x")
            self.assertTrue((imageset / contents["images"][0]["filename"]).is_file())

            blue = root / "blue.png"
            write_png(str(blue), [[(0, 0, 255)] * 2 for _ in range(2)])
            second = root / "screens" / "second.json"
            measurement(second, blue, [{
                "role": "AXImage",
                "label": "blue",
                "frame": {"x": 0, "y": 0, "width": 2, "height": 2},
            }])
            device_assets.extract_assets(second, assets_dir=assets, assets_catalog=catalog)
            device_assets.extract_assets(first, assets_dir=assets, assets_catalog=catalog)

            manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["scope"], "research-only")
            self.assertEqual(len(manifest["assets"]), 3)
            self.assertEqual(len({entry["sha256"] for entry in manifest["assets"]}), 2)
            for entry in manifest["assets"]:
                self.assertEqual(entry["method"], "capture-crop")
                self.assertIn("Screenshot crop only", entry["qualityCaveat"])
                self.assertTrue((assets / entry["outputPath"]).is_file())


if __name__ == "__main__":
    unittest.main()


class TestAutoSelection(unittest.TestCase):
    """What gets cut out of the capture, and what must not.

    An icon exists in the accessibility tree only as a description ("좋아요.
    226명이 이 게시물을 좋아합니다."), never as a picture, so no measurement can
    reproduce it — every action icon, tab icon and top-bar control rendered as
    nothing. A capture crop is the documented research-only path for those.
    Text is the opposite: it IS measured, so pasting it would draw the same
    words twice.
    """

    def select(self, elements: list[dict]) -> set[int]:
        return device_assets._auto_selected(elements)

    def element(self, **overrides) -> dict:
        base = {"role": "AXButton", "label": "", "parent": -1,
                "frame": {"x": 0.0, "y": 0.0, "width": 24.0, "height": 24.0}}
        base.update(overrides)
        return base

    def test_an_icon_sized_leaf_control_is_cut_out(self):
        elements = [self.element(label="좋아요. 226명이 이 게시물을 좋아합니다.",
                                 frame={"x": 60.0, "y": 236.0, "width": 37.0, "height": 34.0})]
        self.assertEqual(self.select(elements), {0})

    def test_an_image_is_still_cut_out_at_any_size(self):
        elements = [self.element(role="AXImage",
                                 frame={"x": 0.0, "y": 0.0, "width": 300.0, "height": 300.0})]
        self.assertEqual(self.select(elements), {0})

    def test_a_control_with_children_is_not_a_leaf(self):
        elements = [self.element(), self.element(parent=0)]
        self.assertNotIn(0, self.select(elements))

    def test_a_control_repeating_measured_text_is_not_pasted(self):
        # The words are already reproduced from the AXStaticText; pasting the
        # control would draw them a second time.
        elements = [
            self.element(label="모두 보기"),
            {"role": "AXStaticText", "label": "모두 보기", "parent": -1,
             "text": {"estimatedPointSize": 14.0},
             "frame": {"x": 0.0, "y": 0.0, "width": 60.0, "height": 18.0}},
        ]
        self.assertEqual(self.select(elements), set())

    def test_a_control_too_large_to_be_an_icon_is_left_alone(self):
        elements = [self.element(
            frame={"x": 0.0, "y": 0.0, "width": 375.0, "height": 80.0})]
        self.assertEqual(self.select(elements), set())

    def test_an_invisible_element_is_never_cut_out(self):
        self.assertEqual(self.select([self.element(visible=False)]), set())


class TestUncoveredRegions(unittest.TestCase):
    """Pixels no leaf element accounts for are cut out too.

    Threads exposes a post avatar to no accessibility element at all — the
    measurement cannot see it and the reproduction drew nothing there, leaving a
    column of empty space beside every post. The scan finds those pixels; this
    is what turns them into something the reproduction can draw.
    """

    def test_an_uncovered_region_becomes_a_crop_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shot = root / "shot.png"
            write_png(str(shot), [[(10, 10, 10)] * 40 for _ in range(40)])
            path = root / "screen.json"
            measurement(path, shot, [
                {"role": "AXApplication", "label": "", "parent": -1,
                 "frame": {"x": 0.0, "y": 0.0, "width": 40.0, "height": 40.0},
                 "colors": {}},
            ])
            data = json.loads(path.read_text(encoding="utf-8"))
            data["uncoveredRegions"] = [
                {"x": 8.0, "y": 12.0, "width": 16.0, "height": 16.0, "blocks": 4}]
            path.write_text(json.dumps(data), encoding="utf-8")

            device_assets.extract_assets(path, assets_dir=root / "assets")
            entries = json.loads(
                (root / "assets" / "manifest.json").read_text(encoding="utf-8"))["assets"]
            uncovered = [e for e in entries
                         if (e.get("element") or {}).get("role") == "uncoveredRegion"]
            self.assertEqual(len(uncovered), 1)
            # Negative index so it cannot collide with a measured element.
            self.assertLess(uncovered[0]["element"]["index"], 0)
            self.assertEqual(uncovered[0]["element"]["frame"],
                             {"x": 8.0, "y": 12.0, "width": 16.0, "height": 16.0})
            self.assertTrue((root / "assets" / uncovered[0]["outputPath"]).is_file())


class TestDecorativeLeaves(unittest.TestCase):
    """A label-less wrapper whose pixels are not flat.

    The Threads wordmark lives in an empty `AXOther` leaf: no label to identify
    it, no role that says "control", and it covers the region so the
    uncovered-pixel scan stays quiet too. A solid fill is all the measurement
    has for it, and the top bar rendered as empty space.
    """

    def build(self, root: Path, patch: bool):
        shot = root / "shot.png"
        rows = [[(10, 10, 10)] * 40 for _ in range(40)]
        if patch:
            for y in range(12, 20):
                for x in range(12, 20):
                    rows[y][x] = (240, 240, 240)
        write_png(str(shot), rows)
        path = root / "screen.json"
        measurement(path, shot, [
            {"role": "AXApplication", "label": "", "parent": -1,
             "frame": {"x": 0.0, "y": 0.0, "width": 40.0, "height": 40.0}, "colors": {}},
            {"role": "AXOther", "label": "", "parent": 0,
             "frame": {"x": 10.0, "y": 10.0, "width": 20.0, "height": 20.0}, "colors": {}},
        ])
        return path

    def selected(self, path: Path) -> set:
        data = json.loads(path.read_text(encoding="utf-8"))
        return device_assets._auto_selected(
            data["elements"], PNG(str(path.parent / "shot.png")), data["screen"]["scale"])

    def test_a_wrapper_with_a_glyph_in_it_is_cut_out(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.selected(self.build(Path(directory), patch=True)), {1})

    def test_a_flat_wrapper_is_left_to_its_measured_fill(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.selected(self.build(Path(directory), patch=False)), set())
