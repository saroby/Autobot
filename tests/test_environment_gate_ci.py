"""Regression: Gate 0 (environment_ready) must not HARD-require Xcode/iOS
simulator, so the stdlib unit suite stays green on no-Xcode CI (ubuntu-latest).

The bug: check_environment_ready probed `xcrun simctl` / `xcode-select` live and
hard-failed when absent. Every IsolatedProjectCase fixture runs `advance-phase 0`
(conftest setUp), so on CI's Ubuntu runner the gate hard-failed → the whole
fixture-based suite errored → CI was red on every push, despite ci.yml declaring
"Fast, no Xcode required".

Fix: honor AUTOBOT_DISABLE_SIMULATOR / AUTOBOT_DISABLE_XCODEBUILD as *degraded
skips* (mirroring sim_runtime.py / xcodebuild_runner.py), and have conftest set
them for all fixture subprocesses. Production (flags unset) keeps the live
fail-fast probe.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks import setup as setup_checks  # noqa: E402


def _probe(results: list[dict], name: str) -> dict:
    return next(r for r in results if r["check"] == name)


class TestEnvironmentReadyHardwareProbes(unittest.TestCase):
    """check_environment_ready honors the disable flags as degraded skips."""

    def setUp(self) -> None:
        # Simulate a host with no Xcode/simulator: every shell probe fails.
        patch = mock.patch.object(setup_checks, "_run_cmd", return_value=(False, "not found"))
        patch.start()
        self.addCleanup(patch.stop)
        for k in ("AUTOBOT_DISABLE_SIMULATOR", "AUTOBOT_DISABLE_XCODEBUILD"):
            os.environ.pop(k, None)
            self.addCleanup(lambda key=k: os.environ.pop(key, None))

    def _run(self) -> list[dict]:
        return setup_checks.check_environment_ready(Path("/tmp"), "App", {})

    def test_missing_simulator_is_hard_fail_without_flag(self):
        # Proves the probe is real: no flag + no hardware → hard fail (not skipped).
        sim = _probe(self._run(), "ios_simulator_runtime")
        self.assertFalse(sim["passed"])
        self.assertFalse(sim.get("skipped", False))

    def test_disable_simulator_degrades_instead_of_hard_fail(self):
        os.environ["AUTOBOT_DISABLE_SIMULATOR"] = "1"
        sim = _probe(self._run(), "ios_simulator_runtime")
        self.assertTrue(sim.get("skipped", False), "should be a skip, not a hard fail")
        self.assertTrue(sim.get("degraded", False))

    def test_disable_xcodebuild_degrades_xcode_cli_probe(self):
        os.environ["AUTOBOT_DISABLE_XCODEBUILD"] = "1"
        cli = _probe(self._run(), "xcode_cli_tools")
        self.assertTrue(cli.get("skipped", False))
        self.assertTrue(cli.get("degraded", False))


class TestConftestDecouplesFixture(unittest.TestCase):
    """The fixture decoupling: subprocess env carries the disable flags so Gate 0
    degrade-skips hardware probes on no-Xcode CI."""

    def test_scoped_env_sets_disable_flags(self):
        import conftest
        env = conftest._scoped_env(Path("/tmp"))
        self.assertEqual(env.get("AUTOBOT_DISABLE_SIMULATOR"), "1")
        self.assertEqual(env.get("AUTOBOT_DISABLE_XCODEBUILD"), "1")


if __name__ == "__main__":
    unittest.main()
