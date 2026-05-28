"""Gate 2→3 / 3→4 — app-icon presence checks.

Past incident (2026-05, BookMemo): the orchestrator silently skipped the
``autobot-app-icon`` skill at the end of Phase 2 and the Phase 3 scaffold
created an empty ``AppIcon.appiconset``. The build still compiled — xcodebuild
does not fail on a faceless app — so the user only noticed once the home
screen showed a blank tile. These two gates make the contract explicit.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import (  # noqa: E402  (after sys.path injection)
    check_app_icon_applied,
    check_app_icon_source_present,
)


class TestAppIconSourcePresent(unittest.TestCase):
    """Gate 2→3 — ``.autobot/app-icon-1024.png`` must exist."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_icon_source_fails(self) -> None:
        result = check_app_icon_source_present(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("autobot-app-icon", result[0]["message"])

    def test_zero_byte_icon_source_fails(self) -> None:
        (self.tmp / ".autobot" / "app-icon-1024.png").write_bytes(b"")
        result = check_app_icon_source_present(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], False)

    def test_present_icon_source_passes(self) -> None:
        (self.tmp / ".autobot" / "app-icon-1024.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        result = check_app_icon_source_present(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], True)
        self.assertIn("app-icon-1024.png", result[0]["message"])


class TestAppIconApplied(unittest.TestCase):
    """Gate 3→4 — ``Assets.xcassets/AppIcon.appiconset/`` must hold ≥1 PNG."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.iconset = self.tmp / "BookMemo" / "Assets.xcassets" / "AppIcon.appiconset"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_iconset_dir_fails(self) -> None:
        result = check_app_icon_applied(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], False)

    def test_iconset_with_only_contents_json_fails(self) -> None:
        self.iconset.mkdir(parents=True)
        (self.iconset / "Contents.json").write_text("{}", encoding="utf-8")
        result = check_app_icon_applied(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("0 PNGs", result[0]["message"])

    def test_iconset_with_png_passes(self) -> None:
        self.iconset.mkdir(parents=True)
        (self.iconset / "AppIcon-1024.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        result = check_app_icon_applied(self.tmp, "BookMemo", {})
        self.assertEqual(result[0]["passed"], True)
        self.assertIn("1 icon PNG", result[0]["message"])


class TestDirHasSwiftRecursive(unittest.TestCase):
    """``_dir_has_swift`` recursive mode must follow ``Views/Components/`` etc.

    Past incident: ui-builder organized files into ``Views/Components/`` and
    ``Views/Screens/`` and the Phase 4 ``views_exist`` gate counted 0 .swift
    files because the original check was non-recursive.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.views = self.tmp / "Views"
        (self.views / "Components").mkdir(parents=True)
        (self.views / "Screens").mkdir(parents=True)
        (self.views / "Components" / "BookCardView.swift").write_text("// stub")
        (self.views / "Screens" / "LibraryView.swift").write_text("// stub")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_non_recursive_misses_nested_files(self) -> None:
        from gate_runner import _dir_has_swift
        result = _dir_has_swift(self.views, "views_files", recursive=False)
        self.assertEqual(result["passed"], False)
        self.assertIn("0 .swift", result["message"])

    def test_recursive_counts_nested_files(self) -> None:
        from gate_runner import _dir_has_swift
        result = _dir_has_swift(self.views, "views_files", recursive=True)
        self.assertEqual(result["passed"], True)
        self.assertIn("2 .swift", result["message"])


if __name__ == "__main__":
    unittest.main()
