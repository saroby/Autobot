"""Dark-appearance screenshot capture in sim_runtime.smoke.

The design-spec `darkMode` policy was write-only (no consumer). smoke() now
captures a second screenshot under `simctl ui <udid> appearance dark` so
visual_contract can verify the dark render. The capture is best-effort:
hosts whose simctl lacks the `ui` subcommand degrade gracefully (no dark
shot, smoke still passes) and the appearance is always restored to light.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import sim_runtime  # noqa: E402

UDID = "U-TEST"
BUNDLE = "com.test.demo"


class TestDarkScreenshotCapture(unittest.TestCase):
    def _smoke(self, *, ui_supported: bool) -> tuple[dict, list[list[str]]]:
        calls: list[list[str]] = []

        def fake_run(cmd, *, timeout=120):
            calls.append(list(cmd))
            if len(cmd) > 3 and cmd[2] == "ui":  # xcrun simctl ui <udid> appearance <mode>
                return (0, "", "") if ui_supported else (1, "", "Unsupported")
            return 0, "", ""

        def fake_capture(udid, dest: Path) -> bool:
            calls.append(["_capture", str(dest)])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"\x89PNG" + b"\x00" * 2048)
            return True

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            with mock.patch.object(sim_runtime, "_simctl_available", return_value=True), \
                 mock.patch.object(sim_runtime, "_pick_simulator_udid", return_value=(UDID, "cached")), \
                 mock.patch.object(sim_runtime, "_find_built_app", return_value=proj / "Demo.app"), \
                 mock.patch.object(sim_runtime, "_resolve_bundle_id", return_value=BUNDLE), \
                 mock.patch.object(sim_runtime, "_boot", return_value=(True, "booted")), \
                 mock.patch.object(sim_runtime, "_is_process_alive", return_value=(True, "pid=5")), \
                 mock.patch.object(sim_runtime, "_capture_screenshot", side_effect=fake_capture), \
                 mock.patch.object(sim_runtime, "_run", side_effect=fake_run), \
                 mock.patch.object(sim_runtime.time, "sleep", lambda *_: None):
                result = sim_runtime.smoke(proj, "Demo")
        return result, calls

    def test_dark_screenshot_captured_and_light_restored(self):
        result, calls = self._smoke(ui_supported=True)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["darkScreenshotCaptured"])
        self.assertTrue(result["darkScreenshotPath"].endswith("screenshot-dark.png"))
        # Both light and dark screenshots were captured.
        captures = [c[1] for c in calls if c[0] == "_capture"]
        self.assertEqual(len(captures), 2)
        self.assertTrue(captures[1].endswith("screenshot-dark.png"))
        # Appearance switched to dark, then restored to light (later steps —
        # flow_runner, visual judge — must keep operating on light).
        ui_modes = [c[-1] for c in calls if len(c) > 3 and c[2] == "ui"]
        self.assertEqual(ui_modes, ["dark", "light"])

    def test_unsupported_simctl_ui_degrades_gracefully(self):
        result, calls = self._smoke(ui_supported=False)
        self.assertEqual(result["status"], "passed")   # smoke never fails on this
        self.assertFalse(result["darkScreenshotCaptured"])
        self.assertIsNone(result["darkScreenshotPath"])
        captures = [c[1] for c in calls if c[0] == "_capture"]
        self.assertEqual(len(captures), 1)             # only the light shot


if __name__ == "__main__":
    unittest.main()
