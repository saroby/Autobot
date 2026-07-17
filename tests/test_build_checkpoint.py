from __future__ import annotations

import shutil
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

    def test_interrupted_restore_converges_via_journal(self):
        # A restore SIGKILLed between delete and copy leaves a franken-tree
        # plus the restore journal. The next checkpoint entry point must
        # re-apply the journaled attempt and sweep dead-pid orphan backups.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("version zero")
            state = {"appName": "DemoApp", "buildId": "build-1", "phases": {"5": {}}}
            save_checkpoint(project, load_spec(), state, attempt=0)

            root = project / ".autobot" / "build-fix" / "checkpoints"
            (root / "restore-journal.json").write_text(json.dumps({
                "attempt": 0, "buildId": "build-1", "startedAt": "t",
            }))
            shutil.rmtree(project / "DemoApp")  # crash after delete, before copy
            orphan = root / ".restore-backup.2147483647.deadbeef"
            orphan.mkdir()

            chosen = latest_checkpoint(project)

            self.assertEqual(chosen["attempt"], 0)
            self.assertEqual(source.read_text(), "version zero")
            self.assertFalse((root / "restore-journal.json").exists())
            self.assertFalse(orphan.exists(), "dead-pid orphan backup must be swept")

    def test_cross_build_journal_is_quarantined_not_replayed(self):
        # A restore journal left by build-A must NEVER replay onto build-B's
        # working tree (it would overwrite B's files with A's checkpoint). The
        # recovery path quarantines the mismatched journal and touches nothing.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            source = project / "DemoApp" / "Views" / "Home.swift"
            source.parent.mkdir(parents=True)
            source.write_text("build-B checkpoint content")
            # Active build is build-B.
            (project / ".autobot").mkdir(parents=True, exist_ok=True)
            (project / ".autobot" / "build-state.json").write_text(json.dumps({
                "appName": "DemoApp", "buildId": "build-B", "phases": {"5": {}},
            }))
            state = {"appName": "DemoApp", "buildId": "build-B", "phases": {"5": {}}}
            save_checkpoint(project, load_spec(), state, attempt=0)

            # Working tree diverges from the checkpoint.
            source.write_text("build-B newer uncommitted work")

            # A STALE journal from a DIFFERENT build survives into build-B's run.
            root = project / ".autobot" / "build-fix" / "checkpoints"
            (root / "restore-journal.json").write_text(json.dumps({
                "attempt": 0, "buildId": "build-A", "startedAt": "t",
            }))

            latest_checkpoint(project)  # any entry point triggers recovery

            self.assertFalse((root / "restore-journal.json").exists())
            quarantined = list(root.glob("restore-journal.json.quarantined.*"))
            self.assertEqual(len(quarantined), 1, "mismatched journal must be quarantined")
            # Working tree untouched — the cross-build checkpoint was NOT applied.
            self.assertEqual(source.read_text(), "build-B newer uncommitted work")

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
