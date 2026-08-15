"""Unit coverage for deterministic clone screen post-processing."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import clone_postprocess  # noqa: E402
from device_compare import write_png  # noqa: E402


def write_pair(root: Path, stem: str, *, image: bool = False) -> tuple[Path, Path]:
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    xml = raw / f"{stem}.xml"
    role = "Image" if image else "StaticText"
    xml.write_text(
        '<?xml version="1.0"?><AppiumAUT>'
        '<XCUIElementTypeApplication type="XCUIElementTypeApplication" label="App" '
        'enabled="true" visible="true" x="0" y="0" width="4" height="4">'
        f'<XCUIElementType{role} type="XCUIElementType{role}" label="{stem}" '
        'enabled="true" visible="true" x="1" y="1" width="2" height="2"/>'
        '</XCUIElementTypeApplication></AppiumAUT>',
        encoding="utf-8",
    )
    png = raw / f"{stem}.png"
    write_png(str(png), [[(10, 20, 30)] * 4 for _ in range(4)])
    return xml, png


def measured(stem: str) -> dict:
    return {
        "source": {"tree": f"raw/{stem}.xml", "image": f"raw/{stem}.png"},
        "screen": {
            "points": {"width": 4, "height": 4},
            "pixels": {"width": 4, "height": 4},
            "scale": 1.0,
        },
        "elements": [{
            "role": "AXStaticText",
            "label": stem,
            "frame": {"x": 1, "y": 1, "width": 2, "height": 1},
            "layout": {"axis": "vstack", "spacing": 4},
            "colors": {"foreground": "#FFFFFF"},
        }],
        "unmeasurable": ["exact font family"],
    }


class TestClonePostprocess(unittest.TestCase):
    def test_unchanged_inputs_hit_measurement_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml, _ = write_pair(root, "home")
            with mock.patch.object(
                clone_postprocess.device_measure, "measure", return_value=measured("home")
            ) as first_measure:
                first = clone_postprocess.postprocess(root, workers=2)
            self.assertEqual((first.processed, first.cached, first.failed), (1, 0, 0))
            first_measure.assert_called_once()

            with mock.patch.object(
                clone_postprocess.device_measure,
                "measure",
                side_effect=AssertionError("cache hit must not remeasure"),
            ) as second_measure:
                second = clone_postprocess.postprocess(root, workers=2)
            self.assertEqual((second.processed, second.cached, second.failed), (0, 1, 0))
            second_measure.assert_not_called()

            xml.write_text(
                xml.read_text(encoding="utf-8").replace('label="home"', 'label="changed"'),
                encoding="utf-8",
            )
            with mock.patch.object(
                clone_postprocess.device_measure, "measure", return_value=measured("changed")
            ) as changed_measure:
                changed = clone_postprocess.postprocess(root, workers=2)
            self.assertEqual((changed.processed, changed.cached, changed.failed), (1, 0, 0))
            changed_measure.assert_called_once()

            spec = (root / "screens" / "home.md").read_text(encoding="utf-8")
            self.assertIn("## Sources", spec)
            self.assertIn("## Layout summary", spec)
            self.assertIn("## Elements", spec)
            self.assertIn("## Unmeasurable", spec)
            self.assertIn("Extracted assets: not generated for this run", spec)
            self.assertIn("AXStaticText", spec)

    def test_changed_screens_measure_in_parallel_with_worker_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stem in ("a", "b", "c", "d"):
                write_pair(root, stem)
            lock = threading.Lock()
            active = 0
            maximum = 0

            def fake_measure(xml: str, _png: str) -> dict:
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                time.sleep(0.04)
                with lock:
                    active -= 1
                return measured(Path(xml).stem)

            with mock.patch.object(clone_postprocess.device_measure, "measure", fake_measure):
                summary = clone_postprocess.postprocess(root, workers=2)

            self.assertEqual((summary.processed, summary.cached, summary.failed), (4, 0, 0))
            self.assertEqual(maximum, 2)
            self.assertEqual(
                sorted(path.name for path in (root / "screens").glob("*.json")),
                ["a.json", "b.json", "c.json", "d.json"],
            )

    def test_optional_asset_extraction_stage_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_pair(root, "gallery", image=True)
            gallery = measured("gallery")
            gallery["elements"][0]["role"] = "AXImage"

            with mock.patch.object(
                clone_postprocess.device_measure, "measure", return_value=gallery
            ):
                summary = clone_postprocess.postprocess(root, workers=1, extract_assets=True)

            self.assertEqual((summary.processed, summary.failed), (1, 0))
            manifest = json.loads((root / "assets" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["assets"]), 1)
            self.assertEqual(manifest["assets"][0]["element"]["role"], "AXImage")
            self.assertIn(
                "../assets/manifest.json",
                (root / "screens" / "gallery.md").read_text(encoding="utf-8"),
            )

    def test_missing_pair_is_a_reported_failure_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            (raw / "orphan.xml").write_text("<AppiumAUT/>", encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = clone_postprocess.main([str(root), "--workers", "2"])

            self.assertEqual(result, 1)
            self.assertIn("SUMMARY processed=0 cached=0 failed=1", stdout.getvalue())
            self.assertIn("missing PNG pair", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
