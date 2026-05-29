"""Phase-0 axe preflight: env_snapshot.capture records axe availability+version."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import env_snapshot  # noqa: E402


class TestAxePreflight(unittest.TestCase):
    def test_axe_present_records_true_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            def fake_which(name):
                return "/usr/local/bin/axe" if name == "axe" else None
            def fake_run(cmd, *, timeout=15):
                if cmd[:2] == ["axe", "--version"]:
                    return 0, "axe 1.2.3\n"
                return 127, ""
            with mock.patch.object(env_snapshot.shutil, "which", side_effect=fake_which), \
                 mock.patch.object(env_snapshot, "_run", side_effect=fake_run):
                snap = env_snapshot.capture(proj)
            self.assertIn("environment", snap)
            self.assertTrue(snap["environment"]["axe"])
            self.assertEqual(snap["environment"]["axeVersion"], "axe 1.2.3")
            # round-trips to disk (read inside the tempdir scope)
            on_disk = json.loads((proj / env_snapshot.SNAPSHOT_PATH).read_text())
            self.assertTrue(on_disk["environment"]["axe"])

    def test_axe_absent_records_false_and_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(env_snapshot.shutil, "which", return_value=None):
                snap = env_snapshot.capture(Path(tmp))
        self.assertFalse(snap["environment"]["axe"])
        self.assertIsNone(snap["environment"]["axeVersion"])

    def test_simulator_field_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(env_snapshot.shutil, "which", return_value=None):
                snap = env_snapshot.capture(Path(tmp))
        self.assertIn("simulator", snap)  # still present (None on this host)


if __name__ == "__main__":
    unittest.main()
