"""Cross-project learning propagation: builds in different directories should
inherit prior learnings via a host-wide store under XDG_CONFIG_HOME (or
~/.config). Solos → Murmur previously required manual `cp learnings.json`."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import learning_impact  # noqa: E402


def _write_learnings(path: Path, items: list[dict], patterns: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {"items": items, "patterns": patterns or {}},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")


class _XDGFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._xdg = tempfile.mkdtemp()
        os.environ["XDG_CONFIG_HOME"] = self._xdg
        self.proj = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        os.environ.pop("XDG_CONFIG_HOME", None)


class TestSeedFromGlobal(_XDGFixture):
    def test_new_project_inherits_global_when_no_local_file(self) -> None:
        global_path = Path(self._xdg) / "autobot" / "learnings.json"
        _write_learnings(global_path, [
            {"id": "cta-vis-001", "phase": "4", "effect_score": 2,
             "last_outcome": "helped", "rule_preview": "outline CTA disabled"},
        ])
        result = learning_impact.merge_global_into_project(self.proj)
        self.assertTrue(result["enriched"])
        self.assertEqual(result["mode"], "seeded_from_global")
        local = json.loads((self.proj / ".autobot" / "learnings.json").read_text())
        self.assertEqual(len(local["items"]), 1)
        self.assertEqual(local["items"][0]["id"], "cta-vis-001")

    def test_missing_global_is_silent_noop(self) -> None:
        result = learning_impact.merge_global_into_project(self.proj)
        self.assertFalse(result["enriched"])
        self.assertFalse((self.proj / ".autobot" / "learnings.json").exists())


class TestMergeIntoExisting(_XDGFixture):
    def test_project_wins_on_id_collision(self) -> None:
        global_path = Path(self._xdg) / "autobot" / "learnings.json"
        _write_learnings(global_path, [
            {"id": "x", "effect_score": 1, "rule_preview": "from global"},
            {"id": "y", "effect_score": 1, "rule_preview": "only global"},
        ])
        local_path = self.proj / ".autobot" / "learnings.json"
        _write_learnings(local_path, [
            {"id": "x", "effect_score": 5, "rule_preview": "from project"},
            {"id": "z", "effect_score": 1, "rule_preview": "only project"},
        ])

        result = learning_impact.merge_global_into_project(self.proj)
        self.assertEqual(result["mode"], "merged_with_existing")
        merged = json.loads(local_path.read_text())
        by_id = {it["id"]: it for it in merged["items"]}
        self.assertEqual(by_id["x"]["rule_preview"], "from project")  # project wins
        self.assertIn("y", by_id)  # global-only kept
        self.assertIn("z", by_id)  # project-only kept


class TestPublishToGlobal(_XDGFixture):
    def test_project_items_overlay_global_on_publish(self) -> None:
        global_path = Path(self._xdg) / "autobot" / "learnings.json"
        _write_learnings(global_path, [
            {"id": "a", "effect_score": 0, "rule_preview": "older"},
        ])
        local_path = self.proj / ".autobot" / "learnings.json"
        _write_learnings(local_path, [
            {"id": "a", "effect_score": 3, "rule_preview": "newer (graded helpful)"},
            {"id": "b", "effect_score": 1, "rule_preview": "brand new"},
        ])
        result = learning_impact.publish_project_to_global(self.proj)
        self.assertTrue(result["published"])
        published = json.loads(global_path.read_text())
        by_id = {it["id"]: it for it in published["items"]}
        self.assertEqual(by_id["a"]["effect_score"], 3)  # newer grade wins
        self.assertIn("b", by_id)

    def test_patterns_frequency_accumulates_across_publishes(self) -> None:
        global_path = Path(self._xdg) / "autobot" / "learnings.json"
        _write_learnings(global_path, [], patterns={
            "common_build_errors": {"foo": {"frequency": 2, "fix_summary": "old"}},
        })
        local_path = self.proj / ".autobot" / "learnings.json"
        _write_learnings(local_path, [], patterns={
            "common_build_errors": {"foo": {"frequency": 3, "fix_summary": "updated"}},
        })
        learning_impact.publish_project_to_global(self.proj)
        published = json.loads(global_path.read_text())
        foo = published["patterns"]["common_build_errors"]["foo"]
        self.assertEqual(foo["frequency"], 5)  # 2 + 3
        self.assertEqual(foo["fix_summary"], "updated")  # latest narrative wins


if __name__ == "__main__":
    unittest.main()
