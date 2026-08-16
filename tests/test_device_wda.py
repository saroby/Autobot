"""device_wda.sh device gate — offline via the CLONE_DEVICES_JSON fixture.

The gate is what makes /autobot:copy stop instead of degrading when no iPhone
is attached, so its three outcomes (one device / none / ambiguous) are pinned
here. `paired` must never count as connected: a phone can hold a trust record
for weeks after its transport is gone (observed 2026-07-25 — devicectl reported
`pairingState: paired` with `transportType: None` on an unplugged device).

Screen/tap/type/swipe are thin HTTP passthroughs to Appium; the offline tests
pin the session capability and active-app guard, while a real device is still
required for WDA interaction itself.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_wda.sh"


def unused_local_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def devicectl_json(devices: list[tuple[str, str, str]]) -> str:
    """Shape of `xcrun devicectl list devices --json-output -`."""
    return json.dumps({"result": {"devices": [
        {
            "hardwareProperties": {"udid": udid, "reality": "physical"},
            "deviceProperties": {"name": name},
            "connectionProperties": {"tunnelState": state},
        }
        for udid, name, state in devices
    ]}})


def device_details_json(
    udid: str,
    name: str,
    connection_state: str = "connected",
    marketing_name: str = "iPhone 12 mini",
    product_type: str = "iPhone13,1",
    os_version: str = "26.5.2",
    os_build: str = "23F84",
) -> str:
    return json.dumps({"result": {"properties": {
        "connection": {"state": connection_state},
        "hardware": {
            "reality": "physical",
            "udid": udid,
            "marketingName": marketing_name,
            "productType": product_type,
        },
        "software": {
            "osVersionNumber": {"stringValue": os_version},
            "osBuildVersions": {"buildVersion": {"name": os_build}},
        },
        "state": {"name": name},
    }}})


def start_tunnel_registry(marker: Path, udid: str = "00008101-AAA"):
    """Return a local registry that publishes the target only after marker exists."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            tunnels = [{"udid": udid}] if marker.exists() else []
            body = json.dumps({"tunnels": tunnels}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run_device(
    devices: list[tuple[str, str, str]],
    *argv: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        fixture = root / "devices.json"
        fixture.write_text(devicectl_json(devices), encoding="utf-8")
        selector = argv[0] if argv else ""
        matches = [item for item in devices
                   if item[2] == "connected"
                   and (not selector or item[0] == selector or selector in item[1])]
        selected = matches[0] if len(matches) == 1 else (devices[0] if devices else ("", "", ""))
        details = root / "details.json"
        details.write_text(device_details_json(selected[0], selected[1], selected[2]), encoding="utf-8")
        env = {
            **os.environ,
            "CLONE_DEVICES_JSON": str(fixture),
            "CLONE_DEVICE_DETAILS_JSON": str(details),
            "CLONE_STATE_DIR": str(root / "state"),
            # Offline gate tests must not launch the developer's Xcode.
            "CLONE_AUTO_OPEN_XCODE": "0",
            **(extra_env or {}),
        }
        return subprocess.run(
            ["bash", str(SCRIPT), "device", *argv],
            capture_output=True, text=True, env=env,
        )


ONE = [("00008101-AAA", "heewook의 iPhone", "connected")]
NONE_CONNECTED = [("00008101-AAA", "heewook의 iPhone", "unavailable")]
TWO = [
    ("00008101-AAA", "heewook의 iPhone", "connected"),
    ("00008120-BBB", "iPhone 14 Pro", "connected"),
]


class TestCloneWdaDeviceGate(unittest.TestCase):
    def test_connected_device_collector_appends_each_name_once(self):
        self.assertEqual(SCRIPT.read_text(encoding="utf-8").count('names+=("$name")'), 1)

    def test_prints_bare_udid_on_stdout(self):
        r = run_device(ONE)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        # stdout must be consumable as `udid=$(device_wda.sh device)`
        self.assertEqual(r.stdout.strip(), "00008101-AAA")
        self.assertIn("OK: analysis device", r.stderr)

    def test_resolved_device_persists_structured_device_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "device-profile.json"
            r = run_device(ONE, extra_env={"CLONE_DEVICE_PROFILE_FILE": str(profile)})
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            value = json.loads(profile.read_text(encoding="utf-8"))

        self.assertEqual(value["udid"], "00008101-AAA")
        self.assertEqual(value["name"], "heewook의 iPhone")
        self.assertEqual(value["marketingName"], "iPhone 12 mini")
        self.assertEqual(value["productType"], "iPhone13,1")
        self.assertEqual(value["osVersion"], "26.5.2")
        self.assertEqual(value["osBuild"], "23F84")
        self.assertEqual(value["connectionState"], "connected")

    def test_paired_but_disconnected_is_not_a_device(self):
        r = run_device(NONE_CONNECTED)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("ERROR: no connected iPhone", r.stderr)

    def test_no_device_opens_the_clone_xcode_project_for_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp)
            opened = stub_dir / "opened.txt"
            opener = stub_dir / "open"
            opener.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$*\" > {opened}\n"
            )
            opener.chmod(0o755)
            project = stub_dir / "CloneWorkspace.xcodeproj"
            project.mkdir()
            r = run_device(
                NONE_CONNECTED,
                extra_env={
                    "PATH": f"{stub_dir}:{os.environ['PATH']}",
                    "CLONE_AUTO_OPEN_XCODE": "1",
                    "CLONE_XCODE_PROJECT": str(project),
                    "CLONE_XCODE_RECOVERY_TIMEOUT": "0",
                },
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("opening Xcode project", r.stderr)
            self.assertEqual(opened.read_text().strip(), f"-a Xcode {project}")

    def test_xcode_recovery_accepts_a_device_that_appears_after_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_dir = Path(tmp)
            connected_fixture = stub_dir / "connected.json"
            connected_fixture.write_text(devicectl_json(ONE), encoding="utf-8")
            opener = stub_dir / "open"
            opener.write_text(
                "#!/usr/bin/env bash\n"
                'cp "$CLONE_TEST_CONNECTED_JSON" "$CLONE_DEVICES_JSON"\n'
            )
            opener.chmod(0o755)
            project = stub_dir / "CloneWorkspace.xcodeproj"
            project.mkdir()
            r = run_device(
                NONE_CONNECTED,
                extra_env={
                    "PATH": f"{stub_dir}:{os.environ['PATH']}",
                    "CLONE_AUTO_OPEN_XCODE": "1",
                    "CLONE_XCODE_PROJECT": str(project),
                    "CLONE_XCODE_RECOVERY_TIMEOUT": "2",
                    "CLONE_TEST_CONNECTED_JSON": str(connected_fixture),
                },
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertEqual(r.stdout.strip(), "00008101-AAA")

    def test_ambiguous_selection_fails_loudly(self):
        r = run_device(TWO)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("00008101-AAA", r.stderr)
        self.assertIn("00008120-BBB", r.stderr)

    def test_selector_disambiguates_by_name(self):
        r = run_device(TWO, "14 Pro")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(r.stdout.strip(), "00008120-BBB")

    def test_selector_disambiguates_by_udid(self):
        r = run_device(TWO, "00008101-AAA")
        self.assertEqual(r.stdout.strip(), "00008101-AAA")

    def test_unmatched_selector_fails(self):
        r = run_device(ONE, "iPad")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")


class TestSigningTeamResolution(unittest.TestCase):
    """WDA cannot install unsigned, so `session` resolves a team before anything else.

    The first implementation read ~/.autobot/.env with `sed -n 's/\\(A\\|B\\)=//p'`,
    which silently matches nothing on BSD sed (no alternation in basic regex) —
    every real run failed with "no signing team" despite the value being there.
    """

    def _run(self, env_body: str | None, bundle_id: str = "com.example.target") -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as home:
            if env_body is not None:
                cfg = Path(home) / ".autobot"
                cfg.mkdir()
                (cfg / ".env").write_text(env_body)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("DEVELOPMENT_TEAM", "TEAM_ID")}
            env["HOME"] = home
            env["CLONE_STATE_DIR"] = str(Path(home) / "state")
            env["CLONE_AUTO_START_APPIUM"] = "0"
            # Port chosen to be closed: getting past the team check must surface
            # as an Appium connection error, not a signing error.
            env["APPIUM_URL"] = "http://127.0.0.1:1"
            env["CLONE_WDA_TIMEOUT"] = "5"
            return subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA", bundle_id],
                capture_output=True, text=True, env=env,
            )

    def _automatic_tunnel_env(self, root: Path, marker: Path, registry_port: int):
        bin_dir = root / "bin"
        bin_dir.mkdir()
        order_log = root / "order.log"
        appium_log = root / "appium-args.log"
        sudo_log = root / "sudo-args.log"

        opener = bin_dir / "open"
        opener.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'open\\n' >> \"$CLONE_TEST_ORDER_LOG\"\n",
            encoding="utf-8",
        )
        appium = bin_dir / "appium"
        appium.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'tunnel\\n' >> \"$CLONE_TEST_ORDER_LOG\"\n"
            "printf '%s\\n' \"$*\" >> \"$CLONE_TEST_APPIUM_ARGS\"\n"
            "sleep \"${CLONE_TEST_TUNNEL_DELAY:-0}\"\n"
            "touch \"$CLONE_TEST_TUNNEL_MARKER\"\n",
            encoding="utf-8",
        )
        sudo = bin_dir / "sudo"
        sudo.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${CLONE_TEST_SUDO_FAIL:-0}\" == \"1\" ]]; then exit 1; fi\n"
            "printf '%s\\n' \"$*\" >> \"$CLONE_TEST_SUDO_ARGS\"\n"
            "[[ \"${1:-}\" == \"-n\" ]] && shift\n"
            "exec \"$@\"\n",
            encoding="utf-8",
        )
        for executable in (opener, appium, sudo):
            executable.chmod(0o755)

        profile = root / "device-profile.json"
        profile.write_text(json.dumps({
            "udid": "00008101-AAA",
            "osVersion": "26.5.2",
        }), encoding="utf-8")
        project = root / "CloneWorkspace.xcodeproj"
        project.mkdir()
        state = root / "state"
        env = {
            **os.environ,
            "HOME": str(root / "home"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CI": "1",
            "DEVELOPMENT_TEAM": "72J2BT27K5",
            "CLONE_DEVICE_PROFILE_FILE": str(profile),
            "CLONE_XCODE_PROJECT": str(project),
            "CLONE_STATE_DIR": str(state),
            "CLONE_SUDO_BIN": str(sudo),
            "CLONE_TUNNEL_REGISTRY_URL": (
                f"http://127.0.0.1:{registry_port}/remotexpc/tunnels"
            ),
            "CLONE_TUNNEL_START_TRIES": "30",
            "CLONE_TUNNEL_POLL_INTERVAL": "0.02",
            "CLONE_TUNNEL_STATUS_TIMEOUT": "0.1",
            "CLONE_AUTO_START_APPIUM": "0",
            "APPIUM_URL": "http://127.0.0.1:1",
            "CLONE_TEST_ORDER_LOG": str(order_log),
            "CLONE_TEST_APPIUM_ARGS": str(appium_log),
            "CLONE_TEST_SUDO_ARGS": str(sudo_log),
            "CLONE_TEST_TUNNEL_MARKER": str(marker),
        }
        return env, state, order_log, appium_log, sudo_log

    def test_reads_team_id_from_global_env(self):
        r = self._run("TEAM_ID=72J2BT27K5\n")
        self.assertNotIn("no signing team", r.stderr)
        self.assertIn("Appium did not answer", r.stderr)

    def test_reads_development_team_and_strips_quotes(self):
        r = self._run('DEVELOPMENT_TEAM="72J2BT27K5"\n')
        self.assertNotIn("no signing team", r.stderr)

    def test_fails_clearly_when_no_team_anywhere(self):
        r = self._run(None)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no signing team", r.stderr)

    def test_requires_target_bundle_id(self):
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "DEVELOPMENT_TEAM": "72J2BT27K5"}
            r = subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA"],
                capture_output=True, text=True, env=env,
            )
        self.assertEqual(r.returncode, 1)
        self.assertIn("session <udid> <bundle_id>", r.stderr)

    def test_session_binds_appium_to_target_bundle_id(self):
        received: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"value": {"ready": True}})

            def do_POST(self):
                received.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._reply({"value": {"sessionId": "session-1"}})

            def do_DELETE(self):
                self._reply({"value": None})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            descriptor = state / "wda-session.json"
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                env = {**os.environ, "DEVELOPMENT_TEAM": "72J2BT27K5",
                       "APPIUM_URL": appium_url, "CLONE_STATE_DIR": str(state)}
                r = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env,
                )
                descriptor_value = json.loads(descriptor.read_text(encoding="utf-8"))
                quit_result = subprocess.run(
                    ["bash", str(SCRIPT), "quit", "session-1"],
                    capture_output=True, text=True, env=env,
                )
                descriptor_exists_after_quit = descriptor.exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        caps = received["capabilities"]["alwaysMatch"]
        self.assertEqual(caps["appium:bundleId"], "com.example.target")
        self.assertEqual(descriptor_value, {
            "sid": "session-1",
            "udid": "00008101-AAA",
            "bundleId": "com.example.target",
            "appiumUrl": appium_url,
        })
        self.assertEqual(quit_result.returncode, 0, msg=quit_result.stderr)
        self.assertFalse(descriptor_exists_after_quit)

    def test_ios_18_plus_profile_can_opt_out_of_tunnel_auto_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "device-profile.json"
            profile.write_text(json.dumps({
                "udid": "00008101-AAA",
                "osVersion": "26.5.2",
            }), encoding="utf-8")
            env = {
                **os.environ,
                "DEVELOPMENT_TEAM": "72J2BT27K5",
                "CLONE_DEVICE_PROFILE_FILE": str(profile),
                "CLONE_TUNNEL_READY": "0",
                "CLONE_AUTO_START_TUNNEL": "0",
                "CLONE_AUTO_START_APPIUM": "0",
                "APPIUM_URL": "http://127.0.0.1:1",
            }
            result = subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                capture_output=True, text=True, env=env,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RemoteXPC tunnel", result.stderr)
        self.assertIn("sudo appium driver run xcuitest tunnel-creation", result.stderr)
        self.assertNotIn("Appium did not answer", result.stderr)

    def test_pre_ios_18_profile_does_not_require_remotexpc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile = root / "device-profile.json"
            profile.write_text(json.dumps({
                "udid": "00008101-AAA",
                "osVersion": "17.7",
            }), encoding="utf-8")
            env = {
                **os.environ,
                "DEVELOPMENT_TEAM": "72J2BT27K5",
                "CLONE_DEVICE_PROFILE_FILE": str(profile),
                "CLONE_TUNNEL_READY": "0",
                "CLONE_AUTO_START_APPIUM": "0",
                "APPIUM_URL": "http://127.0.0.1:1",
            }
            result = subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                capture_output=True, text=True, env=env,
            )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("RemoteXPC tunnel", result.stderr)
        self.assertIn("Appium did not answer", result.stderr)

    def test_existing_tunnel_is_reused_without_opening_xcode_or_starting_another(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, state, order_log, appium_log, sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                env["CLONE_TUNNEL_READY"] = "1"
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=5,
                )
                order_exists = order_log.exists()
                appium_exists = appium_log.exists()
                sudo_exists = sudo_log.exists()
                lock_exists = (state / "remotexpc-tunnel-start.lock").exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1)
        self.assertIn("RemoteXPC tunnel ready", result.stderr)
        self.assertIn("Appium did not answer", result.stderr)
        self.assertFalse(order_exists)
        self.assertFalse(appium_exists)
        self.assertFalse(sudo_exists)
        self.assertFalse(lock_exists)

    def test_missing_tunnel_opens_xcode_then_starts_and_verifies_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, state, order_log, appium_log, sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=5,
                )
                order_lines = order_log.read_text(encoding="utf-8").splitlines()
                appium_args = appium_log.read_text(encoding="utf-8")
                sudo_args = sudo_log.read_text(encoding="utf-8")
                lock_exists = (state / "remotexpc-tunnel-start.lock").exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        self.assertEqual(order_lines, ["open", "tunnel"])
        self.assertIn("driver run xcuitest tunnel-creation -- --udid 00008101-AAA", appium_args)
        self.assertIn(f"--tunnel-registry-port {server.server_port}", appium_args)
        self.assertIn("--disconnect-retry-max-attempts 0", appium_args)
        self.assertIn("-n /bin/sh -c", sudo_args)
        self.assertIn("RemoteXPC tunnel ready for 00008101-AAA", result.stderr)
        self.assertIn("Appium did not answer", result.stderr)
        self.assertFalse(lock_exists)

    def test_headless_authorization_failure_returns_without_waiting_for_password(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, state, order_log, appium_log, _sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                env["CLONE_TEST_SUDO_FAIL"] = "1"
                started_at = time.monotonic()
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=5,
                )
                elapsed = time.monotonic() - started_at
                order_lines = order_log.read_text(encoding="utf-8").splitlines()
                appium_exists = appium_log.exists()
                lock_exists = (state / "remotexpc-tunnel-start.lock").exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1)
        self.assertLess(elapsed, 4)
        self.assertEqual(order_lines, ["open"])
        self.assertFalse(appium_exists)
        self.assertIn("could not obtain administrator authorization", result.stderr)
        self.assertIn("sudo -v", result.stderr)
        self.assertFalse(lock_exists)

    def test_gui_authorization_fallback_starts_tunnel_after_sudo_cache_miss(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, _state, _order_log, _appium_log, _sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                osascript_log = root / "osascript.log"
                osascript = root / "bin" / "osascript"
                osascript.write_text(
                    "#!/usr/bin/env bash\n"
                    "printf '%s\\n' \"$*\" >> \"$CLONE_TEST_OSASCRIPT_ARGS\"\n"
                    "exec /bin/sh -c \"$2\"\n",
                    encoding="utf-8",
                )
                osascript.chmod(0o755)
                env.pop("CI")
                env.update({
                    "CLONE_TEST_SUDO_FAIL": "1",
                    "CLONE_OSASCRIPT_BIN": str(osascript),
                    "CLONE_TEST_OSASCRIPT_ARGS": str(osascript_log),
                })
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=5,
                )
                osascript_args = osascript_log.read_text(encoding="utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        self.assertIn("requesting macOS administrator authorization", result.stderr)
        self.assertIn("tunnel-creation", osascript_args)
        self.assertIn("RemoteXPC tunnel ready for 00008101-AAA", result.stderr)
        self.assertIn("Appium did not answer", result.stderr)

    def test_registry_with_only_another_udid_never_unblocks_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker, udid="00008120-OTHER")
            try:
                env, state, _order_log, _appium_log, sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                env["CLONE_TUNNEL_START_TRIES"] = "10"
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=5,
                )
                tunnel_launch_count = len(sudo_log.read_text(encoding="utf-8").splitlines())
                lock_exists = (state / "remotexpc-tunnel-start.lock").exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(tunnel_launch_count, 1)
        self.assertIn("did not publish 00008101-AAA", result.stderr)
        self.assertNotIn("Appium did not answer", result.stderr)
        self.assertFalse(lock_exists)

    def test_concurrent_sessions_start_only_one_tunnel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, state, _order_log, appium_log, _sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                env["CLONE_TEST_TUNNEL_DELAY"] = "0.2"
                command = [
                    "bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target",
                ]
                first = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, env=env)
                second = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, env=env)
                try:
                    first_stdout, first_stderr = first.communicate(timeout=10)
                    second_stdout, second_stderr = second.communicate(timeout=10)
                finally:
                    for process in (first, second):
                        if process.poll() is None:
                            process.terminate()
                            process.communicate(timeout=2)
                appium_start_count = len(appium_log.read_text(encoding="utf-8").splitlines())
                lock_exists = (state / "remotexpc-tunnel-start.lock").exists()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(first.returncode, 1, msg=first_stdout + first_stderr)
        self.assertEqual(second.returncode, 1, msg=second_stdout + second_stderr)
        self.assertEqual(appium_start_count, 1)
        combined = first_stderr + second_stderr
        self.assertIn("another device_wda.sh process is starting", combined)
        self.assertGreaterEqual(combined.count("RemoteXPC tunnel ready"), 2)
        self.assertFalse(lock_exists)

    def test_session_uses_isolated_wda_copy_when_appium_source_exists(self):
        received: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"value": {"ready": True}})

            def do_POST(self):
                received.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._reply({"value": {"sessionId": "session-1"}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "appium" / "node_modules" / "appium-xcuitest-driver" / "node_modules" / "appium-webdriveragent"
            (source / "WebDriverAgent.xcodeproj").mkdir(parents=True)
            scripts = source / "Scripts"
            scripts.mkdir()
            (scripts / "embed-runner-icon.sh").write_text("#!/bin/bash\necho original\n")
            target = root / "isolated-wda"
            expected_post_action = (SCRIPT.parent / "wda_post_action.sh").read_text()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = {
                    **os.environ,
                    "DEVELOPMENT_TEAM": "72J2BT27K5",
                    "APPIUM_HOME": str(root / "appium"),
                    "CLONE_WDA_BOOTSTRAP": str(target),
                    "CLONE_STATE_DIR": str(root / "state"),
                    "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                }
                r = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env,
                )
                actual_post_action = (target / "Scripts" / "embed-runner-icon.sh").read_text()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        caps = received["capabilities"]["alwaysMatch"]
        self.assertEqual(caps["appium:bootstrapPath"], str(target))
        self.assertEqual(caps["appium:agentPath"], str(target / "WebDriverAgent.xcodeproj"))
        self.assertEqual(actual_post_action, expected_post_action)

    def test_matching_live_session_is_reused_and_target_guard_uses_cached_bundle(self):
        calls = {"status": 0, "session_get": 0, "session_create": 0, "active": 0}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/status":
                    calls["status"] += 1
                    self._reply({"value": {"ready": True}})
                else:
                    calls["session_get"] += 1
                    self._reply({"value": {"capabilities": {
                        "appium:udid": "00008101-AAA",
                        "appium:bundleId": "com.example.target",
                    }}})

            def do_POST(self):
                if self.path == "/session":
                    calls["session_create"] += 1
                    self._reply({"value": {"sessionId": "unexpected"}})
                else:
                    calls["active"] += 1
                    self._reply({"value": {"bundleId": "com.example.target"}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            state.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                descriptor = {
                    "sid": "session-1",
                    "udid": "00008101-AAA",
                    "bundleId": "com.example.target",
                    "appiumUrl": appium_url,
                }
                (state / "wda-session.json").write_text(json.dumps(descriptor), encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": appium_url, "CLONE_STATE_DIR": str(state)}
                reused = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env,
                )
                lib = root / "wda_lib.sh"
                lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                               encoding="utf-8")
                guarded = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; _assert_target session-1"],
                    capture_output=True, text=True, env=env,
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(reused.returncode, 0, msg=reused.stderr)
        self.assertEqual(reused.stdout.strip(), "session-1")
        self.assertIn("reusing live WDA session", reused.stderr)
        self.assertEqual(guarded.returncode, 0, msg=guarded.stderr)
        self.assertEqual(calls["session_create"], 0)
        self.assertEqual(calls["session_get"], 1,
                         msg="_assert_target should trust the matching local descriptor")
        self.assertEqual(calls["active"], 1)

    def test_active_app_guard_rejects_a_foreign_foreground_app(self):
        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"value": {"capabilities": {"appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                self._reply({"value": {"bundleId": "com.example.other"}})

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                lib = Path(temp) / "wda_lib.sh"
                lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                               encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": f"http://127.0.0.1:{server.server_port}"}
                r = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; _assert_target session-1"],
                    capture_output=True, text=True, env=env,
                )
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(r.returncode, 1)
        self.assertIn("expected com.example.target, active com.example.other", r.stderr)

    def test_step_reuses_final_settle_source_and_logs_state_and_behavior_evidence(self):
        before = (
            '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            '<XCUIElementTypeCell type="XCUIElementTypeCell" label="user.one" name="user.one"'
            ' enabled="true" visible="true" x="0" y="100" width="375" height="60"/>'
            '</XCUIElementTypeApplication></AppiumAUT>'
        )
        after = before.replace("user.one", "user.two")
        state = {"tapped": False, "source_gets": 0, "session_gets": 0, "screenshots": 0}
        png_bytes = b"fixture-png"

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/source"):
                    state["source_gets"] += 1
                    self._reply({"value": after if state["tapped"] else before})
                elif self.path.endswith("/screenshot"):
                    state["screenshots"] += 1
                    self._reply({"value": base64.b64encode(png_bytes).decode()})
                else:
                    state["session_gets"] += 1
                    self._reply({"value": {"capabilities": {
                        "appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/actions"):
                    state["tapped"] = True
                    self._reply({"value": {}})
                else:
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_tree = root / "source.xml"
            source_tree.write_text(before, encoding="utf-8")
            outdir = root / "raw"
            flow = root / "flow.jsonl"
            state_dir = root / "state"
            state_dir.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                descriptor = {
                    "sid": "session-1",
                    "udid": "00008101-AAA",
                    "bundleId": "com.example.target",
                    "appiumUrl": appium_url,
                }
                (state_dir / "wda-session.json").write_text(json.dumps(descriptor), encoding="utf-8")
                env = {
                    **os.environ,
                    "APPIUM_URL": appium_url,
                    "CLONE_STATE_DIR": str(state_dir),
                    "CLONE_FLOW_LOG": str(flow),
                    "CLONE_TAP_SETTLE_TRIES": "1",
                }
                r = subprocess.run(
                    ["bash", str(SCRIPT), "step", "session-1", "187", "130",
                     str(source_tree), str(outdir), "destination"],
                    capture_output=True, text=True, env=env,
                )
                events = [json.loads(line) for line in flow.read_text(encoding="utf-8").splitlines()]
                final_xml = (outdir / "destination.xml").read_text(encoding="utf-8")
                final_png = (outdir / "destination.png").read_bytes()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(state["source_gets"], 2,
                         msg="step must use freshness + final settle source, with no screen refetch")
        self.assertEqual(state["session_gets"], 0,
                         msg="matching descriptor should avoid GET /session during target guard")
        self.assertEqual(state["screenshots"], 1)
        self.assertEqual(final_xml, after)
        self.assertEqual(final_png, png_bytes)
        self.assertEqual([event["type"] for event in events], ["tap", "screen"])
        tap, screen = events
        self.assertEqual(tap["evidence"], "durable")
        self.assertEqual(tap["via"], "step")
        self.assertNotEqual(tap["behavior"], "?")
        self.assertNotEqual(tap["from_state"], "?")
        self.assertNotEqual(tap["to_state"], "?")
        self.assertEqual(tap["tree"], str(outdir / "destination.xml"))
        self.assertIn("from", tap)
        self.assertIn("to", tap)
        self.assertEqual(screen["state"], tap["to_state"])
        self.assertEqual(screen["node"], tap["to"])
        self.assertEqual(screen["tree"], str(outdir / "destination.xml"))

    def test_swipe_waits_for_settle_and_records_a_flow_event(self):
        before = (
            '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="가" name="가" enabled="true"'
            ' visible="true" x="0" y="100" width="100" height="40"/>'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="나" name="나" enabled="true"'
            ' visible="true" x="0" y="200" width="100" height="40"/>'
            '</XCUIElementTypeApplication></AppiumAUT>'
        )
        after = before.replace('label="나" name="나"', 'label="다" name="다"')
        state = {"swiped": False}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/source"):
                    self._reply({"value": after if state["swiped"] else before})
                else:
                    self._reply({"value": {"capabilities": {"appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/actions"):
                    state["swiped"] = True
                    self._reply({"value": {}})
                else:
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                lib = root / "wda_lib.sh"
                log = root / "flow.jsonl"
                (root / "device_a11y.py").write_text(
                    (SCRIPT.parent / "device_a11y.py").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                               encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                       "CLONE_FLOW_LOG": str(log), "CLONE_SWIPE_SETTLE_TRIES": "1"}
                r = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; cmd_swipe session-1 180 700 180 200"],
                    capture_output=True, text=True, env=env,
                )
                event = json.loads(log.read_text(encoding="utf-8").strip())
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(event["type"], "swipe")
        self.assertEqual(event["changed"], "true",
                         msg=f"event={event} stdout={r.stdout!r} stderr={r.stderr!r}")
        self.assertNotEqual(event["from_state"], "?")
        self.assertNotEqual(event["to_state"], "?")
        self.assertIn("from", event)
        self.assertIn("to", event)
        self.assertEqual(event["x1"], "180")
        self.assertEqual(event["y2"], "200")

    def test_type_uses_accessibility_id_without_logging_input_value(self):
        received: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"value": {"capabilities": {"appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/element"):
                    received["find"] = payload
                    self._reply({"value": {"element-6066-11e4-a52e-4f735466cecf": "element-1"}})
                else:
                    received["value"] = payload
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                lib = root / "wda_lib.sh"
                log = root / "flow.jsonl"
                lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                               encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                       "CLONE_FLOW_LOG": str(log)}
                r = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; cmd_type session-1 field-id sensitive-value"],
                    capture_output=True, text=True, env=env,
                )
                flow = log.read_text(encoding="utf-8")
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(received["find"], {"using": "accessibility id", "value": "field-id"})
        self.assertEqual(received["value"], {"text": "sensitive-value"})
        self.assertNotIn("sensitive-value", flow)
        self.assertIn('"type": "input"', flow)
        self.assertIn('"length": "15"', flow)


class TestManagedAppiumDoctorAndMetrics(unittest.TestCase):
    def test_auto_start_is_bounded_and_captures_pid_and_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            starts = root / "starts.log"
            appium = bin_dir / "appium"
            appium.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'start\\n' >> \"$CLONE_TEST_START_LOG\"\n"
                "trap 'exit 0' TERM INT\n"
                "while :; do sleep 1; done\n",
                encoding="utf-8",
            )
            appium.chmod(0o755)
            state = root / "state"
            env = {
                **os.environ,
                "HOME": str(root / "home"),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "DEVELOPMENT_TEAM": "72J2BT27K5",
                "APPIUM_URL": f"http://127.0.0.1:{unused_local_port()}",
                "CLONE_STATE_DIR": str(state),
                "CLONE_AUTO_START_APPIUM": "1",
                # Leave enough wall time for the fake process to be scheduled
                # on a busy Xcode/Appium host while keeping the poll bounded.
                "CLONE_APPIUM_START_TRIES": "10",
                "CLONE_APPIUM_POLL_INTERVAL": "0.05",
                "CLONE_APPIUM_STATUS_TIMEOUT": "0.1",
                "CLONE_TEST_START_LOG": str(starts),
            }
            started_at = time.monotonic()
            r = subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                capture_output=True, text=True, env=env, timeout=5,
            )
            elapsed = time.monotonic() - started_at
            start_lines = (starts.read_text(encoding="utf-8").splitlines()
                           if starts.exists() else [])
            appium_log = ((state / "appium-server.log").read_text(encoding="utf-8")
                          if (state / "appium-server.log").exists() else "<missing>")

            self.assertEqual(r.returncode, 1)
            self.assertLess(elapsed, 4)
            self.assertEqual(start_lines, ["start"],
                             msg=f"stderr={r.stderr!r} appium_log={appium_log!r}")
            self.assertTrue((state / "appium-server.log").exists())
            self.assertFalse((state / "appium-server.pid").exists())
            self.assertIn("bounded poll", r.stderr)

    def test_live_managed_pid_prevents_duplicate_server_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            starts = root / "starts.log"
            appium = bin_dir / "appium"
            appium.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'unexpected\\n' >> \"$CLONE_TEST_START_LOG\"\n",
                encoding="utf-8",
            )
            appium.chmod(0o755)
            state = root / "state"
            state.mkdir()
            existing = subprocess.Popen(["sleep", "5"])
            try:
                (state / "appium-server.pid").write_text(f"{existing.pid}\n", encoding="utf-8")
                env = {
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "DEVELOPMENT_TEAM": "72J2BT27K5",
                    "APPIUM_URL": f"http://127.0.0.1:{unused_local_port()}",
                    "CLONE_STATE_DIR": str(state),
                    "CLONE_APPIUM_START_TRIES": "1",
                    "CLONE_APPIUM_POLL_INTERVAL": "0.01",
                    "CLONE_APPIUM_STATUS_TIMEOUT": "0.1",
                    "CLONE_TEST_START_LOG": str(starts),
                }
                r = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env,
                )
            finally:
                existing.terminate()
                existing.wait(timeout=2)

            self.assertEqual(r.returncode, 1)
            self.assertFalse(starts.exists())
            self.assertIn("waiting instead of launching a duplicate", r.stderr)

    def test_normal_session_quit_does_not_stop_managed_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_DELETE(self):
                body = b'{"value":null}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            state.mkdir()
            managed = subprocess.Popen(["sleep", "5"])
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                pid_file = state / "appium-server.pid"
                pid_file.write_text(f"{managed.pid}\n", encoding="utf-8")
                env = {**os.environ,
                       "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                       "CLONE_STATE_DIR": str(state)}
                r = subprocess.run(
                    ["bash", str(SCRIPT), "quit", "session-1"],
                    capture_output=True, text=True, env=env,
                )
                still_running = managed.poll() is None
                pid_still_recorded = pid_file.exists()
            finally:
                managed.terminate()
                managed.wait(timeout=2)
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertTrue(still_running)
        self.assertTrue(pid_still_recorded)

    def test_doctor_reports_actionable_blockers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            appium = bin_dir / "appium"
            appium.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"--version\" ]]; then echo 3.5.2; exit 0; fi\n"
                "if [[ \"$1 $2 $3\" == \"driver list --installed\" ]]; then echo xcuitest; exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            appium.chmod(0o755)
            devices = root / "devices.json"
            devices.write_text(devicectl_json(NONE_CONNECTED), encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("DEVELOPMENT_TEAM", "TEAM_ID")}
            env.update({
                "HOME": str(root / "home"),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "APPIUM_URL": f"http://127.0.0.1:{unused_local_port()}",
                "CLONE_DEVICES_JSON": str(devices),
                "CLONE_STATE_DIR": str(root / "state"),
                "CLONE_APPIUM_STATUS_TIMEOUT": "0.1",
                "CLONE_MIN_DISK_MB": "999999999",
            })
            r = subprocess.run(
                ["bash", str(SCRIPT), "doctor"],
                capture_output=True, text=True, env=env,
            )

        output = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1)
        self.assertIn("OK: appium 3.5.2", output)
        self.assertIn("xcuitest driver is installed", output)
        self.assertIn("no signing team", output)
        self.assertIn("no connected physical iPhone", output)
        self.assertIn("disk free", output)
        self.assertIn("doctor found", output)

    def test_doctor_prepares_missing_tunnel_after_other_checks_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            appium = bin_dir / "appium"
            appium.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"--version\" ]]; then echo 3.5.2; exit 0; fi\n"
                "if [[ \"$1 $2 $3\" == \"driver list --installed\" ]]; then echo xcuitest; exit 0; fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            appium.chmod(0o755)
            lib = root / "wda-lib.sh"
            lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                           encoding="utf-8")
            ensured = root / "ensured.txt"
            command = f"""
source '{lib}'
_appium_status() {{ return 0; }}
_team() {{ printf '72J2BT27K5'; }}
_collect_connected_devices() {{ udids=('00008101-AAA'); names=('Phone'); }}
_persist_device_profile() {{ return 0; }}
_device_requires_tunnel() {{ return 0; }}
_tunnel_registry_ready() {{ return 1; }}
_ensure_tunnel() {{ printf '%s\\n' "$1" > '{ensured}'; return 0; }}
cmd_doctor
"""
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "CLONE_MIN_DISK_MB": "0",
                "APPIUM_URL": "http://127.0.0.1:1",
            }
            result = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True, env=env,
            )
            ensured_udid = ensured.read_text(encoding="utf-8").strip()

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(ensured_udid, "00008101-AAA")
        self.assertIn("RemoteXPC tunnel prepared", result.stdout)
        self.assertIn("doctor passed", result.stdout)

    def test_http_metrics_do_not_corrupt_response_body(self):
        payload = {"value": {"ready": True}, "sentinel": "body"}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lib = root / "wda_lib.sh"
            lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                           encoding="utf-8")
            state = root / "state"
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/status"
                env = {**os.environ, "CLONE_STATE_DIR": str(state), "CLONE_METRICS": "1"}
                r = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; _curl '{url}'"],
                    capture_output=True, text=True, env=env,
                )
                metrics = [json.loads(line) for line in
                           (state / "http-metrics.jsonl").read_text(encoding="utf-8").splitlines()]
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(json.loads(r.stdout), payload)
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["method"], "GET")
        self.assertEqual(metrics[0]["status"], 200)
        self.assertEqual(metrics[0]["url"], url)
        self.assertEqual(metrics[0]["exitCode"], 0)


class TestFlowLogging(unittest.TestCase):
    """The exploration log must never change the verdict of what it logs.

    A tap that physically happened, reported as a failure because the log path
    was unwritable, makes the exploration loop retry it — double-tapping a real
    phone. So `_flow_event` warns and returns success. Sourced directly because
    the tap path itself needs a live Appium session.
    """

    def _call(self, log_path: str, tmp: Path) -> subprocess.CompletedProcess:
        lib = tmp / "wda_lib.sh"
        body = SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', "")
        lib.write_text(body, encoding="utf-8")
        env = dict(os.environ, CLONE_FLOW_LOG=log_path)
        return subprocess.run(
            ["bash", "-c", f"set -euo pipefail; source {lib}; _flow_event tap from=a to=b"],
            capture_output=True, text=True, env=env,
        )

    def test_an_unwritable_log_warns_but_succeeds(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._call("/nonexistent/deep/flow.jsonl", Path(d))
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN: could not append", r.stdout)

    def test_events_are_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "sub" / "flow.jsonl"   # parent created on demand
            r = self._call(str(log), Path(d))
            self.assertEqual(r.returncode, 0)
            event = json.loads(log.read_text(encoding="utf-8").strip())
            self.assertEqual({event["from"], event["to"], event["type"]}, {"a", "b", "tap"})
            self.assertRegex(event["at"], r"^20\d\d-\d\d-\d\dT")


if __name__ == "__main__":
    unittest.main()
