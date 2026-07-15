"""Regression coverage for prose/spec contract drift checks."""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules


import_runtime_modules()
import verify_spec_docs  # noqa: E402


class TestVerifySpecDocsContracts(unittest.TestCase):

    def test_rejects_dead_owner_dispatch_reference(self):
        spec = {"phases": {"1": {"agents": ["architect"]}}}
        docs = [("orchestrator", "dispatch reads spec `phases.<id>.owner`")]

        errors = verify_spec_docs.check_prose_contract_drift(spec, docs)

        self.assertTrue(any("phases.<id>.owner" in error for error in errors))

    def test_current_docs_have_no_prose_contract_drift(self):
        spec = verify_spec_docs.load_spec()

        errors = verify_spec_docs.check_prose_contract_drift(spec)

        self.assertEqual([], errors)

    def test_generic_drift_rejects_unknown_event(self):
        spec = {"logEvents": {"learning_applied": {}}}
        docs = [("doc", "run `build-log.sh --event learning_aplied` now")]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec, docs, pipeline_subs={"run-gate"}
        )

        self.assertTrue(any("learning_aplied" in e for e in errors), errors)

    def test_generic_drift_rejects_unknown_pipeline_subcommand(self):
        spec = {"logEvents": {}}
        docs = [("doc", "then `bash pipeline.sh set-phase-stats --phase 4`")]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec, docs, pipeline_subs={"start-phase", "advance-phase"}
        )

        self.assertTrue(any("set-phase-stats" in e for e in errors), errors)

    def test_generic_drift_ignores_prose_words_after_pipeline_sh(self):
        # "pipeline.sh is ..." in plain prose must not be read as a subcommand —
        # only code spans (backticks / fenced blocks) are scanned.
        spec = {"logEvents": {}}
        docs = [("doc", "pipeline.sh is the only mutation entry point")]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec, docs, pipeline_subs={"start-phase"}
        )

        self.assertEqual([], errors)

    def test_generic_drift_rejects_missing_script_path(self):
        spec = {"logEvents": {}}
        docs = [("doc", "call `bash $CLAUDE_PLUGIN_ROOT/scripts/no-such-script.sh`")]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec, docs, pipeline_subs={"run-gate"}
        )

        self.assertTrue(any("no-such-script.sh" in e for e in errors), errors)

    def test_current_docs_have_no_generic_prose_drift(self):
        spec = verify_spec_docs.load_spec()

        errors = verify_spec_docs.check_prose_generic_drift(spec)

        self.assertEqual([], errors)

    def test_phase_count_handles_fractional_ids(self):
        # Guards the 0.7.2 fractional-phase-id fix: the row counter must include
        # "| 2.5 |". A regression to a \d+-only pattern (or a dropped 2.5 row in
        # SKILL.md) would resurface the spurious 8-vs-9 mismatch.
        spec = verify_spec_docs.load_spec()

        errors = verify_spec_docs.check_phase_count(spec)

        self.assertEqual([], errors)

    def test_release_metadata_rejects_version_drift(self):
        manifest = '{"version":"0.12.2","description":"same"}'
        pyproject = '[project]\nversion = "0.11.0"\ndescription = "same"\n'

        errors = verify_spec_docs.check_release_metadata_consistency(
            manifest, pyproject
        )

        self.assertTrue(any("project.version" in error for error in errors), errors)

    def test_release_metadata_rejects_description_drift(self):
        manifest = '{"version":"0.12.2","description":"current"}'
        pyproject = '[project]\nversion = "0.12.2"\ndescription = "stale"\n'

        errors = verify_spec_docs.check_release_metadata_consistency(
            manifest, pyproject
        )

        self.assertTrue(any("project.description" in error for error in errors), errors)

    def test_current_release_metadata_is_consistent(self):
        errors = verify_spec_docs.check_release_metadata_consistency()

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
