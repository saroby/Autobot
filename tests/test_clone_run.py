"""clone_run.sh — the two unattended halves of /autobot:clone.

Nothing here touches a phone. What is pinned is the part that decides WHAT to
do: refusing clearly when the previous half never ran, and the join that turns
`views.json` + `flow.jsonl` + `screens/*.json` into "render THIS view against
THAT capture". Get the join wrong and verify silently checks nothing, which
reads exactly like a clean pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_run.sh"
# A UDID no attached device can have, so anything that reaches devicectl fails
# fast instead of driving a phone.
FIXTURE_UDID = "00008101-000FIXTURE0001E"


class CloneRunCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.root = self.dir / "clone"
        (self.root / "screens").mkdir(parents=True)
        (self.root / "raw").mkdir()
        self.addCleanup(self._dir.cleanup)
        # Device enumeration must come from a fixture, never from whatever
        # phone happens to be plugged in. Without this the `observe` tests
        # resolved the developer's real device and drove it: measured
        # 2026-08-23, one run walked 60+ steps through the user's live Threads
        # account, and the notification bell on three strangers' posts was
        # toggled on and back off before anyone noticed. A test suite must not
        # be able to touch a real account.
        self.devices_json = self.dir / "devices.json"
        self.devices_json.write_text(json.dumps({"result": {"devices": [{
            "hardwareProperties": {"udid": FIXTURE_UDID, "reality": "physical"},
            "deviceProperties": {"name": "fixture iPhone"},
            "connectionProperties": {"tunnelState": "connected"},
        }]}}), encoding="utf-8")
        self.device_details_json = self.dir / "details.json"
        self.device_details_json.write_text(json.dumps({"result": {"properties": {
            "connection": {"state": "connected"},
            "hardware": {"reality": "physical", "udid": FIXTURE_UDID,
                         "marketingName": "iPhone 12 mini", "productType": "iPhone13,1"},
            "software": {"osVersionNumber": {"stringValue": "26.5.2"},
                         "osBuildVersions": {"buildVersion": {"name": "23F84"}}},
        }}}), encoding="utf-8")

    def offline_env(self, **extra: str) -> dict:
        """Everything that keeps a run inside this temp directory."""
        return {
            **os.environ,
            "CLONE_ROOT": str(self.root),
            "CLONE_FLOW_LOG": str(self.root / "flow.jsonl"),
            "CLONE_STATE_DIR": str(self.dir / "state"),
            "CLONE_DEVICES_JSON": str(self.devices_json),
            "CLONE_DEVICE_DETAILS_JSON": str(self.device_details_json),
            # Nothing here may open the developer's Xcode, start a server, or
            # run a privileged tunnel command.
            "CLONE_AUTO_OPEN_XCODE": "0",
            "CLONE_AUTO_START_TUNNEL": "0",
            "CLONE_TUNNEL_GUI_AUTH": "0",
            "CLONE_AUTO_START_APPIUM": "0",
            # `auto` resolves the simulator from this profile; pointing it at a
            # path that does not exist makes rendering fail before swiftc runs.
            "CLONE_DEVICE_PROFILE": str(self.dir / "no-profile.json"),
            # Pin the simulator so the join is exercised without a real one.
            # Resolution is a property of the RUN, not of a screen, so verify
            # settles it once up front — see test_no_simulator_fails_once.
            "CLONE_RENDER_SIMULATOR": "SIM-UDID",
            **extra,
        }

    def run_clone(self, *args: str, **env_extra: str) -> subprocess.CompletedProcess:
        # stdin closed: `_authorize_tunnel` asks `[[ -t 0 ]]` before `sudo -v`,
        # and a suite run from a terminal would otherwise sit on a password
        # prompt.
        return subprocess.run(["bash", str(SCRIPT), *args],
                              capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=self.offline_env(**env_extra))

    def write_flow(self, events: list[dict]) -> None:
        (self.root / "flow.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
            encoding="utf-8")

    def write_views(self, views: dict[str, str]) -> None:
        (self.root / "views.json").write_text(
            json.dumps({"version": 1, "initial_state": next(iter(views)), "views": views}),
            encoding="utf-8")

    def write_measurement(self, stem: str) -> None:
        (self.root / "screens" / f"{stem}.json").write_text("{}", encoding="utf-8")
        (self.root / "raw" / f"{stem}.png").write_bytes(b"png")

    def write_sources(self, *views: str) -> None:
        sources = self.root / "Sources"
        sources.mkdir(exist_ok=True)
        for view in views or ("HomeView",):
            (sources / f"{view}.swift").write_text(
                f"struct {view}: View {{ var body: some View {{ EmptyView() }} }}\n",
                encoding="utf-8")


class TestRefusals(CloneRunCase):
    def test_observe_without_a_target_prints_usage(self):
        r = self.run_clone("observe")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Usage: clone_run.sh observe", r.stderr)

    def test_an_unknown_subcommand_prints_usage(self):
        r = self.run_clone("explore")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Usage: clone_run.sh", r.stderr)

    def test_verify_before_observe_names_the_command_that_produces_the_input(self):
        r = self.run_clone("verify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("clone_run.sh observe", r.stderr)

    def test_verify_before_the_views_are_written_says_so(self):
        self.write_views({"state-a": "HomeView"})
        r = self.run_clone("verify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("has not been written", r.stderr)

    def test_a_view_without_a_measured_capture_is_not_silently_skipped(self):
        self.write_views({"state-a": "HomeView"})
        self.write_sources()
        self.write_flow([{"type": "screen", "node": "n1", "statekey": "state-a",
                          "name": "01-home", "tree": "t", "png": "p"}])
        r = self.run_clone("polish")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no screen has both", r.stderr)


class TestCodegenOnItsOwn(CloneRunCase):
    """The half that needs no phone must be runnable without one.

    Generation is the LAST thing `observe` does, so a contradiction in the log
    fails after the whole device run and leaves Sources/ empty. Measured
    2026-08-23 on Threads: recovering meant re-exploring a live app for minutes
    to redo work no device is involved in.
    """

    def test_codegen_before_observe_names_the_command_that_produces_the_log(self):
        r = self.run_clone("codegen")
        self.assertEqual(r.returncode, 1)
        self.assertIn("clone_run.sh observe", r.stderr)

    def test_codegen_rebuilds_the_manifest_router_and_views_from_the_log_alone(self):
        self.write_flow([
            {"type": "screen", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
            {"type": "screen", "statekey": "state-b", "name": "02-detail",
             "tree": "t", "png": "p"},
            {"type": "tap", "from_statekey": "state-a", "to_statekey": "state-b",
             "label": "열기", "changed": True, "x": 10, "y": 20},
        ])
        for stem in ("01-home", "02-detail"):
            self.write_measurement(stem)
        r = self.run_clone("codegen")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        views = json.loads((self.root / "views.json").read_text(encoding="utf-8"))["views"]
        self.assertEqual(set(views), {"state-a", "state-b"})
        router = (self.root / "Sources" / "ObservedFlow.swift").read_text(encoding="utf-8")
        self.assertIn('"열기"', router)
        for view in views.values():
            self.assertTrue((self.root / "Sources" / f"{view}.swift").is_file(), view)

    def test_codegen_keeps_names_already_chosen_for_a_state(self):
        # compare/ evidence and hand-polished files are keyed by the view name,
        # so re-running generation must not rename a state that already has one.
        self.write_flow([{"type": "screen", "statekey": "state-a", "name": "01-home",
                          "tree": "t", "png": "p"}])
        self.write_measurement("01-home")
        self.write_views({"state-a": "HomeFeedView"})
        r = self.run_clone("codegen")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        views = json.loads((self.root / "views.json").read_text(encoding="utf-8"))["views"]
        self.assertEqual(views["state-a"], "HomeFeedView")

    def test_codegen_drops_stale_alias_keys_and_repairs_the_initial_state(self):
        self.write_flow([
            {"type": "screen", "statekey": "loading", "name": "01-profile",
             "tree": "t", "png": "p"},
            {"type": "screen", "statekey": "home", "name": "02-home",
             "tree": "t", "png": "p"},
        ])
        for stem in ("01-profile", "02-home"):
            self.write_measurement(stem)
        (self.root / "state-aliases.json").write_text(json.dumps({"aliases": {
            "loading": {"canonical": "loaded", "why": "same settled profile screen"},
        }}), encoding="utf-8")
        (self.root / "views.json").write_text(json.dumps({
            "version": 1,
            "initial_state": "loading",
            "views": {
                "loading": "StaleLoadingView",
                "loaded": "ProfileView",
                "home": "HomeFeedView",
                "unobserved": "StaleView",
            },
        }), encoding="utf-8")

        r = self.run_clone("codegen")

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        manifest = json.loads((self.root / "views.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["initial_state"], "loaded")
        self.assertEqual(manifest["views"], {
            "home": "HomeFeedView",
            "loaded": "ProfileView",
        })


class TestTargetBinding(CloneRunCase):
    """Target resolution may not silently retarget an existing clone."""

    def setUp(self):
        super().setUp()
        self.harness = self.dir / "harness"
        self.harness.mkdir()
        shutil.copy2(SCRIPT, self.harness / "clone_run.sh")
        (self.harness / "clone_workspace.sh").write_text(
            "#!/bin/bash\nmkdir -p \"$CLONE_ROOT/project\"\n", encoding="utf-8")
        (self.harness / "device_wda.sh").write_text(f"""#!/bin/bash
case "$1" in
  device) echo "{FIXTURE_UDID}" ;;
  doctor)
    echo "doctor:$3" >>"$FAKE_DEVICE_LOG"
    exit "${{FAKE_DOCTOR_STATUS:-0}}"
    ;;
  session)
    echo "session:$3" >>"$FAKE_DEVICE_LOG"
    [[ "${{FAKE_SESSION_STATUS:-0}}" == "0" ]] || exit "$FAKE_SESSION_STATUS"
    echo "fixture-session"
    ;;
  explore) exit 1 ;;
esac
""", encoding="utf-8")
        self.device_log = self.dir / "device.log"
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        xcrun = self.bin / "xcrun"
        xcrun.write_text("""#!/bin/bash
printf '%s\n' '{"result":{"apps":[{"bundleIdentifier":"com.example.threads","name":"Threads"}]}}'
""", encoding="utf-8")
        xcrun.chmod(0o755)

    def observe(self, **extra: str) -> subprocess.CompletedProcess:
        env = self.offline_env(
            CLONE_REQUIRE_SUDO="0",
            FAKE_DEVICE_LOG=str(self.device_log),
            PATH=f"{self.bin}:{os.environ['PATH']}",
            **extra,
        )
        return subprocess.run(
            ["bash", str(self.harness / "clone_run.sh"), "observe", "Threads"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env,
        )

    def test_a_different_existing_target_aborts_before_doctor_or_session(self):
        target = self.root / "target.json"
        original = {"bundleId": "com.example.other", "name": "Other"}
        target.write_text(json.dumps(original), encoding="utf-8")

        result = self.observe()

        self.assertEqual(result.returncode, 1)
        self.assertIn("use a separate CLONE_ROOT", result.stderr)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), original)
        self.assertFalse(self.device_log.exists())

    def test_existing_target_without_a_bundle_id_fails_closed(self):
        target = self.root / "target.json"
        original = {"name": "Unknown legacy target"}
        target.write_text(json.dumps(original), encoding="utf-8")

        result = self.observe()

        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot be verified", result.stderr)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), original)
        self.assertFalse(self.device_log.exists())

    def test_doctor_or_session_failure_does_not_record_the_candidate(self):
        for failure in ({"FAKE_DOCTOR_STATUS": "1"}, {"FAKE_SESSION_STATUS": "1"}):
            with self.subTest(failure=failure):
                target = self.root / "target.json"
                target.unlink(missing_ok=True)
                self.device_log.unlink(missing_ok=True)
                result = self.observe(**failure)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(target.exists())

    def test_target_is_recorded_after_doctor_and_session_bind(self):
        result = self.observe()

        # The harness intentionally stops at explore. Target binding is already
        # proven and recorded before evidence collection starts.
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.device_log.read_text(encoding="utf-8").splitlines(), [
            "doctor:com.example.threads", "session:com.example.threads",
        ])
        self.assertEqual(json.loads((self.root / "target.json").read_text(
            encoding="utf-8")), {
                "bundleId": "com.example.threads",
                "name": "Threads",
                "resolvedBy": "exact-name",
                "query": "Threads",
            })


class TestExploreRounds(CloneRunCase):
    """A failed round that still collected evidence must not end observe.

    Measured 2026-08-23: one unsettled tap on a live feed ended the whole
    observe mid-budget with rounds left, and a human restarted it. The round
    budget exists to absorb exactly that; only a round that failed without
    making a single step is environmental and stops the loop.
    """

    def setUp(self):
        super().setUp()
        self.harness = self.dir / "harness"
        self.harness.mkdir()
        shutil.copy2(SCRIPT, self.harness / "clone_run.sh")
        (self.harness / "clone_workspace.sh").write_text(
            "#!/bin/bash\nmkdir -p \"$CLONE_ROOT/project\"\n", encoding="utf-8")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        xcrun = self.bin / "xcrun"
        xcrun.write_text("""#!/bin/bash
printf '%s\n' '{"result":{"apps":[{"bundleIdentifier":"com.example.threads","name":"Threads"}]}}'
""", encoding="utf-8")
        xcrun.chmod(0o755)
        self.rounds_file = self.dir / "rounds"
        (self.harness / "device_wda.sh").write_text(f"""#!/bin/bash
case "$1" in
  device) echo "{FIXTURE_UDID}" ;;
  doctor) exit 0 ;;
  session) echo "fixture-session" ;;
  explore)
    n="$(cat "$FAKE_ROUNDS_FILE" 2>/dev/null || echo 0)"
    n=$((n + 1)); echo "$n" >"$FAKE_ROUNDS_FILE"
    if [[ "$n" -eq 1 ]]; then
      # A round that collected evidence and then died mid-budget.
      for i in 1 2 3; do
        echo '{{"type":"screen","state":"s'$i'","name":"auto-000'$i'"}}' >>"$CLONE_FLOW_LOG"
      done
      exit 1
    fi
    exit 1   # the next round could not even step: environmental, stop
    ;;
esac
""", encoding="utf-8")

    def observe(self) -> subprocess.CompletedProcess:
        env = self.offline_env(
            CLONE_REQUIRE_SUDO="0",
            FAKE_ROUNDS_FILE=str(self.rounds_file),
            PATH=f"{self.bin}:{os.environ['PATH']}",
        )
        return subprocess.run(
            ["bash", str(self.harness / "clone_run.sh"), "observe", "Threads"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env,
        )

    def test_a_failed_round_with_progress_starts_the_next_round(self):
        result = self.observe()
        self.assertEqual(self.rounds_file.read_text(encoding="utf-8").strip(), "2")
        self.assertIn("starting the next round", result.stderr)
        self.assertIn("INFO: explore round 2/", result.stdout)
        self.assertIn("failed without making a step", result.stderr)

    def test_a_failed_run_does_not_print_the_ok_line(self):
        result = self.observe()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("OK: observed", result.stdout)
        self.assertIn("observe finished with failures", result.stderr)


class TestUnwrittenViews(CloneRunCase):
    def test_a_view_that_was_never_written_is_named_before_anything_renders(self):
        """device_render.sh compiles Sources as one unit and the generated
        router names every mapped type, so one unwritten view fails the build
        for every screen. Reporting 24 identical compiler errors hides which
        one is actually missing."""
        self.write_views({"state-a": "HomeView", "state-b": "DetailView"})
        self.write_sources("HomeView")
        self.write_measurement("01-home")
        self.write_flow([{"type": "screen", "node": "n1", "statekey": "state-a",
                          "name": "01-home", "tree": "t", "png": "p"}])
        r = self.run_clone("verify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("DetailView", r.stderr)
        self.assertNotIn("HomeView", r.stderr)
        self.assertNotIn("INFO: verify", r.stdout)


class TestSimulatorGate(CloneRunCase):
    def test_no_simulator_fails_once_not_once_per_screen(self):
        """A missing simulator is an environment fault, not 20 broken views.

        Measured 2026-08-22: `auto` could not match the iPhone 12 mini, and
        verify reported it 20 times as "did not render — fix the compiler
        diagnostics above", naming a cause that was not there.
        """
        self.write_views({"state-a": "HomeView", "state-b": "DetailView"})
        self.write_sources("HomeView", "DetailView")
        self.write_measurement("01-home")
        self.write_measurement("02-detail")
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
            {"type": "screen", "node": "n2", "statekey": "state-b", "name": "02-detail",
             "tree": "t", "png": "p"},
        ])
        env = {"CLONE_RENDER_SIMULATOR": ""}
        r = subprocess.run(["bash", str(SCRIPT), "verify"], capture_output=True, text=True,
                           env={**os.environ, "CLONE_ROOT": str(self.root),
                                "CLONE_FLOW_LOG": str(self.root / "flow.jsonl"),
                                "CLONE_DEVICE_PROFILE": str(self.dir / "no-profile.json"),
                                **env})
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot pick a simulator", r.stderr)
        self.assertNotIn("INFO: verify", r.stdout)
        self.assertNotIn("compiler diagnostics", r.stderr)


class TestJoin(CloneRunCase):
    def test_each_measured_state_is_verified_against_its_own_view(self):
        self.write_views({"state-a": "HomeView", "state-b": "DetailView"})
        self.write_sources("HomeView", "DetailView")
        self.write_measurement("01-home")
        self.write_measurement("02-detail")
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
            {"type": "screen", "node": "n2", "statekey": "state-b", "name": "02-detail",
             "tree": "t", "png": "p"},
        ])
        r = self.run_clone("polish")
        self.assertIn("INFO: verify 01-home (HomeView)", r.stdout)
        self.assertIn("INFO: verify 02-detail (DetailView)", r.stdout)
        # Rendering cannot succeed here, and a verify that cannot render must
        # never report a pass — that is the whole point of the exit code.
        self.assertEqual(r.returncode, 1)
        self.assertIn("failed verification", r.stderr)

    def test_a_state_without_a_measurement_is_reported_not_skipped(self):
        """Silently skipping is how "28 of 28 failed" hides three unchecked screens.

        A mapped state with no measurement has nothing to compare a render
        against, so the loop never sees it — and the summary then counts only
        what it did check, which reads as full coverage. Measured 2026-08-22:
        views.json mapped 31 states, verify reported on 28.
        """
        self.write_views({"state-a": "HomeView", "state-b": "DetailView"})
        self.write_sources("HomeView", "DetailView")
        self.write_measurement("01-home")          # state-b has none
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
            {"type": "screen", "node": "n2", "statekey": "state-b", "name": "02-detail",
             "tree": "t", "png": "p"},
        ])
        r = self.run_clone("polish")
        self.assertEqual(r.returncode, 1)
        self.assertIn("have no measurement", r.stderr)
        self.assertIn("DetailView", r.stderr)
        self.assertIn("1 unverifiable", r.stderr)

    def test_the_state_key_wins_over_the_coarse_node(self):
        """Two interaction states of one node must not collapse into one view."""
        self.write_views({"state-a": "HomeView", "state-b": "SearchFocusedView"})
        self.write_sources("HomeView", "SearchFocusedView")
        self.write_measurement("01-home")
        self.write_measurement("02-focused")
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
            {"type": "screen", "node": "n1", "statekey": "state-b", "name": "02-focused",
             "tree": "t", "png": "p"},
        ])
        r = self.run_clone("polish")
        self.assertIn("INFO: verify 01-home (HomeView)", r.stdout)
        self.assertIn("INFO: verify 02-focused (SearchFocusedView)", r.stdout)


class TestPhaseOrder(CloneRunCase):
    """Functional before pixels.

    Polishing a screen the app cannot reach is work spent before knowing
    whether it counts — and the static checks cannot see the difference: the
    2026-08-23 run had every element present and every pixel metric computed on
    screens whose taps went nowhere.
    """

    def setUp(self):
        super().setUp()
        self.write_views({"state-a": "HomeView"})
        self.write_sources("HomeView")
        self.write_measurement("01-home")
        self.write_flow([
            {"type": "screen", "node": "n1", "statekey": "state-a", "name": "01-home",
             "tree": "t", "png": "p"},
        ])

    def test_verify_does_not_reach_the_pixel_pass_when_the_build_fails(self):
        r = self.run_clone("verify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("stopping before the pixel pass", r.stderr)
        self.assertNotIn("INFO: verify 01-home", r.stdout)

    def test_polish_can_still_be_asked_for_directly(self):
        # The gate is the default order, not a lock: a screen can be worked on
        # before the whole flow is wired.
        r = self.run_clone("polish")
        self.assertNotIn("stopping before the pixel pass", r.stderr)
        self.assertIn("INFO: verify 01-home (HomeView)", r.stdout)


class TestSudoGate(CloneRunCase):
    """`observe` asks for authorization before it does anything expensive.

    An iOS 18+ device needs a RemoteXPC tunnel and creating it needs root. That
    happened several minutes in, at `doctor`, so a run that nobody could
    authenticate burned the whole preamble first.
    """

    def test_authorization_is_asked_for_before_anything_expensive(self):
        r = self.run_clone("observe", "Threads")
        self.assertEqual(r.returncode, 1)
        # The point of the gate: the password is asked for at the start, not
        # several minutes in at `doctor`, after the run has spent that time.
        self.assertIn("starting the RemoteXPC tunnel", r.stderr)
        self.assertIn("administrator dialog", r.stderr)
        self.assertNotIn("INFO: explore round", r.stdout)

    def test_a_failure_names_both_ways_to_authorize(self):
        r = self.run_clone("observe", "Threads")
        self.assertIn("sudo -v", r.stderr)
        self.assertIn("tunnel-creation", r.stderr)

    def test_the_gate_can_be_turned_off(self):
        r = self.run_clone("observe", "Threads", CLONE_REQUIRE_SUDO="0")
        self.assertNotIn("no terminal to ask for a password", r.stderr)
        # Turning the gate off must not turn the run loose on a real phone.
        self.assertNotIn("INFO: explore round", r.stdout)


if __name__ == "__main__":
    unittest.main()
