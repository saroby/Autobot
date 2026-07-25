"""device_render.sh preconditions — offline, no simulator.

This script is what makes SKILL rule 4 ("no completion claim without a compare
image") executable, so its refusals matter: a silent failure here would let the
clone loop compare against a stale screenshot from a previous run.

Booting a simulator and rendering is verified against a real one instead (a live
Journal reproduction, 2026-07-25) — the checks below are the ones that must hold
without any device attached.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_render.sh"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True)


class TestRefusals(unittest.TestCase):
    def test_missing_arguments_print_usage(self):
        r = run(".", "HomeScreen")
        self.assertEqual(r.returncode, 1)
        self.assertIn("usage:", r.stderr)

    def test_missing_sources_directory(self):
        r = run("/nonexistent-sources", "HomeScreen", "sim", "/tmp/out.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such sources directory", r.stderr)

    def test_an_empty_sources_directory_names_the_step_that_fills_it(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d, "HomeScreen", "sim", "/tmp/out.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no .swift files", r.stderr)
        self.assertIn("Step 5", r.stderr)

    def test_uncompilable_views_fail_before_any_simulator_work(self):
        # The compiler diagnostic must survive to the caller: "swiftc failed"
        # alone does not say which line of generated SwiftUI is wrong.
        with tempfile.TemporaryDirectory() as d:
            Path(d, "Broken.swift").write_text(
                "import SwiftUI\nstruct Broken: View { var body: some View { Text(nope) } }\n",
                encoding="utf-8")
            r = run(d, "Broken", "no-such-simulator", "/tmp/out.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot find 'nope'", r.stdout + r.stderr)
        self.assertIn("swiftc failed", r.stderr)


if __name__ == "__main__":
    unittest.main()
