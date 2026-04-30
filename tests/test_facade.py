"""runtime.py facade contract: every documented re-export is the same object
as the source-module symbol. Future renames in either side are caught here.
"""

from __future__ import annotations

import importlib
import unittest

from conftest import import_runtime_modules


class TestFacade(unittest.TestCase):

    def setUp(self) -> None:
        import_runtime_modules()

    def test_facade_exports_match_source_modules(self):
        runtime = importlib.import_module("runtime")

        # Each (name, module) tuple must satisfy: facade re-export === module symbol.
        expected = [
            ("load_spec", "spec_loader"),
            ("validate_spec", "spec_loader"),
            ("phase_ids", "spec_loader"),
            ("schema_keys", "spec_loader"),
            ("load_state", "state_store"),
            ("save_state", "state_store"),
            ("mutate_state_with_validation", "state_store"),
            ("collect_schema_issues", "state_store"),
            ("default_phases", "state_store"),
            ("utc_now", "state_store"),
            ("validate_log_event", "event_log"),
            ("append_build_log", "event_log"),
            ("validate_transition_request", "transitions"),
            ("update_phase_status", "transitions"),
            ("circuit_breaker_tripped", "transitions"),
            ("execute_and_record_gate", "gate_persistence"),
            ("phase_id_for_alwaysrun", "gate_persistence"),
            ("force_phase_in_progress", "gate_persistence"),
        ]

        for name, source_mod_name in expected:
            with self.subTest(name=name, source=source_mod_name):
                self.assertTrue(hasattr(runtime, name), f"runtime.{name} missing")
                source = importlib.import_module(source_mod_name)
                self.assertIs(getattr(runtime, name), getattr(source, name))


if __name__ == "__main__":
    unittest.main()
