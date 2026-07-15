from __future__ import annotations

import tempfile
import unittest
import copy
import json
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from build_checkpoint import (  # noqa: E402
    latest_checkpoint,
    restore_checkpoint,
    save_checkpoint,
)
from spec_loader import load_spec  # noqa: E402


class TestBuildCheckpoint(unittest.TestCase):
    def test_save_and_restore_exact_phase_five_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("version zero")
            (project / "project.yml").write_text("name: Demo")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {"inputHash": "h0"}}}

            saved = save_checkpoint(project, load_spec(), state, attempt=0)
            self.assertEqual(saved["attempt"], 0)
            source.write_text("broken edit")
            added_after_save = source.parent / "NewBroken.swift"
            added_after_save.write_text("must disappear")

            restored = restore_checkpoint(project, load_spec(), state, attempt=0)
            self.assertEqual(restored["attempt"], 0)
            self.assertEqual(source.read_text(), "version zero")
            self.assertFalse(added_after_save.exists())

    def test_latest_can_exclude_repeated_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "App" / "DemoApp.swift"
            source.parent.mkdir(parents=True)
            source.write_text("attempt zero")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {"inputHash": "h0"}}}
            spec = load_spec()
            save_checkpoint(project, spec, state, attempt=0)
            source.write_text("attempt one")
            save_checkpoint(project, spec, state, attempt=1, error_signature="same")

            chosen = latest_checkpoint(project, exclude_signature="same")
            self.assertEqual(chosen["attempt"], 0)

    def test_save_after_attempt_honors_policy_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "DemoApp").mkdir()
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {}}}
            spec = copy.deepcopy(load_spec())
            spec["policies"]["buildFixLoop"]["checkpoint"]["saveAfterEachAttempt"] = False
            with self.assertRaises(ValueError):
                save_checkpoint(project, spec, state, attempt=1)

    def test_restore_rejects_tampered_checkpoint_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("original")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {}}}
            save_checkpoint(project, load_spec(), state, attempt=0)
            checkpoint_file = (
                project / ".autobot" / "build-fix" / "checkpoints" /
                "attempt-0" / "DemoApp" / "Views" / "Home.swift"
            )
            checkpoint_file.write_text("tampered")

            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                restore_checkpoint(project, load_spec(), state, attempt=0)
            self.assertEqual(source.read_text(), "original")

    def test_restore_rejects_tampered_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("original")
            outside = root / "must-not-delete"
            outside.write_text("safe")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {}}}
            save_checkpoint(project, load_spec(), state, attempt=0)
            metadata_path = (
                project / ".autobot" / "build-fix" / "checkpoints" /
                "attempt-0" / "checkpoint.json"
            )
            metadata = json.loads(metadata_path.read_text())
            metadata["targets"] = ["../must-not-delete"]
            metadata_path.write_text(json.dumps(metadata))

            with self.assertRaisesRegex(ValueError, "metadata hash mismatch"):
                restore_checkpoint(project, load_spec(), state, attempt=0)
            self.assertEqual(outside.read_text(), "safe")

    def test_latest_rejects_tampered_attempt_and_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("original")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {}}}
            save_checkpoint(
                project, load_spec(), state, attempt=0, error_signature="original"
            )
            metadata_path = (
                project / ".autobot" / "build-fix" / "checkpoints" /
                "attempt-0" / "checkpoint.json"
            )
            metadata = json.loads(metadata_path.read_text())
            metadata["attempt"] = 99
            metadata["errorSignature"] = "forged"
            metadata_path.write_text(json.dumps(metadata))

            with self.assertRaises(FileNotFoundError):
                latest_checkpoint(project)


if __name__ == "__main__":
    unittest.main()
