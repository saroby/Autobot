"""Regression lock for the concrete-destination requirement of the test action.

`xcodebuild test` rejects the generic "platform=iOS Simulator" destination
("Tests must be run on a concrete device"). integration_build must therefore
(a) refuse the test action without a concrete destination (degraded skip), and
(b) thread a passed destination into the xcodebuild argv. Caught by the cycle-2
feasibility spike against a real iOS 26 simulator.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import xcodebuild_runner as xr  # noqa: E402


class _Proc:
    returncode = 0
    stdout = ""
    stderr = ""


class TestIntegrationBuildDestination(unittest.TestCase):
    def test_test_action_without_destination_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"):
                r = xr.integration_build(Path(tmp), "App", test=True, destination=None)
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(r["skipReason"], "no_concrete_destination_for_test")

    def test_test_action_threads_concrete_destination(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", side_effect=fake_run):
                xr.integration_build(Path(tmp), "App", test=True, destination="id=ABC-123")

        cmd = captured["cmd"]
        self.assertIn("-destination", cmd)
        self.assertIn("id=ABC-123", cmd)
        self.assertIn("test", cmd)
        self.assertNotIn(xr.DEFAULT_DESTINATION, cmd)  # generic must NOT be used for test

    def test_build_action_defaults_to_generic_destination(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", side_effect=fake_run):
                xr.integration_build(Path(tmp), "App", test=False)

        cmd = captured["cmd"]
        self.assertIn(xr.DEFAULT_DESTINATION, cmd)
        self.assertIn("build", cmd)


if __name__ == "__main__":
    unittest.main()
