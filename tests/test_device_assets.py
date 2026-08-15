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
