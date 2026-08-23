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

# Generous on purpose. These bound how long the SCRIPT may take, not how fast
# the host must be — and under a full-suite run the host is busy. A 5s bound
# failed one of them there while passing every time on its own, which is the
# 2026-08-15 lesson: scheduling delay is not a readiness failure.
SUBPROCESS_TIMEOUT = 20
FLOW_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_flow.py"


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
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
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
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
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

    def test_tunnel_start_does_not_depend_on_nohup_detaching_from_console(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "ready"
            server, thread = start_tunnel_registry(marker)
            try:
                env, _state, _order_log, appium_log, _sudo_log = self._automatic_tunnel_env(
                    root, marker, server.server_port,
                )
                nohup = root / "bin" / "nohup"
                nohup.write_text(
                    "#!/usr/bin/env bash\n"
                    "echo 'nohup: cannot detach from console' >&2\n"
                    "exit 91\n",
                    encoding="utf-8",
                )
                nohup.chmod(0o755)
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
                )
                appium_args = appium_log.read_text(encoding="utf-8")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(result.returncode, 1, msg=result.stderr)
        self.assertIn("driver run xcuitest tunnel-creation", appium_args)
        self.assertIn("RemoteXPC tunnel ready for 00008101-AAA", result.stderr)
        self.assertIn("Appium did not answer", result.stderr)

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
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
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
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
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
                    capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
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
                # The winner starts the fake Appium as a child; on a loaded host
                # that child can still be waiting to be scheduled when both
                # sessions have already exited, and reading immediately raised
                # FileNotFoundError instead of testing anything. Same class as
                # the 2026-08-15 lesson: give the first instruction wall time,
                # keep the assertion exact.
                for _ in range(40):
                    if appium_log.exists():
                        break
                    time.sleep(0.05)
                appium_start_count = len(
                    appium_log.read_text(encoding="utf-8").splitlines()
                ) if appium_log.exists() else 0
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

    def test_new_session_applies_perf_settings(self):
        """Clone owns settling (sig polling), so WDA idle/animation waits are
        double-waiting — a fresh session must zero them via the settings API."""
        result, posts = self._run_session_with_settings_server({})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        settings = [body for path, body in posts if path.endswith("/appium/settings")]
        self.assertEqual(len(settings), 1)
        self.assertEqual(settings[0]["settings"], {
            "waitForIdleTimeout": 0,
            "animationCoolOffTimeout": 0,
        })

    def test_perf_settings_knobs_and_optional_snapshot_depth(self):
        result, posts = self._run_session_with_settings_server({
            "CLONE_WDA_IDLE_TIMEOUT": "3",
            "CLONE_WDA_ANIM_COOLOFF": "2",
            "CLONE_WDA_SNAPSHOT_MAX_DEPTH": "60",
        })
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        settings = [body for path, body in posts if path.endswith("/appium/settings")]
        self.assertEqual(settings[0]["settings"], {
            "waitForIdleTimeout": 3,
            "animationCoolOffTimeout": 2,
            "snapshotMaxDepth": 60,
        })

    def test_perf_settings_can_be_disabled(self):
        result, posts = self._run_session_with_settings_server({"CLONE_WDA_TUNE": "0"})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            [path for path, _ in posts if path.endswith("/appium/settings")], [])

    def test_perf_settings_failure_does_not_fail_the_session(self):
        result, posts = self._run_session_with_settings_server({}, settings_status=500)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "session-1")
        self.assertIn("continuing untuned", result.stderr)

    def _run_session_with_settings_server(
        self, extra_env: dict[str, str], settings_status: int = 200,
    ) -> tuple[subprocess.CompletedProcess, list[tuple[str, dict]]]:
        posts: list[tuple[str, dict]] = []

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict, status: int = 200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"value": {"ready": True}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                posts.append((self.path, body))
                if self.path.endswith("/appium/settings"):
                    self._reply({"value": None}, status=settings_status)
                else:
                    self._reply({"value": {"sessionId": "session-1"}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = {**os.environ, "DEVELOPMENT_TEAM": "72J2BT27K5",
                       "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                       "CLONE_STATE_DIR": str(state), **extra_env}
                result = subprocess.run(
                    ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                    capture_output=True, text=True, env=env,
                )
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()
        return result, posts

    def test_matching_live_session_is_reused_and_target_guard_uses_cached_bundle(self):
        calls = {"status": 0, "session_get": 0, "session_create": 0, "active": 0,
                 "settings": 0}

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
                elif self.path.endswith("/appium/settings"):
                    calls["settings"] += 1
                    self._reply({"value": None})
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
        self.assertEqual(calls["settings"], 1,
                         msg="a reused session must be re-tuned (settings are per session)")

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
                # Producer/reader contract: the log the shell writes must be
                # readable by device_flow.py (2026-08-16: `state=`/`from_state=`
                # were emitted while the reader hard-rejects those aliases, so
                # every real exploration log failed next/stats/map).
                flow_result = subprocess.run(
                    ["python3", str(FLOW_SCRIPT), "stats", str(flow)],
                    capture_output=True, text=True,
                )
                # Same boundary, second consumer: `explore` now walks the whole
                # app by asking next-tap what to do from the capture it just
                # took, so that command must read this producer's log and this
                # producer's tree — not a hand-authored fixture of either.
                next_tap_result = subprocess.run(
                    ["python3", str(FLOW_SCRIPT), "next-tap", str(flow),
                     str(outdir / "destination.xml")],
                    capture_output=True, text=True,
                )
                final_xml = (outdir / "destination.xml").read_text(encoding="utf-8")
                final_png = (outdir / "destination.png").read_bytes()
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertEqual(flow_result.returncode, 0,
                         msg="device_flow.py must read the log device_wda.sh writes: "
                             + flow_result.stderr + flow_result.stdout)
        self.assertEqual(next_tap_result.returncode, 0,
                         msg="device_flow.py next-tap must read the log and tree device_wda.sh "
                             "writes: " + next_tap_result.stderr + next_tap_result.stdout)
        self.assertNotIn("ERROR", next_tap_result.stderr)
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
        self.assertNotEqual(tap["from_statekey"], "?")
        self.assertNotEqual(tap["to_statekey"], "?")
        self.assertEqual(tap["tree"], str(outdir / "destination.xml"))
        self.assertIn("from", tap)
        self.assertIn("to", tap)
        self.assertEqual(screen["statekey"], tap["to_statekey"])
        self.assertEqual(screen["node"], tap["to"])
        self.assertEqual(screen["tree"], str(outdir / "destination.xml"))

    def _run_explore(self, *explore_args: str):
        """Fake device: one screen, two safe buttons (both no-op taps) and one
        withheld 팔로우 button. Explore must drain the two safe targets by
        itself and never touch the withheld one."""
        tree_xml = (
            '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="가" name="가" enabled="true"'
            ' visible="true" x="0" y="100" width="100" height="40"/>'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="나" name="나" enabled="true"'
            ' visible="true" x="0" y="200" width="100" height="40"/>'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="팔로우" name="팔로우"'
            ' enabled="true" visible="true" x="0" y="300" width="100" height="40"/>'
            '</XCUIElementTypeApplication></AppiumAUT>'
        )
        taps: list[str] = []

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
                    self._reply({"value": tree_xml})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"png").decode()})
                else:
                    self._reply({"value": {"capabilities": {
                        "appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/actions"):
                    taps.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                    self._reply({"value": {}})
                else:
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outdir = root / "raw"
            flow = root / "flow.jsonl"
            state_dir = root / "state"
            state_dir.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                (state_dir / "wda-session.json").write_text(json.dumps({
                    "sid": "session-1", "udid": "00008101-AAA",
                    "bundleId": "com.example.target", "appiumUrl": appium_url,
                }), encoding="utf-8")
                env = {
                    **os.environ,
                    "APPIUM_URL": appium_url,
                    "CLONE_STATE_DIR": str(state_dir),
                    "CLONE_FLOW_LOG": str(flow),
                    "CLONE_TAP_SETTLE_TRIES": "1",
                }
                r = subprocess.run(
                    ["bash", str(SCRIPT), "explore", "session-1", str(outdir), *explore_args],
                    capture_output=True, text=True, env=env,
                )
                events = [json.loads(line)
                          for line in flow.read_text(encoding="utf-8").splitlines()]
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()
        return r, events, taps

    def test_explore_drains_the_safe_frontier_without_a_human_per_tap(self):
        r, events, taps = self._run_explore()
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        self.assertIn("explore made 2 step(s)", r.stdout)
        # The stop condition is the GLOBAL frontier, not this one screen: with a
        # single screen in the log the two are the same, and explore must not
        # end by telling a human to go navigate somewhere themselves.
        self.assertIn("frontier empty", r.stdout)
        self.assertNotIn("navigate elsewhere", r.stdout)
        tap_labels = [e["label"] for e in events if e["type"] == "tap"]
        self.assertEqual(sorted(tap_labels), ["가", "나"])
        self.assertNotIn("팔로우", "".join(tap_labels))
        # A 600ms pointerMove is the scroll gesture, not a tap. Explore tries one
        # scroll before giving up (a drained capture is not a drained app), and
        # this fake serves a static tree, so the scroll moves nothing and stops.
        gestures = [body for body in taps if '"duration":600' not in body.replace(" ", "")]
        self.assertEqual(len(gestures), 2, msg="withheld targets must never be tapped")
        self.assertIn("did not move — end of content", r.stdout)
        # Every tap left durable evidence the reader accepts.
        # The trailing swipe+screen is the scroll attempt and its evidence. It is
        # recorded even though it moved nothing — "we looked and there was no
        # more" is a finding, and `changed=false` keeps it out of capture_gaps.
        self.assertEqual([e["type"] for e in events],
                         ["screen", "tap", "screen", "tap", "screen", "swipe", "screen"])
        self.assertEqual([e for e in events if e["type"] == "swipe"][0]["changed"], "false")

    def test_explore_respects_max_steps(self):
        r, events, taps = self._run_explore("1")
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        self.assertIn("reached max steps (1)", r.stdout)
        self.assertEqual(len(taps), 1)

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
        # A swipe SCROLLS: the elements that survive it move. Renaming a label in
        # place is the signature of content churn (a like count ticking), which
        # must not be reported as a transition — see TestSwipeChurn below.
        after = (before.replace('y="100"', 'y="40"').replace('y="200"', 'y="140"'))
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
                       "CLONE_FLOW_LOG": str(log), "CLONE_SWIPE_SETTLE_TRIES": "3"}
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
        self.assertNotEqual(event["from_statekey"], "?")
        self.assertNotEqual(event["to_statekey"], "?")
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

    def test_type_refinds_once_after_stale_element_reference(self):
        received = {"finds": 0, "values": []}

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload: dict, status: int = 200):
                body = json.dumps(payload).encode()
                self.send_response(status)
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
                    received["finds"] += 1
                    self._reply({"value": {
                        "element-6066-11e4-a52e-4f735466cecf":
                            f"element-{received['finds']}"
                    }})
                elif self.path.endswith("/element/element-1/value"):
                    received["values"].append(payload)
                    self._reply({"value": {"error": "stale element reference"}}, status=404)
                else:
                    received["values"].append(payload)
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
        self.assertEqual(received["finds"], 2)
        self.assertEqual(received["values"], [
            {"text": "sensitive-value"}, {"text": "sensitive-value"}
        ])
        self.assertIn("re-finding 'field-id' once", r.stderr)
        self.assertNotIn("sensitive-value", flow)
        self.assertEqual(flow.count('"type": "input"'), 1)


class TestManagedAppiumDoctorAndMetrics(unittest.TestCase):
    def test_launchctl_backed_start_records_job_and_pid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            launchctl_log = root / "launchctl.log"
            launchctl = bin_dir / "launchctl"
            launchctl.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$CLONE_TEST_LAUNCHCTL_LOG\"\n"
                "if [[ \"${1:-}\" == \"print\" ]]; then\n"
                "  printf '\\tpid = %s\\n' \"$CLONE_TEST_JOB_PID\"\n"
                "fi\n",
                encoding="utf-8",
            )
            launchctl.chmod(0o755)
            appium = bin_dir / "appium"
            appium.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            appium.chmod(0o755)
            state = root / "state"
            lib = root / "wda-lib.sh"
            lib.write_text(SCRIPT.read_text(encoding="utf-8").replace('main "$@"\n', ""),
                           encoding="utf-8")
            managed = subprocess.Popen(["sleep", "5"])
            try:
                env = {
                    **os.environ,
                    "HOME": str(root / "home"),
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "CLONE_STATE_DIR": str(state),
                    "CLONE_LAUNCHCTL_BIN": str(launchctl),
                    "CLONE_TEST_LAUNCHCTL_LOG": str(launchctl_log),
                    "CLONE_TEST_JOB_PID": str(managed.pid),
                }
                result = subprocess.run(
                    ["bash", "-c", f"source '{lib}'; _start_managed_appium_server 127.0.0.1 4723 ''"],
                    capture_output=True, text=True, env=env,
                )
                launchctl_args = (launchctl_log.read_text(encoding="utf-8")
                                  if launchctl_log.exists() else "")
                pid_value = ((state / "appium-server.pid").read_text(encoding="utf-8").strip()
                             if (state / "appium-server.pid").exists() else "")
                label_value = ((state / "appium-server.label").read_text(encoding="utf-8").strip()
                               if (state / "appium-server.label").exists() else "")
            finally:
                managed.terminate()
                managed.wait(timeout=2)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), str(managed.pid))
        self.assertEqual(pid_value, str(managed.pid))
        self.assertTrue(label_value.startswith("com.autobot.clone.appium.4723."))
        self.assertIn("submit -l", launchctl_args)
        self.assertIn("-o", launchctl_args)
        self.assertIn("appium server --address 127.0.0.1 --port 4723", launchctl_args)

    def test_stop_server_removes_launchctl_job_and_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            launchctl_log = root / "launchctl.log"
            appium = bin_dir / "appium-test-server"
            appium.write_text(
                "#!/usr/bin/env bash\n"
                "trap 'exit 0' TERM INT\n"
                "while :; do sleep 1; done\n",
                encoding="utf-8",
            )
            appium.chmod(0o755)
            managed = subprocess.Popen([str(appium)])
            reaper = threading.Thread(target=managed.wait, daemon=True)
            reaper.start()
            state = root / "state"
            state.mkdir()
            label = "com.autobot.clone.appium.4723.1234"
            (state / "appium-server.pid").write_text(f"{managed.pid}\n", encoding="utf-8")
            (state / "appium-server.label").write_text(f"{label}\n", encoding="utf-8")
            launchctl = bin_dir / "launchctl"
            launchctl.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$CLONE_TEST_LAUNCHCTL_LOG\"\n"
                "if [[ \"${1:-}\" == \"remove\" ]]; then\n"
                "  kill \"$CLONE_TEST_JOB_PID\"\n"
                "fi\n",
                encoding="utf-8",
            )
            launchctl.chmod(0o755)
            try:
                env = {
                    **os.environ,
                    "CLONE_STATE_DIR": str(state),
                    "CLONE_LAUNCHCTL_BIN": str(launchctl),
                    "CLONE_TEST_LAUNCHCTL_LOG": str(launchctl_log),
                    "CLONE_TEST_JOB_PID": str(managed.pid),
                    "CLONE_APPIUM_STOP_TRIES": "20",
                }
                result = subprocess.run(
                    ["bash", str(SCRIPT), "stop-server"],
                    capture_output=True, text=True, env=env,
                )
                launchctl_args = launchctl_log.read_text(encoding="utf-8")
                pid_exists = (state / "appium-server.pid").exists()
                label_exists = (state / "appium-server.label").exists()
            finally:
                if managed.poll() is None:
                    managed.terminate()
                managed.wait(timeout=2)
                reaper.join(timeout=2)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"remove {label}", launchctl_args)
        self.assertFalse(pid_exists)
        self.assertFalse(label_exists)

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
                # This test pins the non-launchctl fallback path.
                "CLONE_APPIUM_USE_LAUNCHCTL": "0",
                "CLONE_APPIUM_START_TRIES": "10",
                "CLONE_APPIUM_POLL_INTERVAL": "0.05",
                "CLONE_APPIUM_STATUS_TIMEOUT": "0.01",
                "CLONE_TEST_START_LOG": str(starts),
            }
            started_at = time.monotonic()
            r = subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA", "com.example.target"],
                capture_output=True, text=True, env=env, timeout=SUBPROCESS_TIMEOUT,
            )
            elapsed = time.monotonic() - started_at
            start_lines = (starts.read_text(encoding="utf-8").splitlines()
                           if starts.exists() else [])
            appium_log = ((state / "appium-server.log").read_text(encoding="utf-8")
                          if (state / "appium-server.log").exists() else "<missing>")

            self.assertEqual(r.returncode, 1)
            self.assertLess(elapsed, 4)
            # The spawn is proven by stderr; starts.log may miss the line when
            # the bounded poll TERMs the child before it is even scheduled, so
            # it only guards against DUPLICATE starts (racy assertEqual(["start"])
            # flaked on busy hosts).
            self.assertIn("started managed Appium server", r.stderr)
            self.assertLessEqual(len(start_lines), 1,
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


class TestLiveContentDoesNotBlockTaps(unittest.TestCase):
    """A live feed must not freeze exploration.

    Measured on Threads 2026-08-22: between the capture and the tap a like count
    ticked 226 -> 227. The old guard compared `sig` (a hash of the label set), so
    it rejected every candidate and `explore` made 0 steps on a real device — the
    skill could not observe the app at all. The guard must accept content churn
    and still refuse a screen that actually moved.
    """

    APP = ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
           '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
           ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
           '<XCUIElementTypeButton type="XCUIElementTypeButton" label="\uac00" name="\uac00" enabled="true"'
           ' visible="true" x="0" y="100" width="100" height="40"/>'
           '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="LIKES" name="LIKES"'
           ' enabled="true" visible="true" x="0" y="300" width="200" height="20"/>'
           '</XCUIElementTypeApplication></AppiumAUT>')

    def _step(self, live: str) -> tuple[subprocess.CompletedProcess, list[dict]]:
        captured = self.APP.replace("LIKES", "\uc88b\uc544\uc694 226\uba85")

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
                    self._reply({"value": live})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()})
                else:
                    self._reply({"value": {"capabilities": {"appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
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
                tree = root / "auto-0001.xml"
                tree.write_text(captured, encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": f"http://127.0.0.1:{server.server_port}",
                       "CLONE_FLOW_LOG": str(log), "CLONE_TAP_SETTLE_TRIES": "1"}
                r = subprocess.run(
                    ["bash", "-c",
                     f"source '{lib}'; cmd_step session-1 50 120 '{tree}' '{root}' auto-0002"],
                    capture_output=True, text=True, env=env,
                )
                raw = log.read_text(encoding="utf-8") if log.exists() else ""
                events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()
        return r, events

    def test_a_ticking_counter_does_not_reject_the_tap(self):
        live = self.APP.replace("LIKES", "\uc88b\uc544\uc694 227\uba85")
        r, events = self._step(live)
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        self.assertTrue([e for e in events if e["type"] == "tap"],
                        msg="the tap must happen despite the label churn")

    def test_a_screen_that_really_moved_is_still_refused_and_is_retryable(self):
        live = self.APP.replace(
            '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="LIKES" name="LIKES"'
            ' enabled="true" visible="true" x="0" y="300" width="200" height="20"/>', "")
        r, events = self._step(live)
        self.assertEqual(r.returncode, 2,
                         msg=f"guard rejections must be retryable (2), got {r.returncode}: {r.stderr}")
        self.assertIn("screen changed since", r.stderr)
        self.assertEqual([e for e in events if e["type"] == "tap"], [],
                         msg="a refused tap must never be logged as having happened")


class TestSwipeChurnIsNotAScroll(unittest.TestCase):
    """`changed` on a swipe must mean the screen moved, not that text changed.

    device_flow.py demands a durable destination capture for every changed
    action, so a swipe that reports `changed=true` because a like count ticked
    leaves a coverage gap that can never be closed. Measured on Threads
    2026-08-22: counters move on their own every few seconds.
    """

    BEFORE = ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
              '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
              ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
              '<XCUIElementTypeButton type="XCUIElementTypeButton" label="\uac00" name="\uac00"'
              ' enabled="true" visible="true" x="0" y="100" width="100" height="40"/>'
              '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="LIKES" name="LIKES"'
              ' enabled="true" visible="true" x="0" y="300" width="200" height="20"/>'
              '</XCUIElementTypeApplication></AppiumAUT>')

    def _swipe(self, after: str) -> dict:
        before = self.BEFORE.replace("LIKES", "\uc88b\uc544\uc694 226\uba85")
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
                       "CLONE_FLOW_LOG": str(log), "CLONE_SWIPE_SETTLE_TRIES": "3"}
                subprocess.run(
                    ["bash", "-c", f"source '{lib}'; cmd_swipe session-1 180 700 180 200"],
                    capture_output=True, text=True, env=env,
                )
                return json.loads(log.read_text(encoding="utf-8").strip())
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_a_ticking_counter_is_not_a_changed_swipe(self):
        after = self.BEFORE.replace("LIKES", "\uc88b\uc544\uc694 227\uba85")
        self.assertEqual(self._swipe(after)["changed"], "false",
                         msg="text changing in place is churn, not a scroll")

    def test_a_scroll_under_unchanged_labels_is_still_a_changed_swipe(self):
        # `sig` cannot see this one: the label set is identical, only y moved.
        after = (self.BEFORE.replace("LIKES", "\uc88b\uc544\uc694 226\uba85")
                 .replace('y="100"', 'y="40"').replace('y="300"', 'y="240"'))
        self.assertEqual(self._swipe(after)["changed"], "true")


class TestExploreScrollsForMoreCandidates(unittest.TestCase):
    """A drained capture is not a drained app.

    Measured on Threads 2026-08-22: exploration ended after the first screenful
    and reported 34 of 235 targets, because everything below the fold was never
    on a capture. `next-tap` already distinguished "nothing on this capture" from
    "frontier empty"; explore treated both as done.
    """

    def _app(self, *buttons: tuple[str, int]) -> str:
        rows = "".join(
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="%s" name="%s"'
            ' enabled="true" visible="true" x="0" y="%d" width="100" height="40"/>'
            % (label, label, y) for label, y in buttons)
        return ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
                '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App"'
                ' label="App" enabled="true" visible="true" x="0" y="0" width="375"'
                ' height="812">' + rows + '</XCUIElementTypeApplication></AppiumAUT>')

    def test_a_candidate_below_the_fold_is_reached_by_scrolling(self):
        top = self._app(("\uac00", 100))
        # After the scroll the same row moved up and a second one came into view.
        bottom = self._app(("\uac00", 40), ("\ub098", 300))
        state = {"scrolled": False}
        bodies: list[str] = []

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
                    self._reply({"value": bottom if state["scrolled"] else top})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"png").decode()})
                else:
                    self._reply({"value": {"capabilities": {
                        "appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/actions"):
                    body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                    bodies.append(body)
                    if '"duration":600' in body.replace(" ", ""):
                        state["scrolled"] = True
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
                state_dir = root / "state"
                state_dir.mkdir()
                flow = root / "flow.jsonl"
                appium_url = f"http://127.0.0.1:{server.server_port}"
                (state_dir / "wda-session.json").write_text(json.dumps({
                    "sid": "session-1", "udid": "00008101-AAA",
                    "bundleId": "com.example.target", "appiumUrl": appium_url,
                }), encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": appium_url,
                       "CLONE_STATE_DIR": str(state_dir), "CLONE_FLOW_LOG": str(flow),
                       "CLONE_TAP_SETTLE_TRIES": "1", "CLONE_SWIPE_SETTLE_TRIES": "2",
                       "CLONE_EXPLORE_MAX_SCROLL": "2"}
                r = subprocess.run(
                    ["bash", str(SCRIPT), "explore", "session-1", str(root / "raw"), "6"],
                    capture_output=True, text=True, env=env,
                )
                events = [json.loads(line) for line in
                          flow.read_text(encoding="utf-8").splitlines() if line.strip()]
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        tapped = [e.get("label") for e in events if e["type"] == "tap"]
        self.assertIn("\ub098", tapped,
                      msg=f"the row revealed by scrolling was never tapped: {r.stdout}\n{r.stderr}")
        self.assertIn("scrolled for more candidates", r.stdout)
        swipes = [e for e in events if e["type"] == "swipe"]
        self.assertTrue(swipes and swipes[0]["changed"] == "true",
                        msg="a scroll that moved the screen must record changed=true")


class TestLeavingTheAppIsRecoverable(unittest.TestCase):
    """A tap that opens another app must not poison the flow graph.

    Measured on Threads 2026-08-22: tapping "Instagram으로 전환" switched apps,
    Appium's /source then described Instagram, and that screen was written as a
    state of com.burbn.barcelona — it would have been measured, spec'd and
    mapped to a SwiftUI view as a Threads screen. Exploration then ended.
    """

    TARGET = "com.example.target"
    OTHER = "com.example.other"

    def _tree(self, label: str) -> str:
        return ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
                '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App"'
                ' label="App" enabled="true" visible="true" x="0" y="0" width="375"'
                ' height="812">'
                '<XCUIElementTypeButton type="XCUIElementTypeButton" label="%s" name="%s"'
                ' enabled="true" visible="true" x="0" y="100" width="100" height="40"/>'
                '</XCUIElementTypeApplication></AppiumAUT>' % (label, label))

    def test_the_foreign_screen_is_not_a_state_and_the_walk_continues(self):
        target, other = self.TARGET, self.OTHER
        home, away = self._tree("\uc804\ud658"), self._tree("\ub2e4\ub978\uc571")
        state = {"app": target, "tapped": 0}

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
                    self._reply({"value": away if state["app"] == other else home})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"png").decode()})
                else:
                    self._reply({"value": {"capabilities": {"appium:bundleId": target}}})

            def do_POST(self):
                if self.path.endswith("/execute/sync"):
                    body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                    if "activateApp" in body:
                        state["app"] = target
                        self._reply({"value": {}})
                    else:
                        self._reply({"value": {"bundleId": state["app"]}})
                elif self.path.endswith("/actions"):
                    self.rfile.read(int(self.headers["Content-Length"]))
                    state["tapped"] += 1
                    if state["tapped"] == 1:
                        state["app"] = other      # the first tap leaves the app
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
                state_dir = root / "state"
                state_dir.mkdir()
                flow = root / "flow.jsonl"
                appium_url = f"http://127.0.0.1:{server.server_port}"
                (state_dir / "wda-session.json").write_text(json.dumps({
                    "sid": "session-1", "udid": "00008101-AAA",
                    "bundleId": target, "appiumUrl": appium_url,
                }), encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": appium_url,
                       "CLONE_STATE_DIR": str(state_dir), "CLONE_FLOW_LOG": str(flow),
                       "CLONE_TAP_SETTLE_TRIES": "1", "CLONE_SWIPE_SETTLE_TRIES": "1",
                       "CLONE_REACTIVATE_TRIES": "3", "CLONE_EXPLORE_MAX_SCROLL": "0"}
                r = subprocess.run(
                    ["bash", str(SCRIPT), "explore", "session-1", str(root / "raw"), "4"],
                    capture_output=True, text=True, env=env,
                )
                events = [json.loads(line) for line in
                          flow.read_text(encoding="utf-8").splitlines() if line.strip()]
                captures = sorted(q.name for q in (root / "raw").glob("*.xml"))
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)
        exits = [e for e in events if e.get("left_app")]
        self.assertTrue(exits, msg="leaving the app must be recorded as a transition")
        self.assertEqual(exits[0]["left_app"], other)
        self.assertEqual(exits[0]["evidence"], "foreign-app")
        # The destination is another app, not a state of this one. Recording the
        # foreign statekey here would make observed_edges route toward a state
        # that has no screen event, and capture_gaps demand an arrival capture
        # that is deliberately never written — a gap nothing can close.
        self.assertEqual(exits[0]["changed"], "false")
        self.assertEqual(exits[0]["to_statekey"], "?")
        self.assertEqual(exits[0]["to"], "?")
        # No screen event may point at a capture taken while the other app was up.
        self.assertNotIn("left the app", "".join(
            str(e) for e in events if e["type"] == "screen"))
        self.assertIn("re-activated", r.stderr)
        self.assertTrue(captures, msg="the walk must resume with a fresh capture")


if __name__ == "__main__":
    unittest.main()


class TestTunnelStatusGate(unittest.TestCase):
    """Can this run reach the device without asking anyone for a password?

    The tunnel is created several minutes into a run, at `doctor`, which is a
    bad place to discover that nobody can authenticate. This answers it up
    front — and refuses to answer when it cannot, because a gate that passes on
    a mismatch is worse than no gate.
    """

    def status(self, profile: dict | None, udid: str, **env) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "device-profile.json"
            if profile is not None:
                path.write_text(json.dumps(profile), encoding="utf-8")
            return subprocess.run(
                ["bash", str(SCRIPT), "tunnel-status", udid],
                capture_output=True, text=True,
                env={**os.environ, "CLONE_DEVICE_PROFILE_FILE": str(path), **env})

    def test_no_profile_refuses_instead_of_passing(self):
        r = self.status(None, "00008101-AAA")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no device profile", r.stderr)

    def test_a_profile_for_another_device_refuses_instead_of_passing(self):
        # Measured 2026-08-23: handed the CoreDevice identifier while the
        # profile records the hardware one, this answered OK for a device on
        # iOS 26 that very much needed a tunnel.
        r = self.status({"udid": "00008101-AAA", "osVersion": "26.6"}, "74859CB7-BBB")
        self.assertEqual(r.returncode, 2)
        self.assertIn("describes '00008101-AAA'", r.stderr)

    def test_an_older_device_needs_no_tunnel(self):
        r = self.status({"udid": "00008101-AAA", "osVersion": "17.5"}, "00008101-AAA")
        self.assertEqual(r.returncode, 0)
        self.assertIn("does not need", r.stdout)

    def test_a_registered_tunnel_is_ready(self):
        r = self.status({"udid": "00008101-AAA", "osVersion": "26.6"}, "00008101-AAA",
                        CLONE_TUNNEL_READY="1")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ready", r.stdout)

    def test_a_missing_tunnel_is_reported_as_work_to_do(self):
        r = self.status({"udid": "00008101-AAA", "osVersion": "26.6"}, "00008101-AAA",
                        CLONE_TUNNEL_READY="0")
        self.assertEqual(r.returncode, 1)
        self.assertIn("needs a RemoteXPC tunnel", r.stderr)


class TestExploreTypesIntoTextFields(unittest.TestCase):
    """A text field on screen is a door the tap walk cannot open.

    Exploration never typed, so every search screen was a dead end — the
    results behind it exist only past the keyboard. The probe is generic and
    never logged; the flow records which field and where the screen went.
    """

    def _run(self):
        # Screen A: one text field, no safe taps. After typing, the device
        # shows screen B (a results list) — a different statekey.
        tree_a = (
            '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            '<XCUIElementTypeTextField type="XCUIElementTypeTextField" name="search-field"'
            ' label="" value="검색" enabled="true" visible="true" x="20" y="100" width="300" height="40"/>'
            '</XCUIElementTypeApplication></AppiumAUT>'
        )
        tree_b = (
            '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            '<XCUIElementTypeNavigationBar type="XCUIElementTypeNavigationBar" name="결과" label="결과"'
            ' enabled="true" visible="true" x="0" y="44" width="375" height="44"/>'
            '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="결과 1" name="결과 1"'
            ' enabled="true" visible="true" x="0" y="120" width="375" height="40"/>'
            '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" label="결과 2" name="결과 2"'
            ' enabled="true" visible="true" x="0" y="170" width="375" height="40"/>'
            '</XCUIElementTypeApplication></AppiumAUT>'
        )
        state = {"typed": False, "bodies": []}

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
                    self._reply({"value": tree_b if state["typed"] else tree_a})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"png").decode()})
                else:
                    self._reply({"value": {"capabilities": {
                        "appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                state["bodies"].append((self.path, body))
                if self.path.endswith("/execute/sync"):
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/element"):
                    self._reply({"value": {"element-6066-11e4-a52e-4f735466cecf": "el-1"}})
                elif "/element/el-1/value" in self.path:
                    state["typed"] = True
                    self._reply({"value": None})
                else:
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outdir, flow, state_dir = root / "raw", root / "flow.jsonl", root / "state"
            state_dir.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                (state_dir / "wda-session.json").write_text(json.dumps({
                    "sid": "session-1", "udid": "00008101-AAA",
                    "bundleId": "com.example.target", "appiumUrl": appium_url,
                }), encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": appium_url,
                       "CLONE_STATE_DIR": str(state_dir), "CLONE_FLOW_LOG": str(flow),
                       "CLONE_TAP_SETTLE_TRIES": "1", "CLONE_EXPLORE_MAX_SCROLL": "0",
                       "CLONE_EXPLORE_MAX_RESTART": "0", "CLONE_TYPE_SETTLE": "0",
                       "CLONE_EXPLORE_PROBE_TEXT": "secret-probe"}
                r = subprocess.run(["bash", str(SCRIPT), "explore", "session-1", str(outdir), "5"],
                                   capture_output=True, text=True, env=env)
                events = [json.loads(line) for line in flow.read_text(encoding="utf-8").splitlines()]
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()
        return r, events, state

    def test_a_text_field_is_typed_into_and_the_result_screen_is_captured(self):
        r, events, state = self._run()
        typed = [e for e in events if e.get("type") == "type"]
        self.assertEqual(len(typed), 1, msg=r.stdout + r.stderr)
        self.assertEqual(typed[0]["field"], "search-field")
        self.assertEqual(typed[0]["changed"], "true")
        self.assertNotEqual(typed[0]["from_statekey"], typed[0]["to_statekey"])
        # The results screen is real evidence: a screen event exists for it.
        self.assertTrue(any(e.get("type") == "screen" and e.get("statekey") == typed[0]["to_statekey"]
                            for e in events))

    def test_the_probe_text_is_never_written_to_the_log(self):
        r, events, state = self._run()
        self.assertNotIn("secret-probe", json.dumps(events, ensure_ascii=False))
        self.assertNotIn("secret-probe", r.stdout + r.stderr)

    def test_the_same_field_is_not_typed_into_twice(self):
        r, events, state = self._run()
        value_posts = [b for p, b in state["bodies"] if "/value" in p]
        self.assertEqual(len(value_posts), 1)


class TestExploreRestartsWhenBoxedIn(unittest.TestCase):
    """A screen with nothing left AND no observed route onward is not the end.

    Routing only knows transitions it has observed, so from a screen deep in
    the app there was no known way back to the screens still holding
    candidates — the walk ended there (2026-08-23: 422 of 522 targets
    untouched, and a reproduction whose buttons mostly did nothing). A
    relaunch reopens the map.
    """

    def _run(self, max_restart: str):
        # Home has one button leading to Detail. Detail has nothing safe to tap
        # and no observed way back. Home still has an untouched button "나"
        # only visible after the first visit (content churn).
        def tree(*buttons):
            rows = "".join(
                f'<XCUIElementTypeButton type="XCUIElementTypeButton" label="{b}" name="{b}"'
                f' enabled="true" visible="true" x="0" y="{100 + 60 * i}" width="100" height="40"/>'
                for i, b in enumerate(buttons))
            return ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
                    '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App"'
                    ' label="App" enabled="true" visible="true" x="0" y="0" width="375" height="812">'
                    + rows + '</XCUIElementTypeApplication></AppiumAUT>')
        home, detail = tree("가", "나"), tree("상세")
        state = {"screen": "home", "terminated": 0}

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
                    self._reply({"value": home if state["screen"] == "home" else detail})
                elif self.path.endswith("/screenshot"):
                    self._reply({"value": base64.b64encode(b"png").decode()})
                else:
                    self._reply({"value": {"capabilities": {"appium:bundleId": "com.example.target"}}})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                if self.path.endswith("/execute/sync"):
                    if "terminateApp" in body:
                        state["terminated"] += 1
                        state["screen"] = "home"
                    self._reply({"value": {"bundleId": "com.example.target"}})
                elif self.path.endswith("/actions"):
                    # Any tap on Home goes to Detail; taps on Detail do nothing.
                    if state["screen"] == "home":
                        state["screen"] = "detail"
                    self._reply({"value": {}})
                else:
                    self._reply({"value": {}})

            def log_message(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outdir, flow, state_dir = root / "raw", root / "flow.jsonl", root / "state"
            state_dir.mkdir()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                appium_url = f"http://127.0.0.1:{server.server_port}"
                (state_dir / "wda-session.json").write_text(json.dumps({
                    "sid": "session-1", "udid": "00008101-AAA",
                    "bundleId": "com.example.target", "appiumUrl": appium_url,
                }), encoding="utf-8")
                env = {**os.environ, "APPIUM_URL": appium_url,
                       "CLONE_STATE_DIR": str(state_dir), "CLONE_FLOW_LOG": str(flow),
                       "CLONE_TAP_SETTLE_TRIES": "1", "CLONE_EXPLORE_MAX_SCROLL": "0",
                       "CLONE_EXPLORE_MAX_RESTART": max_restart, "CLONE_RESTART_SETTLE": "0",
                       "CLONE_REACTIVATE_TRIES": "1"}
                r = subprocess.run(["bash", str(SCRIPT), "explore", "session-1", str(outdir), "12"],
                                   capture_output=True, text=True, env=env)
                events = [json.loads(line) for line in flow.read_text(encoding="utf-8").splitlines()]
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()
        return r, events, state

    def test_boxed_in_exploration_relaunches_and_keeps_going(self):
        r, events, state = self._run(max_restart="3")
        self.assertGreaterEqual(state["terminated"], 1, msg=r.stdout + r.stderr)
        self.assertIn("restarting the app", r.stdout)
        tapped = {e.get("label") for e in events if e.get("type") == "tap"}
        # Both Home buttons were reached — the second only after a relaunch.
        self.assertTrue({"가", "나"} <= tapped, msg=str(tapped))
        self.assertIn("coverage complete", r.stdout)

    def test_restarts_are_bounded(self):
        r, events, state = self._run(max_restart="0")
        self.assertEqual(state["terminated"], 0)
        self.assertNotIn("restarting the app", r.stdout)
