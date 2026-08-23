"""clone_device_project.py — the generated project carries the original app's name."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_device_project.py"


def generate(*extra: str) -> str:
    with tempfile.TemporaryDirectory() as temp:
        r = subprocess.run([sys.executable, str(SCRIPT), temp, "--name", "CloneApp",
                            "--bundle-id", "com.axi.clone.test", "--team", "ABCDE12345", *extra],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return (Path(temp) / "CloneApp.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")


class TestDisplayName(unittest.TestCase):
    def test_display_name_is_the_original_apps_name_not_the_target(self):
        pbx = generate("--display-name", "Threads")
        self.assertIn('INFOPLIST_KEY_CFBundleDisplayName = "Threads";', pbx)
        # The product (target, binary, bundle id) stays the clone's own.
        self.assertIn("PRODUCT_BUNDLE_IDENTIFIER = com.axi.clone.test;", pbx)
        self.assertIn('PRODUCT_NAME = "$(TARGET_NAME)";', pbx)

    def test_quotes_and_backslashes_in_a_name_do_not_break_the_pbxproj(self):
        pbx = generate("--display-name", 'My "App" \\ co')
        self.assertIn('INFOPLIST_KEY_CFBundleDisplayName = "My \\"App\\" \\\\ co";', pbx)

    def test_no_display_name_leaves_the_key_out(self):
        self.assertNotIn("CFBundleDisplayName", generate())


if __name__ == "__main__":
    unittest.main()
