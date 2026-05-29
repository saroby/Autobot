"""Regression: simulator selection must prefer the HIGHEST iOS runtime, not the
first device that matches a device name.

The bug (build-20260529 dogfood): `simctl list devices --json` returns runtimes
in an arbitrary order. Both env_snapshot._pick_simulator and
sim_runtime._pick_simulator_udid returned the first device named "iPhone 16 Pro"
regardless of its runtime version, landing on an iOS-18 sim. An app built for
iOS 26 cannot install on an iOS-18 simulator, so the Phase 5 runtime smoke +
axe functional flow silently failed/degraded — defeating the VERIFIED badge.

Selection contract:
  1. iPhones preferred over other device classes.
  2. Highest iOS runtime wins (version dominates name).
  3. deployment-target floor filters out runtimes too old to install the build.
  4. ensure() re-picks a cached snapshot whose runtime is below the floor.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import env_snapshot  # noqa: E402
import sim_runtime  # noqa: E402


# iOS-18-2 (with the legacy default device name) is listed BEFORE the iOS-26
# runtimes on purpose — that ordering is what tripped the old "first name match"
# logic. A higher-versioned iPad (26-5) is included to prove iPhone-preference
# does not get overridden by a newer non-iPhone.
def _listing() -> dict:
    return {
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                {"udid": "U-18-2-16PRO", "name": "iPhone 16 Pro", "isAvailable": True},
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [
                {"udid": "U-26-2-17PRO", "name": "iPhone 17 Pro", "isAvailable": True},
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                {"udid": "U-26-5-IPAD", "name": "iPad Pro 13-inch (M5)", "isAvailable": True},
            ],
            "com.apple.CoreSimulator.SimRuntime.iOS-15-4": [
                {"udid": "U-15-4-SE", "name": "iPhone SE (3rd generation)", "isAvailable": True},
            ],
            "com.apple.CoreSimulator.SimRuntime.tvOS-18-0": [
                {"udid": "U-TV", "name": "Apple TV", "isAvailable": True},
            ],
        }
    }


class TestSelectSimulatorFromListing(unittest.TestCase):
    def test_prefers_highest_ios_runtime_iphone(self) -> None:
        chosen = env_snapshot.select_simulator_from_listing(_listing())
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["udid"], "U-26-2-17PRO")
        self.assertIn("26-2", chosen["runtime"])

    def test_iphone_preferred_over_newer_ipad(self) -> None:
        # iPad on 26-5 is a higher runtime than iPhone on 26-2, but an iPhone
        # MVP wants an iPhone sim.
        chosen = env_snapshot.select_simulator_from_listing(_listing())
        self.assertEqual(chosen["name"], "iPhone 17 Pro")

    def test_min_runtime_floor_excludes_old(self) -> None:
        only_old = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                    {"udid": "U-18", "name": "iPhone 16 Pro", "isAvailable": True},
                ],
            }
        }
        self.assertIsNone(
            env_snapshot.select_simulator_from_listing(only_old, min_runtime=(26, 0))
        )

    def test_min_runtime_floor_keeps_qualifying(self) -> None:
        chosen = env_snapshot.select_simulator_from_listing(_listing(), min_runtime=(26, 0))
        self.assertEqual(chosen["udid"], "U-26-2-17PRO")

    def test_unavailable_devices_ignored(self) -> None:
        data = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-26-2": [
                    {"udid": "U-OFF", "name": "iPhone 17 Pro", "isAvailable": False},
                ],
                "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                    {"udid": "U-ON", "name": "iPhone 16 Pro", "isAvailable": True},
                ],
            }
        }
        chosen = env_snapshot.select_simulator_from_listing(data)
        self.assertEqual(chosen["udid"], "U-ON")  # only available one


class TestParseRuntimeVersion(unittest.TestCase):
    def test_identifier_form(self) -> None:
        self.assertEqual(
            env_snapshot._parse_runtime_version(
                "com.apple.CoreSimulator.SimRuntime.iOS-26-2"
            ),
            (26, 2),
        )

    def test_label_form(self) -> None:
        self.assertEqual(env_snapshot._parse_runtime_version("iOS 26.0"), (26, 0))

    def test_non_ios_returns_empty(self) -> None:
        self.assertEqual(
            env_snapshot._parse_runtime_version(
                "com.apple.CoreSimulator.SimRuntime.tvOS-18-0"
            ),
            (),
        )


class TestEnvSnapshotPicker(unittest.TestCase):
    def test_pick_simulator_uses_highest_runtime(self) -> None:
        def fake_which(name):
            return "/usr/bin/xcrun" if name == "xcrun" else None

        def fake_run(cmd, *, timeout=15):
            if "list" in cmd:
                return 0, json.dumps(_listing())
            return 127, ""

        with mock.patch.object(env_snapshot.shutil, "which", side_effect=fake_which), \
             mock.patch.object(env_snapshot, "_run", side_effect=fake_run):
            chosen = env_snapshot._pick_simulator()
        self.assertEqual(chosen["udid"], "U-26-2-17PRO")


class TestSimRuntimePicker(unittest.TestCase):
    def test_fallback_picker_uses_highest_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)  # no cached env_snapshot.json -> fallback path

            def fake_run(cmd, *, timeout=120):
                if "list" in cmd:
                    return 0, json.dumps(_listing()), ""
                return 127, "", ""

            with mock.patch.object(sim_runtime, "_run", side_effect=fake_run):
                udid, source = sim_runtime._pick_simulator_udid(proj)
        self.assertEqual(udid, "U-26-2-17PRO")
        self.assertIn("26-2", source)


class TestEnsureRevalidatesStaleRuntime(unittest.TestCase):
    def test_cached_runtime_below_deployment_target_is_repicked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            dot = proj / ".autobot"
            dot.mkdir()
            # Stale snapshot: an iOS-18 sim cached for an iOS-26 app.
            (dot / "env_snapshot.json").write_text(
                json.dumps(
                    {
                        "capturedAt": "2026-01-01T00:00:00Z",
                        "simulator": {
                            "udid": "U-18-2-16PRO",
                            "name": "iPhone 16 Pro",
                            "runtime": "com.apple.CoreSimulator.SimRuntime.iOS-18-2",
                        },
                        "environment": {"axe": True, "axeVersion": "1.7.0"},
                    }
                )
            )
            (dot / "build-state.json").write_text(json.dumps({"deploymentTarget": "26.0"}))

            def fake_which(name):
                return "/usr/bin/xcrun" if name in ("xcrun", "axe") else None

            def fake_run(cmd, *, timeout=15):
                if "list" in cmd and "--json" in cmd:
                    return 0, json.dumps(_listing())
                return 127, ""

            with mock.patch.object(env_snapshot.shutil, "which", side_effect=fake_which), \
                 mock.patch.object(env_snapshot, "_udid_still_available", return_value=True), \
                 mock.patch.object(env_snapshot, "_run", side_effect=fake_run):
                snap = env_snapshot.ensure(proj)
        # Must have re-picked onto a >= 26.0 runtime instead of trusting the
        # stale-but-still-available iOS-18 UDID.
        self.assertEqual(snap["simulator"]["udid"], "U-26-2-17PRO")


class TestDeploymentFloor(unittest.TestCase):
    def test_build_state_target_wins_over_global_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            dot = proj / ".autobot"
            dot.mkdir()
            (dot / "build-state.json").write_text(json.dumps({"deploymentTarget": "26.0"}))
            with mock.patch.object(
                env_snapshot, "_global_config_target", return_value=(99, 0)
            ):
                self.assertEqual(env_snapshot.deployment_floor(proj), (26, 0))

    def test_falls_back_to_global_config_when_state_lacks_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            dot = proj / ".autobot"
            dot.mkdir()
            # state exists but deploymentTarget is null (the init-state gap)
            (dot / "build-state.json").write_text(json.dumps({"appName": "X"}))
            with mock.patch.object(
                env_snapshot, "_global_config_target", return_value=(26, 0)
            ):
                self.assertEqual(env_snapshot.deployment_floor(proj), (26, 0))


if __name__ == "__main__":
    unittest.main()
