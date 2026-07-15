"""Event log validation — schema enforcement via spec.logEvents."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules, run_build_log, run_pipeline

import_runtime_modules()

from event_log import append_build_log  # noqa: E402


class TestLogValidation(unittest.TestCase):
    APP_NAME = "TestApp"
    DISPLAY_NAME = "Test"
    BUILD_ID = "build-test"

    def setUp(self) -> None:
        # Event validation needs only an initialized build identity. Keeping this
        # fixture independent of the Phase-0 environment gate means a low-disk or
        # no-Xcode host cannot turn focused log tests into environment tests.
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = Path(self._tmp.name)
        result = run_pipeline(
            "init-build",
            "--build-id", self.BUILD_ID,
            "--app-name", self.APP_NAME,
            "--display-name", self.DISPLAY_NAME,
            project_dir=self.project_dir,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def log_lines(self) -> list[dict]:
        log = self.project_dir / ".autobot" / "build-log.jsonl"
        if not log.is_file():
            return []
        return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]

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
        event = self.log_lines()[-1]
        self.assertEqual(event["buildId"], self.BUILD_ID)

    def test_explicit_build_id_must_match_current_state(self):
        with self.assertRaisesRegex(SystemExit, "buildId.*does not match"):
            append_build_log(
                self.project_dir,
                "learning_applied",
                phase="1",
                agent="architect",
                build_id="another-build",
            )

        log = self.project_dir / ".autobot" / "build-log.jsonl"
        self.assertNotIn(
            "another-build",
            log.read_text(encoding="utf-8") if log.is_file() else "",
        )

    def test_explicit_matching_build_id_is_written(self):
        append_build_log(
            self.project_dir,
            "learning_applied",
            phase="1",
            agent="architect",
            build_id=self.BUILD_ID,
        )
        event = json.loads(
            (self.project_dir / ".autobot" / "build-log.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[-1]
        )
        self.assertEqual(event["buildId"], self.BUILD_ID)

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
