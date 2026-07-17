"""Gate 1->2 planning-depth heading checks (setup.py) — all DEGRADED-only.

market_context_present / hook_retention_present (+ conditional First-Run) /
service_protocol_depth grep for the wave-1 architecture sections. They must
NEVER hard-fail: heading presence is a quality signal, and a hard fail would
consume circuit-breaker retries on an unattended build.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.setup import (  # noqa: E402
    check_hook_retention_present,
    check_market_context_present,
    check_service_protocol_depth,
)


def _degraded(r: dict) -> bool:
    return bool(r.get("skipped")) and bool(r.get("degraded"))


class _GateCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _arch_md(self, text: str) -> None:
        (self.proj / ".autobot" / "architecture.md").write_text(text, encoding="utf-8")

    def _arch_json(self, payload: dict) -> None:
        (self.proj / ".autobot" / "architecture.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


_MARKET_TABLE = (
    "## Overview\nx\n\n## Market Context\n"
    "| # | App | Notable |\n|---|---|---|\n"
    "| 1 | Streaks | heatmap |\n| 2 | HabitKit | grid |\n| 3 | Done | streak |\n"
)


class TestMarketContextPresent(_GateCase):
    def test_heading_with_three_rows_passes(self):
        self._arch_md(_MARKET_TABLE)
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertTrue(r["passed"], r["message"])

    def test_missing_heading_is_degraded_never_hard(self):
        self._arch_md("## Overview\nno market research here\n")
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_too_few_rows_is_degraded_unless_no_competitors(self):
        self._arch_md("## Market Context\n| # | App |\n|---|---|\n| 1 | Only |\n")
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)
        # market-brief noDirectCompetitors=true legitimizes the short table
        (self.proj / ".autobot" / "market-brief.json").write_text(
            json.dumps({"noDirectCompetitors": True}), encoding="utf-8"
        )
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertTrue(r["passed"], r["message"])

    def test_missing_architecture_md_is_degraded(self):
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_string_false_no_competitors_not_honored(self):
        # "false" (a JSON string) is truthy in Python — it must NOT waive the
        # short-table row; only the boolean true does.
        self._arch_md("## Market Context\n| # | App |\n|---|---|\n| 1 | Only |\n")
        (self.proj / ".autobot" / "market-brief.json").write_text(
            json.dumps({"noDirectCompetitors": "false"}), encoding="utf-8"
        )
        r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_unreadable_architecture_md_degrades_not_crash(self):
        # A read error must not kill the gate process — degrade instead.
        self._arch_md(_MARKET_TABLE)
        with mock.patch.object(Path, "read_text", side_effect=OSError("perm denied")):
            r = check_market_context_present(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)


class TestHookRetentionPresent(_GateCase):
    def _rows(self):
        return {r["check"]: r for r in check_hook_retention_present(self.proj, "Demo", {})}

    def test_heading_present_passes(self):
        self._arch_md("## Features\n\n### Hook & Retention\n| 훅 | ... |\n")
        rows = self._rows()
        self.assertTrue(rows["hook_retention_present"]["passed"])

    def test_missing_heading_is_degraded(self):
        self._arch_md("## Features\nnothing else\n")
        rows = self._rows()
        r = rows["hook_retention_present"]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_first_run_not_required_for_direct_policy(self):
        self._arch_md("### Hook & Retention\n")
        self._arch_json({"firstRunPolicy": "direct"})
        r = self._rows()["first_run_experience_present"]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))

    def test_primer_policy_requires_first_run_section(self):
        self._arch_md("### Hook & Retention\n")
        self._arch_json({"firstRunPolicy": "primer"})
        r = self._rows()["first_run_experience_present"]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)
        self._arch_md("### Hook & Retention\n\n## First-Run Experience\npriming\n")
        r = self._rows()["first_run_experience_present"]
        self.assertTrue(r["passed"], r["message"])


class TestServiceProtocolDepth(_GateCase):
    def _write_protocols(self, text: str) -> None:
        models = self.proj / "Demo" / "Models"
        models.mkdir(parents=True, exist_ok=True)
        (models / "ServiceProtocols.swift").write_text(text, encoding="utf-8")

    def test_non_crud_method_passes(self):
        self._write_protocols(
            "protocol HabitServiceProtocol {\n"
            "  func fetchAll() -> [Habit]\n"
            "  func weeklySummary() -> WeekSummary\n}\n"
        )
        r = check_service_protocol_depth(self.proj, "Demo", {})[0]
        self.assertTrue(r["passed"], r["message"])
        self.assertIn("weeklySummary", r["message"])

    def test_crud_only_protocol_is_degraded_never_hard(self):
        self._write_protocols(
            "protocol HabitServiceProtocol {\n"
            "  func fetchAll() -> [Habit]\n  func add(_ h: Habit)\n"
            "  func delete(_ h: Habit)\n  func update(_ h: Habit)\n}\n"
        )
        r = check_service_protocol_depth(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_absent_file_benign_skips(self):
        r = check_service_protocol_depth(self.proj, "Demo", {})[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_commented_out_derived_method_not_counted(self):
        # `// func weeklySummary()` is a comment, not a real derived method — a
        # CRUD-only protocol with a commented insight method must still degrade.
        self._write_protocols(
            "protocol HabitServiceProtocol {\n"
            "  func fetchAll() -> [Habit]\n"
            "  // func weeklySummary() -> WeekSummary\n}\n"
        )
        r = check_service_protocol_depth(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)

    def test_unreadable_protocols_degrades_not_crash(self):
        self._write_protocols("protocol P {\n  func weeklySummary() -> X\n}\n")
        with mock.patch.object(Path, "read_text", side_effect=OSError("boom")):
            r = check_service_protocol_depth(self.proj, "Demo", {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(_degraded(r), r)


if __name__ == "__main__":
    unittest.main()
