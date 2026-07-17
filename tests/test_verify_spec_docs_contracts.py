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

    def test_generic_drift_rejects_typo_env_var(self):
        spec = {"logEvents": {}}
        docs = [("doc", "set `AUTOBOT_INVITE_STATU_FILE` before calling invite.sh")]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec,
            docs,
            pipeline_subs={"run-gate"},
            known_autobot_vars={"AUTOBOT_INVITE_STATUS_FILE"},
        )

        self.assertTrue(any("AUTOBOT_INVITE_STATU_FILE" in e for e in errors), errors)

    def test_generic_drift_allows_doc_local_knob_with_default(self):
        # A var declared inline with a shell default (`${AUTOBOT_X:-default}`)
        # is self-contained documentation, not a reference to a script-known
        # name — e.g. skills/autobot-app-review/SKILL.md's AUTOBOT_HOMEPAGE_REPO.
        spec = {"logEvents": {}}
        docs = [("doc", 'REPO="${AUTOBOT_HOMEPAGE_REPO:-$HOME/Code/repo}"')]

        errors = verify_spec_docs.check_prose_generic_drift(
            spec, docs, pipeline_subs={"run-gate"}, known_autobot_vars={"AUTOBOT_OTHER"}
        )

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

    def test_gate_structure_rejects_empty_checks(self):
        errors = verify_spec_docs.check_gate_structure({"gates": {
            "1->2": {"checks": [{"type": "procedural", "name": "x"}]},  # ok
            "2->3": {"checks": []},                                     # empty
            "3->4": {},                                                 # missing
        }})
        joined = " ".join(errors)
        self.assertIn("2->3", joined)
        self.assertIn("3->4", joined)
        self.assertNotIn("1->2", joined)

    def test_current_gates_all_have_checks(self):
        from spec_loader import load_spec
        self.assertEqual([], verify_spec_docs.check_gate_structure(load_spec()))

    def test_deterministic_drift_checks_fail_the_run(self):
        # Retry drift, phase-count drift, and empty-gate structure are
        # deterministic mismatches — main() must exit non-zero (ERROR), not pass
        # with a warning. Inject a fake finding into each and assert rc == 1.
        for attr in ("check_retry_drift", "check_phase_count", "check_gate_structure"):
            with self.subTest(check=attr):
                original = getattr(verify_spec_docs, attr)
                setattr(verify_spec_docs, attr, lambda spec, _m=f"FAKE {attr} drift": [_m])
                try:
                    rc = verify_spec_docs.main()
                finally:
                    setattr(verify_spec_docs, attr, original)
                self.assertEqual(rc, 1)

    def test_phase_learning_mapping_rejects_zero_mappings(self):
        # A canonical doc that extracts no mappings (prose removed / format
        # drifted) is an error, not a silent pass.
        errors = verify_spec_docs.check_phase_learning_mapping(
            "",  # resume.md lost its mapping prose
            "- Phase 별 파일 매핑: 1→`architecture.md`",
            "| 1 | architect | `phase-learnings/architecture.md` |",
            known_filenames={"architecture.md"},
        )
        self.assertTrue(any("0 Phase" in e and "resume.md" in e for e in errors), errors)

    def test_phase_learning_mapping_rejects_cross_doc_disagreement(self):
        resume = "- Phase 1 → `.autobot/phase-learnings/architecture.md`"
        skill = "- Phase 별 파일 매핑: 1→`architecture_v2.md`"
        bootstrap = "| 1 | architect | `phase-learnings/architecture.md` |"

        errors = verify_spec_docs.check_phase_learning_mapping(
            resume, skill, bootstrap, known_filenames={"architecture.md", "architecture_v2.md"}
        )

        self.assertTrue(any("Phase 1 disagrees" in e for e in errors), errors)

    def test_phase_learning_mapping_rejects_unknown_alias(self):
        resume = "- Phase 1 → `.autobot/phase-learnings/architecture.md`"
        skill = "- Phase 별 파일 매핑: 1→`architecture.md`"
        bootstrap = "| 1 | architect | `phase-learnings/architecture.md` |"

        errors = verify_spec_docs.check_phase_learning_mapping(
            resume, skill, bootstrap, known_filenames={"some_other.md"}
        )

        self.assertTrue(any("not in render-active-learnings.py" in e for e in errors), errors)

    def test_current_phase_learning_mapping_is_consistent(self):
        errors = verify_spec_docs.check_phase_learning_mapping()

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
