"""device_idb.sh target parsing + device gate — offline via CLONE_TARGETS_RAW.

Tree parsing lives in device_a11y.py and is covered by test_device_a11y.py.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_idb.sh"

# One physical device (Booted) + one simulator, in `idb list-targets` format.
SAMPLE = (
    "iPhone 14 Pro | 00008120-0018 | Booted | device | iOS 27.0 | arm64e | No Companion Connected\n"
    "iPhone 17 Pro | 88277868-08BD | Booted | simulator | iOS 26.5 | x86_64 | /tmp/x.sock\n"
)


def run_with_targets(raw: str, *argv: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(raw)
        fixture = f.name
    try:
        env = {**os.environ, "CLONE_TARGETS_RAW": fixture}
        return subprocess.run(
            ["bash", str(SCRIPT), *argv],
            capture_output=True, text=True, env=env,
        )
    finally:
        os.unlink(fixture)


def run_targets(raw: str) -> subprocess.CompletedProcess:
    return run_with_targets(raw, "targets")


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


class TestCloneIdbDeviceGate(unittest.TestCase):
    """`device` is the hard precondition for agent-driven exploration."""

    def test_prints_bare_udid_on_stdout(self):
        r = run_with_targets(SAMPLE, "device")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        # stdout must be consumable as `udid=$(device_idb.sh device)`
        self.assertEqual(r.stdout.strip(), "00008120-0018")
        self.assertIn("OK: analysis device", r.stderr)

    def test_fails_when_no_physical_device(self):
        r = run_with_targets(
            "iPhone 17 Pro | SIM1 | Booted | simulator | iOS 26.5 | x86_64 | /tmp/x.sock\n",
            "device",
        )
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("ERROR: no physical device", r.stderr)

    def test_fails_when_multiple_devices_are_ambiguous(self):
        r = run_with_targets(
            "iPhone A | UDID-A | Booted | device | iOS 27.0 | arm64e | No Companion Connected\n"
            "iPhone B | UDID-B | Booted | device | iOS 27.0 | arm64e | No Companion Connected\n",
            "device",
        )
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("UDID-A", r.stderr)
        self.assertIn("UDID-B", r.stderr)


if __name__ == "__main__":
    unittest.main()
