"""set-flag command: whitelist + flag_changed event."""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, run_pipeline


class TestSetFlag(IsolatedProjectCase):

    def test_backend_required_toggle(self):
        result = run_pipeline(
            "set-flag", "--key", "backend_required", "--value", "true",
            "--reason", "test", project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self.state()["backend_required"], True)

        events = [e for e in self.log_lines() if e["event"] == "flag_changed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"]["key"], "backend_required")
        self.assertEqual(events[0]["detail"]["from"], False)
        self.assertEqual(events[0]["detail"]["to"], True)

    def test_unknown_flag_rejected(self):
        result = run_pipeline(
            "set-flag", "--key", "totally_made_up", "--value", "true",
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported flag", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
