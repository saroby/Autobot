"""device_render.sh preconditions — offline, no simulator.

This script is what makes SKILL rule 4 ("no completion claim without a compare
image") executable, so its refusals matter: a silent failure here would let the
clone loop compare against a stale screenshot from a previous run.

Booting a simulator and rendering is verified against a real one instead (a live
Journal reproduction, 2026-07-25) — the checks below are the ones that must hold
without any device attached.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_render.sh"


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(SCRIPT), *args], capture_output=True, text=True, env=merged_env
    )


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
            r = run(d, "Broken", "no-such-simulator", "/tmp/out.png",
                    env={"CLONE_RENDER_CACHE": str(Path(d, "cache"))})
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot find 'nope'", r.stdout + r.stderr)
        self.assertIn("swiftc failed", r.stderr)


MOCK_XCRUN = r'''#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${MOCK_XCRUN_LOG:?}"

if [[ "${1:-}" == "--sdk" && "${3:-}" == "--show-sdk-path" ]]; then
  printf '%s\n' "${MOCK_SDK_PATH:-/mock/iPhoneSimulator.sdk}"
  exit 0
fi

if [[ "${1:-}" == "simctl" && "${2:-}" == "list" && "${3:-}" == "devices" ]]; then
  if [[ -n "${MOCK_SIMCTL_DEVICES_JSON:-}" ]]; then
    printf '%s\n' "$MOCK_SIMCTL_DEVICES_JSON"
  else
    printf '%s\n' '{"devices":{}}'
  fi
  exit 0
fi

if [[ "${1:-}" == "swiftc" ]]; then
  if [[ "${MOCK_SWIFTC_FAIL:-0}" == "1" ]]; then
    echo "mock compiler failure" >&2
    exit 1
  fi
  output=""
  shift
  while (( $# )); do
    if [[ "$1" == "-o" ]]; then
      output="$2"
      shift 2
    else
      shift
    fi
  done
  mkdir -p "$(dirname "$output")"
  printf '#!/bin/sh\nexit 0\n' > "$output"
  chmod +x "$output"
  exit 0
fi

if [[ "${1:-}" == "simctl" && "${2:-}" == "io" && "${4:-}" == "screenshot" ]]; then
  output="${5:?}"
  count=0
  if [[ -f "${MOCK_FRAME_COUNT:?}" ]]; then count="$(< "${MOCK_FRAME_COUNT}")"; fi
  count=$((count + 1))
  printf '%s\n' "$count" > "${MOCK_FRAME_COUNT}"
  IFS=',' read -r -a frames <<< "${MOCK_FRAME_SEQUENCE:-A,A}"
  index=$((count - 1))
  if (( index >= ${#frames[@]} )); then index=$((${#frames[@]} - 1)); fi
  mkdir -p "$(dirname "$output")"
  printf '%s' "${frames[$index]}" > "$output"
  exit 0
fi

exit 0
'''


class RenderMockCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)
        self.sources = self.directory / "Sources"
        self.sources.mkdir()
        self.source = self.sources / "HomeView.swift"
        self.source.write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"A\") } }\n",
            encoding="utf-8",
        )
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.xcrun = self.bin / "xcrun"
        self.xcrun.write_text(MOCK_XCRUN, encoding="utf-8")
        self.xcrun.chmod(0o755)
        self.log = self.directory / "xcrun.log"
        self.count = self.directory / "frame-count"
        self.cache = self.directory / "cache"
        self.environment = {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "MOCK_XCRUN_LOG": str(self.log),
            "MOCK_FRAME_COUNT": str(self.count),
            "MOCK_FRAME_SEQUENCE": "A,A",
            "CLONE_RENDER_CACHE": str(self.cache),
            "CLONE_RENDER_POLL_ATTEMPTS": "6",
            "CLONE_RENDER_POLL_INTERVAL": "0",
        }
        self.addCleanup(self._directory.cleanup)

    def render(self, name: str, view: str = "HomeView", **environment: str):
        merged = self.environment | environment
        return run(
            str(self.sources), view, "mock-simulator", str(self.directory / name),
            env=merged,
        )

    def calls(self, needle: str) -> list[str]:
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text(encoding="utf-8").splitlines()
                if needle in line]


class TestRenderCache(RenderMockCase):
    def test_cache_miss_then_hit_compiles_only_once(self):
        first = self.render("first.png")
        second = self.render("second.png")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("render cache miss", first.stdout)
        self.assertIn("render cache hit", second.stdout)
        self.assertEqual(len(self.calls("swiftc")), 1)

    def test_source_root_sdk_and_deployment_target_invalidate_cache(self):
        self.assertEqual(self.render("base.png").returncode, 0)

        self.source.write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"B\") } }\n",
            encoding="utf-8",
        )
        self.assertEqual(self.render("source.png").returncode, 0)
        self.assertEqual(self.render("root.png", view="AlternateView").returncode, 0)
        self.assertEqual(self.render("sdk.png", MOCK_SDK_PATH="/mock/iPhoneSimulatorNext.sdk").returncode, 0)
        self.assertEqual(self.render("target.png", CLONE_IOS_TARGET="18.0").returncode, 0)
        self.assertEqual(len(self.calls("swiftc")), 5)


class TestStableFramePolling(RenderMockCase):
    def test_polling_stops_after_two_consecutive_identical_frames(self):
        result = self.render("stable.png", MOCK_FRAME_SEQUENCE="A,B,B,C")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.directory / "stable.png").read_text(encoding="utf-8"), "B")
        self.assertEqual(len(self.calls("screenshot")), 3)
        self.assertIn("frame stable after 3 captures", result.stdout)

    def test_explicit_legacy_settle_takes_one_screenshot(self):
        result = self.render(
            "legacy.png", MOCK_FRAME_SEQUENCE="A,B", CLONE_RENDER_SETTLE="0"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.calls("screenshot")), 1)

    def test_unstable_frames_fail_at_the_bound(self):
        result = self.render(
            "unstable.png", MOCK_FRAME_SEQUENCE="A,B,C,D", CLONE_RENDER_POLL_ATTEMPTS="4"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not produce two identical frames", result.stderr)
        self.assertFalse((self.directory / "unstable.png").exists())


class TestAutomaticSimulatorSelection(RenderMockCase):
    def setUp(self):
        super().setUp()
        self.profile = self.directory / "device-profile.json"
        self.profile.write_text(
            json.dumps({"marketingName": "iPhone 12 mini"}), encoding="utf-8"
        )

    def auto_render(self, name: str, devices: dict):
        return run(
            str(self.sources), "HomeView", "auto", str(self.directory / name),
            env=self.environment | {
                "CLONE_DEVICE_PROFILE": str(self.profile),
                "MOCK_SIMCTL_DEVICES_JSON": json.dumps({"devices": devices}),
            },
        )

    def test_auto_prefers_booted_before_a_newer_runtime(self):
        result = self.auto_render("booted.png", {
            "com.apple.CoreSimulator.SimRuntime.iOS-25-4": [{
                "name": "iPhone 12 mini", "udid": "BOOTED-25", "state": "Booted",
                "isAvailable": True,
            }],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [{
                "name": "iPhone 12 mini", "udid": "SHUTDOWN-26", "state": "Shutdown",
                "isAvailable": True,
            }],
        })
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("selected simulator BOOTED-25", result.stdout)
        self.assertTrue(any("simctl boot BOOTED-25" in call for call in self.calls("simctl boot")))

    def test_auto_uses_newest_runtime_when_none_are_booted(self):
        result = self.auto_render("newest.png", {
            "com.apple.CoreSimulator.SimRuntime.iOS-18-1": [{
                "name": "iPhone 12 mini", "udid": "OLD", "state": "Shutdown",
            }],
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [{
                "name": "iPhone 12 mini", "udid": "NEW", "state": "Shutdown",
            }],
        })
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("selected simulator NEW", result.stdout)

    def test_auto_fails_clearly_when_no_marketing_name_matches(self):
        result = self.auto_render("missing.png", {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [{
                "name": "iPhone 17 Pro", "udid": "OTHER", "state": "Booted",
            }],
        })
        self.assertEqual(result.returncode, 1)
        self.assertIn("no available simulator matching marketingName 'iPhone 12 mini'", result.stderr)
        self.assertEqual(len(self.calls("swiftc")), 0)

    def test_explicit_simulator_does_not_read_profile_or_list_devices(self):
        missing_profile = self.directory / "missing-profile.json"
        result = self.render("explicit.png", CLONE_DEVICE_PROFILE=str(missing_profile))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any("simctl list devices" in call for call in self.calls("simctl list")))


if __name__ == "__main__":
    unittest.main()
