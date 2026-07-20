"""clone_idb.sh target parsing — offline via CLONE_TARGETS_RAW fixture."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_idb.sh"

# One physical device (Booted) + one simulator, in `idb list-targets` format.
SAMPLE = (
    "iPhone 14 Pro | 00008120-0018 | Booted | device | iOS 27.0 | arm64e | No Companion Connected\n"
    "iPhone 17 Pro | 88277868-08BD | Booted | simulator | iOS 26.5 | x86_64 | /tmp/x.sock\n"
)


def run_targets(raw: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(raw)
        fixture = f.name
    try:
        env = {**os.environ, "CLONE_TARGETS_RAW": fixture}
        return subprocess.run(
            ["bash", str(SCRIPT), "targets"],
            capture_output=True, text=True, env=env,
        )
    finally:
        os.unlink(fixture)


class TestCloneIdbTargets(unittest.TestCase):
    def test_flags_physical_device_as_ok(self):
        r = run_targets(SAMPLE)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("OK: 00008120-0018", r.stdout)
        self.assertIn("device", r.stdout)

    def test_simulator_is_info_not_ok(self):
        r = run_targets(SAMPLE)
        self.assertIn("INFO: 88277868-08BD", r.stdout)
        # simulator udid must not be emitted as an OK (analysis) target
        self.assertNotIn("OK: 88277868-08BD", r.stdout)

    def test_warns_when_only_simulators(self):
        r = run_targets(
            "iPhone 17 Pro | SIM1 | Booted | simulator | iOS 26.5 | x86_64 | /tmp/x.sock\n"
        )
        self.assertIn("WARN:", r.stdout)


if __name__ == "__main__":
    unittest.main()
