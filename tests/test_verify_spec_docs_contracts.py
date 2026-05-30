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

    def test_phase_count_handles_fractional_ids(self):
        # Guards the 0.7.2 fractional-phase-id fix: the row counter must include
        # "| 2.5 |". A regression to a \d+-only pattern (or a dropped 2.5 row in
        # SKILL.md) would resurface the spurious 8-vs-9 mismatch.
        spec = verify_spec_docs.load_spec()

        errors = verify_spec_docs.check_phase_count(spec)

        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
