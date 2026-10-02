"""Routed prompt resources must remain deployable and inspectable."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR, import_runtime_modules

import_runtime_modules()
from prompt_resources import documents, read_bundle  # noqa: E402


class PromptResourceTests(unittest.TestCase):
    def test_nested_links_and_cycles_are_resolved_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir()
            entry = root / "SKILL.md"
            detail = root / "references" / "detail.md"
            entry.write_text("[detail](references/detail.md#one)\n[again](references/detail.md)")
            detail.write_text("contract\n[entry](../SKILL.md)\n[remote](https://example.com/doc.md)")
            self.assertEqual([entry.resolve(), detail.resolve()], documents(entry))
            self.assertEqual(1, read_bundle(entry).count("contract"))

    def test_missing_local_reference_is_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / "SKILL.md"
            entry.write_text("[required](references/missing.md)")
            with self.assertRaises(FileNotFoundError):
                documents(entry)

    def test_all_routed_plugin_resources_exist(self):
        for entry in sorted(PLUGIN_DIR.glob("skills/*/SKILL.md")) + sorted(PLUGIN_DIR.glob("agents/*.md")):
            with self.subTest(entry=entry.relative_to(PLUGIN_DIR)):
                self.assertTrue(documents(entry))
