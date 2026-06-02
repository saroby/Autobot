"""Gate 5→6 check_first_launch_seeded — architect's seed policy enforcement.

The architect classifies each app in .autobot/architecture.json as
``seedPolicy: "seeded"`` (content/dashboard/social — a blank first launch reads
as broken) or ``"empty"`` (todo/journal — a blank start is the point). When
seeded, quality-engineer must wire the data-engineer's ``seedIfNeeded`` factory
into the app entry point. This deterministic gate greps for that call.

Policy under test:
  seedPolicy=="seeded"  + seedIfNeeded() in App/  → pass
  seedPolicy=="seeded"  + no call                 → FAIL
  seedPolicy=="empty"                             → skip (blank is correct)
  no seedPolicy field (legacy)                    → skip
  no/garbled architecture.json                    → skip (exception-safe)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import check_first_launch_seeded  # noqa: E402


class TestCheckFirstLaunchSeeded(unittest.TestCase):
    APP = "Trips"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_arch(self, policy):
        data = {"appName": self.APP}
        if policy is not None:
            data["seedPolicy"] = policy
        (self.proj / ".autobot" / "architecture.json").write_text(json.dumps(data))

    def _write_entry(self, *, seed_call: bool, filename: str = "TripsApp.swift"):
        app_dir = self.proj / self.APP / "App"
        app_dir.mkdir(parents=True, exist_ok=True)
        body = (
            "import SwiftUI\nimport SwiftData\n"
            "@main struct TripsApp: App {\n"
            "  let container: ModelContainer\n"
            "  init() {\n"
            "    container = try! ModelContainer(for: Trip.self)\n"
        )
        if seed_call:
            body += "    SampleData.seedIfNeeded(container.mainContext)\n"
        body += "  }\n  var body: some Scene { WindowGroup { ContentView() } }\n}\n"
        (app_dir / filename).write_text(body)

    def _result(self):
        return check_first_launch_seeded(self.proj, self.APP, {})[0]

    def test_seeded_with_call_passes(self):
        self._write_arch("seeded")
        self._write_entry(seed_call=True)
        r = self._result()
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_seeded_without_call_fails(self):
        self._write_arch("seeded")
        self._write_entry(seed_call=False)
        r = self._result()
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertIn("MISSING", r["message"])

    def test_empty_policy_skips(self):
        self._write_arch("empty")
        self._write_entry(seed_call=False)
        r = self._result()
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])

    def test_legacy_no_field_skips(self):
        self._write_arch(None)
        self._write_entry(seed_call=False)
        r = self._result()
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])

    def test_no_architecture_json_skips(self):
        # exception-safe: missing file must not raise
        self._write_entry(seed_call=False)
        r = self._result()
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])

    def test_garbled_architecture_json_skips(self):
        (self.proj / ".autobot" / "architecture.json").write_text("{not valid json")
        self._write_entry(seed_call=False)
        r = self._result()
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])

    def test_seed_call_in_other_app_file_passes(self):
        # The seam may live in CompositionRoot.swift, not the @main file —
        # the gate greps all of App/*.swift, so it must still pass.
        self._write_arch("seeded")
        self._write_entry(seed_call=False)  # @main has no call
        (self.proj / self.APP / "App" / "CompositionRoot.swift").write_text(
            "func wire() { SampleData.seedIfNeeded(container.mainContext) }\n"
        )
        r = self._result()
        self.assertTrue(r["passed"])

    def test_skip_is_benign_not_degraded(self):
        # The gate rollup (gate_runner.py:340-348) only lowers a gate when a skip
        # ALSO carries degraded=True. A benign skip (skipped only) counts green —
        # same contract as backend_required N/A skips. If empty/legacy skips were
        # degraded, EVERY legacy build + EVERY empty app would flip
        # VERIFIED→DEGRADED→not shippable. Lock the benign-skip invariant.
        for policy in ("empty", None):
            self._write_arch(policy)
            self._write_entry(seed_call=False)
            r = self._result()
            self.assertTrue(r.get("skipped"), f"policy={policy}")
            self.assertTrue(r["passed"], f"policy={policy}")
            self.assertFalse(r.get("degraded", False), f"policy={policy} must be benign skip")

    def test_registered_in_gate_registry(self):
        import gate_runner
        self.assertIn("first_launch_seeded", gate_runner.GATE_CHECKS)


if __name__ == "__main__":
    unittest.main()
