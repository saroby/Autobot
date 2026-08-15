"""device_compare.py — side-by-side output plus advisory visual metrics."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.device_compare import write_png


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_compare.py"


class TestDeviceCompare(unittest.TestCase):
    def test_reports_advisory_metrics_for_same_size_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.png"
            rendered = root / "rendered.png"
            output = root / "compare.png"
            write_png(str(original), [[(0, 0, 0), (255, 255, 255)]])
            write_png(str(rendered), [[(0, 0, 0), (255, 0, 0)]])
            result = subprocess.run(
                ["python3", str(SCRIPT), str(original), str(rendered), str(output)],
                capture_output=True, text=True,
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


if __name__ == "__main__":
    unittest.main()
