"""device_wda.sh device gate — offline via the CLONE_DEVICES_JSON fixture.

The gate is what makes /autobot:copy stop instead of degrading when no iPhone
is attached, so its three outcomes (one device / none / ambiguous) are pinned
here. `paired` must never count as connected: a phone can hold a trust record
for weeks after its transport is gone (observed 2026-07-25 — devicectl reported
`pairingState: paired` with `transportType: None` on an unplugged device).

Session/screen/tap/swipe are thin HTTP passthroughs to Appium and are not
exercised here; they were verified against a real device instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_wda.sh"


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


def run_device(devices: list[tuple[str, str, str]], *argv: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(devicectl_json(devices))
        fixture = f.name
    try:
        env = {**os.environ, "CLONE_DEVICES_JSON": fixture}
        return subprocess.run(
            ["bash", str(SCRIPT), "device", *argv],
            capture_output=True, text=True, env=env,
        )
    finally:
        os.unlink(fixture)


ONE = [("00008101-AAA", "heewook의 iPhone", "connected")]
NONE_CONNECTED = [("00008101-AAA", "heewook의 iPhone", "unavailable")]
TWO = [
    ("00008101-AAA", "heewook의 iPhone", "connected"),
    ("00008120-BBB", "iPhone 14 Pro", "connected"),
]


class TestCloneWdaDeviceGate(unittest.TestCase):
    def test_prints_bare_udid_on_stdout(self):
        r = run_device(ONE)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        # stdout must be consumable as `udid=$(device_wda.sh device)`
        self.assertEqual(r.stdout.strip(), "00008101-AAA")
        self.assertIn("OK: analysis device", r.stderr)

    def test_paired_but_disconnected_is_not_a_device(self):
        r = run_device(NONE_CONNECTED)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("ERROR: no connected iPhone", r.stderr)

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

    def _run(self, env_body: str | None) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as home:
            if env_body is not None:
                cfg = Path(home) / ".autobot"
                cfg.mkdir()
                (cfg / ".env").write_text(env_body)
            env = {k: v for k, v in os.environ.items()
                   if k not in ("DEVELOPMENT_TEAM", "TEAM_ID")}
            env["HOME"] = home
            # Port chosen to be closed: getting past the team check must surface
            # as an Appium connection error, not a signing error.
            env["APPIUM_URL"] = "http://127.0.0.1:1"
            env["CLONE_WDA_TIMEOUT"] = "5"
            return subprocess.run(
                ["bash", str(SCRIPT), "session", "00008101-AAA"],
                capture_output=True, text=True, env=env,
            )

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
            self.assertEqual(json.loads(log.read_text(encoding="utf-8").strip()),
                             {"from": "a", "to": "b", "type": "tap"})


if __name__ == "__main__":
    unittest.main()
