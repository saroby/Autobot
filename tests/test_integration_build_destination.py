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
import plistlib
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import xcodebuild_runner as xr  # noqa: E402


class _Proc:
    returncode = 0
    stdout = ""
    stderr = ""


MACH_O_64_LE = bytes.fromhex("cffaedfe")


def _emit_built_app(cmd: list[str], app_name: str = "App") -> Path:
    derived = Path(cmd[cmd.index("-derivedDataPath") + 1])
    app = derived / "Build" / "Products" / "Debug-iphonesimulator" / f"{app_name}.app"
    app.mkdir(parents=True, exist_ok=True)
    (app / app_name).write_bytes(MACH_O_64_LE + b"\x00" * 28)
    with (app / "Info.plist").open("wb") as f:
        plistlib.dump({
            "CFBundleIdentifier": "com.example.app",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "CFBundleExecutable": app_name,
        }, f)
    return app


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
            _emit_built_app(cmd)
            return _Proc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", side_effect=fake_run):
                result = xr.integration_build(Path(tmp), "App", test=True, destination="id=ABC-123")

        cmd = captured["cmd"]
        self.assertIn("-destination", cmd)
        self.assertIn("id=ABC-123", cmd)
        self.assertIn("test", cmd)
        self.assertNotIn(xr.DEFAULT_DESTINATION, cmd)  # generic must NOT be used for test
        self.assertIn("-derivedDataPath", cmd)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["artifactManifestPath"].endswith("artifact-provenance.json"))
        self.assertEqual(result["buildId"], "unknown-build")
        self.assertEqual(len(result["artifactDigest"]), 64)

    def test_build_action_defaults_to_generic_destination(self):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            _emit_built_app(cmd)
            return _Proc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", side_effect=fake_run):
                xr.integration_build(Path(tmp), "App", test=False)

        cmd = captured["cmd"]
        self.assertIn(xr.DEFAULT_DESTINATION, cmd)
        self.assertIn("build", cmd)

    def test_successful_xcodebuild_without_app_artifact_fails_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=Path(tmp) / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", return_value=_Proc()):
                result = xr.integration_build(Path(tmp), "App", test=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["artifactError"], "app_artifact_missing")

    def test_attempts_share_incremental_cache_but_not_app_proof(self):
        observed_cache_paths = []
        calls = 0

        def fake_run(cmd, **kw):
            nonlocal calls
            calls += 1
            derived = Path(cmd[cmd.index("-derivedDataPath") + 1])
            observed_cache_paths.append(derived)
            marker = derived / "ModuleCache.noindex" / "cache.marker"
            if calls == 1:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("reusable")
            else:
                self.assertEqual(marker.read_text(), "reusable")
                stale_app = derived / "Build/Products/Debug-iphonesimulator/App.app"
                self.assertFalse(stale_app.exists())
            _emit_built_app(cmd)
            return _Proc()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(xr, "_xcodebuild_available", return_value=True), \
                 mock.patch.object(xr, "_resolve_project", return_value=root / "App.xcodeproj"), \
                 mock.patch.object(xr.subprocess, "run", side_effect=fake_run):
                first = xr.integration_build(root, "App", attempt=1)
                second = xr.integration_build(root, "App", attempt=2)

            self.assertEqual(first["status"], "passed")
            self.assertEqual(second["status"], "passed")
            self.assertEqual(observed_cache_paths[0], observed_cache_paths[1])
            self.assertNotEqual(first["derivedDataPath"], second["derivedDataPath"])


if __name__ == "__main__":
    unittest.main()
