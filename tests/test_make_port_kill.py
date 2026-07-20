"""port-targets.mk kill-port — starts a real listener, asserts make frees it."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

MK = Path(__file__).resolve().parent.parent / "skills" / "autobot-make" / "references" / "port-targets.mk"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _is_listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _make_kill(port: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["make", "-f", str(MK), "kill-port", f"PORTS={port}"],
        capture_output=True, text=True,
    )


class TestKillPort(unittest.TestCase):
    def test_frees_an_occupied_port(self):
        port = _free_port()
        server = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not _is_listening(port):
                time.sleep(0.1)
            self.assertTrue(_is_listening(port), "listener failed to start")

            r = _make_kill(port)
            self.assertEqual(r.returncode, 0, msg=r.stderr)  # 0 also proves Makefile tabs are valid
            self.assertIn("freeing port", r.stdout)

            deadline = time.time() + 5
            while time.time() < deadline and _is_listening(port):
                time.sleep(0.1)
            self.assertFalse(_is_listening(port), "port still occupied after kill-port")
        finally:
            server.kill()
            server.wait(timeout=5)

    def test_free_port_is_a_noop(self):
        port = _free_port()  # nothing bound
        r = _make_kill(port)
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("already free", r.stdout)


if __name__ == "__main__":
    unittest.main()
