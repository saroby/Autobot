"""Guard tests: the scaffold MUST emit a unit-test target + a scheme TestAction
so `xcodebuild test` (and thus check_logic_tests_pass) can run authored tests.

Pure generation tests — no xcodebuild/simulator. We invoke generate-pbxproj.py
directly and inspect the xcodegen project.yml that create-xcode-project.sh writes.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCAFFOLD = PLUGIN_DIR / "skills" / "autobot-ios-scaffold" / "scripts"
GEN_PBXPROJ = SCAFFOLD / "generate-pbxproj.py"
CREATE_SH = SCAFFOLD / "create-xcode-project.sh"


class TestPbxprojTestTarget(unittest.TestCase):
    def test_pbxproj_has_unit_test_target_and_test_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources = Path(tmp) / "Demo"
            sources.mkdir(parents=True)
            proc = subprocess.run(
                ["python3", str(GEN_PBXPROJ),
                 "--name", "Demo", "--bundle-id", "com.axi.demo",
                 "--sources-dir", str(sources)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            pbx = (Path(tmp) / "Demo.xcodeproj" / "project.pbxproj").read_text()
            # Unit-test target present
            self.assertIn("com.apple.product-type.bundle.unit-test", pbx)
            self.assertIn("DemoTests", pbx)
            self.assertIn("TEST_HOST", pbx)
            # Scheme test action present and references the test bundle
            scheme = (Path(tmp) / "Demo.xcodeproj" / "xcshareddata"
                      / "xcschemes" / "Demo.xcscheme").read_text()
            self.assertIn("<TestAction", scheme)
            self.assertIn("DemoTests.xctest", scheme)
            self.assertIn("<TestableReference", scheme)


class TestXcodegenProjectYmlScheme(unittest.TestCase):
    def test_project_yml_wires_test_scheme(self):
        # Force the xcodegen branch by faking an xcodegen on PATH that no-ops,
        # so create-xcode-project.sh writes project.yml then "generates".
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            (fake_bin / "xcodegen").write_text("#!/bin/bash\nexit 0\n")
            (fake_bin / "xcodegen").chmod(0o755)
            env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": tmp}
            proj = Path(tmp) / "out"
            proc = subprocess.run(
                ["bash", str(CREATE_SH),
                 "--name", "Demo", "--bundle-id", "com.axi.demo",
                 "--project-dir", str(proj)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            yml = (proj / "project.yml").read_text()
            self.assertIn("DemoTests", yml)
            self.assertIn("bundle.unit-test", yml)
            # GAP being closed: an explicit scheme wiring the test target.
            self.assertIn("schemes:", yml)
            self.assertIn("Demo:", yml.split("schemes:", 1)[1])
            self.assertIn("test:", yml.split("schemes:", 1)[1])


if __name__ == "__main__":
    unittest.main()
