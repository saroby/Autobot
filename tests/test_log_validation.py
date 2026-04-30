"""Event log validation — schema enforcement via spec.logEvents."""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, run_build_log


class TestLogValidation(IsolatedProjectCase):

    def test_unknown_event_rejected(self):
        result = run_build_log("--event", "totally_invalid_xyz", "--phase", "5", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown event", (result.stdout + result.stderr).lower())

    def test_missing_required_field_rejected(self):
        # build_attempt requires 'detail'.
        result = run_build_log("--event", "build_attempt", "--phase", "5", project_dir=self.project_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires field 'detail'", result.stdout + result.stderr)

    def test_valid_event_accepted(self):
        result = run_build_log(
            "--event", "learning_applied",
            "--phase", "1", "--agent", "architect",
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_detail_schema_missing_required_field(self):
        # build_attempt detail must contain attempt/errors/succeeded.
        result = run_build_log(
            "--event", "build_attempt", "--phase", "5",
            "--detail", '{"attempt": 1}',
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        msg = result.stdout + result.stderr
        self.assertIn("detail missing required key", msg)

    def test_detail_schema_wrong_type(self):
        # 'errors' must be integer; pass a string.
        result = run_build_log(
            "--event", "build_attempt", "--phase", "5",
            "--detail", '{"attempt": 1, "errors": "many", "succeeded": false}',
            project_dir=self.project_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected integer", result.stdout + result.stderr)

    def test_detail_schema_valid_payload_accepted(self):
        result = run_build_log(
            "--event", "build_attempt", "--phase", "5",
            "--detail", '{"attempt": 1, "errors": 8, "succeeded": false}',
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
