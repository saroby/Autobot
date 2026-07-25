"""device_capture.sh device enumeration — offline via CLONE_DEVICES_JSON fixture."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_capture.sh"


def run_devices(devices: list[dict]) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"result": {"devices": devices}}, f)
        fixture = f.name
    try:
        env = {**os.environ, "CLONE_DEVICES_JSON": fixture}
        return subprocess.run(
            ["bash", str(SCRIPT), "devices"],
            capture_output=True, text=True, env=env,
        )
    finally:
        os.unlink(fixture)


def _dev(reality: str, tunnel: str, udid: str, name: str) -> dict:
    return {
        "hardwareProperties": {"reality": reality, "udid": udid},
        "connectionProperties": {"tunnelState": tunnel},
        "deviceProperties": {"name": name},
    }


class TestCloneCapture(unittest.TestCase):
    def test_lists_only_physical_devices(self):
        r = run_devices([
            _dev("simulated", "connected", "SIM1", "iPhone 17 Pro"),
            _dev("physical", "connected", "PHYS1", "iPhone 14 Pro"),
        ])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("OK: PHYS1", r.stdout)
        self.assertIn("iPhone 14 Pro", r.stdout)
        self.assertNotIn("SIM1", r.stdout)

    def test_reports_tunnel_state(self):
        r = run_devices([_dev("physical", "unavailable", "PHYS1", "iPhone 14 Pro")])
        self.assertIn("unavailable", r.stdout)

    def test_warns_when_no_physical_device(self):
        r = run_devices([_dev("simulated", "connected", "SIM1", "iPhone 17 Pro")])
        self.assertIn("WARN:", r.stdout)


class TestShot4016Remedy(unittest.TestCase):
    """4016 failure branches on ddiServicesAvailable via a stubbed xcrun."""

    def _run_shot(self, ddi: bool):
        stub_dir = tempfile.mkdtemp()
        # Fake xcrun: any 'capture' invocation fails with 4016; anything else
        # (there is none here) exits 0. list-devices comes from the fixture.
        xcrun = Path(stub_dir) / "xcrun"
        xcrun.write_text(
            "#!/usr/bin/env bash\n"
            'echo "ERROR: ... CoreDeviceError error 4016 (0xFB0)" >&2\n'
            "exit 1\n"
        )
        xcrun.chmod(0o755)

        device = {
            "hardwareProperties": {"reality": "physical", "udid": "PHYS1"},
            "connectionProperties": {"tunnelState": "unavailable"},
            "deviceProperties": {"name": "iPhone 14 Pro", "ddiServicesAvailable": ddi},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"result": {"devices": [device]}}, f)
            fixture = f.name
        try:
            env = {
                **os.environ,
                "PATH": f"{stub_dir}:{os.environ['PATH']}",
                "CLONE_DEVICES_JSON": fixture,
            }
            return subprocess.run(
                ["bash", str(SCRIPT), "shot", "PHYS1", "/tmp/nope.png"],
                capture_output=True, text=True, env=env,
            )
        finally:
            os.unlink(fixture)

    def test_ddi_unavailable_points_to_developer_mode(self):
        r = self._run_shot(ddi=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Developer Mode", r.stderr)

    def test_ddi_available_points_to_unlock(self):
        r = self._run_shot(ddi=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unlock the iPhone", r.stderr)


if __name__ == "__main__":
    unittest.main()
