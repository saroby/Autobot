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
            # There is no real simulator behind "mock-simulator", so the
            # is-the-app-on-screen check has nothing to ask.
            "CLONE_RENDER_CAPTURE_ATTEMPTS": "0",
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

    def test_source_sdk_target_and_root_set_invalidate_cache(self):
        self.assertEqual(self.render("base.png").returncode, 0)

        self.source.write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"B\") } }\n"
            "struct AlternateView: View { var body: some View { Text(\"C\") } }\n",
            encoding="utf-8",
        )
        self.assertEqual(self.render("source.png").returncode, 0)
        self.assertEqual(self.render("sdk.png", MOCK_SDK_PATH="/mock/iPhoneSimulatorNext.sdk").returncode, 0)
        self.assertEqual(self.render("target.png", CLONE_IOS_TARGET="18.0").returncode, 0)
        self.assertEqual(
            self.render("roots.png", CLONE_ROOT_VIEWS="HomeView").returncode, 0)
        self.assertEqual(len(self.calls("swiftc")), 5)

    def test_a_second_root_view_reuses_the_same_build(self):
        # The whole point of the launch-time dispatcher: N screens used to cost
        # N full compiles of the same Sources/ directory, and any source edit
        # invalidated every one of them.
        self.source.write_text(
            "import SwiftUI\nstruct HomeView: View { var body: some View { Text(\"A\") } }\n"
            "struct AlternateView: View { var body: some View { Text(\"B\") } }\n",
            encoding="utf-8",
        )
        self.assertEqual(self.render("first.png").returncode, 0)
        second = self.render("second.png", view="AlternateView")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("render cache hit", second.stdout)
        self.assertEqual(len(self.calls("swiftc")), 1)
        # ...and the launch says which root to show.
        self.assertTrue(any("simctl launch" in call for call in self.calls("launch")))


class TestStableFramePolling(RenderMockCase):
    def test_polling_stops_after_two_consecutive_identical_frames(self):
        # The first capture is the pre-launch baseline, so "A" here is the home
        # screen and the poll settles on the two "B" frames after it.
        result = self.render("stable.png", MOCK_FRAME_SEQUENCE="A,B,B,C")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.directory / "stable.png").read_text(encoding="utf-8"), "B")
        self.assertEqual(len(self.calls("screenshot")), 3)
        self.assertIn("frame stable after 2 captures", result.stdout)

    def test_a_frame_stable_on_the_pre_launch_screen_is_reported_not_filed_silently(self):
        # Two identical frames that both equal what was on screen before the
        # launch are how a not-yet-drawn app gets filed as the reproduction.
        result = self.render("home.png", MOCK_FRAME_SEQUENCE="A,A")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("settled on a frame identical to the pre-launch screen",
                      result.stderr)

    def test_a_frame_that_differs_from_the_baseline_is_not_warned_about(self):
        result = self.render("moved.png", MOCK_FRAME_SEQUENCE="HOME,B,B")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("pre-launch screen", result.stderr)

    def test_explicit_legacy_settle_takes_one_screenshot(self):
        result = self.render(
            "legacy.png", MOCK_FRAME_SEQUENCE="A,B", CLONE_RENDER_SETTLE="0"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.calls("screenshot")), 1)

    def test_unstable_frames_fail_at_the_bound(self):
        result = self.render(
            "unstable.png", MOCK_FRAME_SEQUENCE="A,B,C,D,E", CLONE_RENDER_POLL_ATTEMPTS="4"
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

    def test_auto_fails_clearly_when_no_device_type_matches(self):
        result = self.auto_render("missing.png", {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [{
                "name": "iPhone 17 Pro", "udid": "OTHER", "state": "Booted",
                "deviceTypeIdentifier":
                    "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro",
            }],
        })
        self.assertEqual(result.returncode, 1)
        self.assertIn("no available simulator of device type 'iPhone 12 mini'", result.stderr)
        self.assertIn("simctl create clone-probe", result.stderr)
        self.assertEqual(len(self.calls("swiftc")), 0)

    def test_a_custom_named_simulator_of_the_right_type_is_selected(self):
        """The header tells you to `simctl create clone-probe ...iPhone-12-mini`.

        That names the simulator "clone-probe", so matching on the name could
        never select what the instructions produce — measured 2026-08-22 against
        three real iPhone 12 mini simulators, all rejected. Logical size comes
        from the device type; the name is whoever created it.
        """
        result = self.auto_render("named.png", {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [{
                "name": "Clone-Threads-Probe", "udid": "PROBE", "state": "Shutdown",
                "deviceTypeIdentifier":
                    "com.apple.CoreSimulator.SimDeviceType.iPhone-12-mini",
            }],
        })
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("selected simulator PROBE", result.stdout)

    def test_explicit_simulator_does_not_read_profile_or_list_devices(self):
        missing_profile = self.directory / "missing-profile.json"
        result = self.render("explicit.png", CLONE_DEVICE_PROFILE=str(missing_profile))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any("simctl list devices" in call for call in self.calls("simctl list")))


if __name__ == "__main__":
    unittest.main()


class TestRootDispatch(unittest.TestCase):
    """One build hosts every root view; the root is chosen at launch.

    Baking the root into the binary meant N screens cost N full compiles of the
    same Sources/ directory, and every source edit invalidated all of them. The
    refusals below are what keeps that build honest: it can only host roots it
    was told about.
    """

    def sources(self, directory: str) -> str:
        Path(directory, "Views.swift").write_text(
            "import SwiftUI\n"
            "struct HomeView: View { var body: some View { Text(\"home\") } }\n"
            "struct DetailView: View, Equatable { var body: some View { Text(\"d\") } }\n"
            "struct RowView: View { let title: String\n"
            "    var body: some View { Text(title) } }\n",
            encoding="utf-8")
        return directory

    def test_a_root_that_is_not_a_view_in_sources_is_named_as_such(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(self.sources(d), "NoSuchView", "sim", "/tmp/out.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a View declared", r.stderr)
        # The message has to list what IS available or the caller is guessing.
        self.assertIn("HomeView", r.stderr)

    def test_a_multi_protocol_conformance_is_still_selectable(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(self.sources(d), "DetailView", "sim", "/tmp/out.png")
        self.assertNotIn("not a View declared", r.stderr)

    def test_an_explicit_root_set_excludes_everything_else(self):
        # clone_run.sh passes exactly the views.json mapping, so a helper view
        # that needs an argument never has to be constructed by the dispatcher.
        with tempfile.TemporaryDirectory() as d:
            r = run(self.sources(d), "RowView", "sim", "/tmp/out.png",
                    env={"CLONE_ROOT_VIEWS": "HomeView DetailView"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a View declared", r.stderr)
        self.assertNotIn("RowView", r.stderr.split("found:")[-1])


class TestRenderCacheIsBounded(RenderMockCase):
    """Every entry ships the capture crops, so the cache must not grow forever.

    This repo has a lesson where a full disk surfaced as "Unable to resolve
    module dependency" and was read as a SwiftUI error. A polish loop — edit a
    view, re-render all of them, repeat — is exactly the workload that gets
    there.
    """

    def test_old_entries_are_pruned_to_the_cap(self):
        for index in range(4):
            self.source.write_text(
                "import SwiftUI\n"
                f"struct HomeView: View {{ var body: some View {{ Text(\"{index}\") }} }}\n",
                encoding="utf-8")
            result = self.render(f"round{index}.png", CLONE_RENDER_CACHE_KEEP="2")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entries = [path for path in self.cache.iterdir() if path.is_dir()]
        self.assertLessEqual(len(entries), 2, [p.name for p in entries])

    def test_the_entry_just_built_is_never_the_one_pruned(self):
        for index in range(3):
            self.source.write_text(
                "import SwiftUI\n"
                f"struct HomeView: View {{ var body: some View {{ Text(\"{index}\") }} }}\n",
                encoding="utf-8")
            self.render(f"keep{index}.png", CLONE_RENDER_CACHE_KEEP="1")
        # The last build must still be a hit, or the cap has made the cache useless.
        again = self.render("again.png", CLONE_RENDER_CACHE_KEEP="1")
        self.assertIn("render cache hit", again.stdout)
