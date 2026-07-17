"""Docker missing on a backend_required app must DEGRADE, not abort the build.

Previously check_backend_required_consistent emitted a hard-fail docker_available
result, so a backend_required idea on a Mac without Docker produced nothing. It
now degrades (skipped+degraded) so the iOS app + backend code are still built.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks import setup  # noqa: E402


def _docker_result(proj: Path):
    results = setup.check_backend_required_consistent(proj, "Demo", {"backend_required": True})
    return next(r for r in results if r["check"] == "docker_available")


class TestBackendDockerDegrade(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / "Demo" / "Models").mkdir(parents=True)
        (self.proj / "Demo" / "Models" / "APIContracts.swift").write_text("// contracts\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_docker_missing_degrades_not_hard_fails(self):
        with mock.patch.object(setup.subprocess, "run", side_effect=FileNotFoundError):
            r = _docker_result(self.proj)
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"), "docker-missing must be a skip, not a hard fail")
        self.assertTrue(r.get("degraded"), "docker-missing must be marked degraded")

    def test_docker_present_passes(self):
        with mock.patch.object(setup.subprocess, "run", return_value=mock.Mock(returncode=0)):
            r = _docker_result(self.proj)
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_backend_not_required_skips_cleanly(self):
        results = setup.check_backend_required_consistent(self.proj, "Demo", {"backend_required": False})
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["passed"])
        self.assertTrue(results[0].get("skipped"))

    def test_backend_not_required_but_present_degrades(self):
        # Reverse-direction guard: backend/ on a backend_required=false build
        # is misdispatched backend-engineer output — DEGRADED, never hard.
        (self.proj / "backend").mkdir()
        results = setup.check_backend_required_consistent(self.proj, "Demo", {"backend_required": False})
        row = next(r for r in results if r["check"] == "backend_not_required_but_present")
        self.assertFalse(row["passed"])
        self.assertTrue(row.get("skipped"), row)
        self.assertTrue(row.get("degraded"), row)


if __name__ == "__main__":
    unittest.main()
