"""Gate 3→4 design-system 체크 회귀 테스트."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from conftest import SCRIPTS_DIR, import_runtime_modules

import_runtime_modules()

from gate_runner import (  # noqa: E402  (after sys.path injection)
    check_design_system_package_exists,
    check_design_system_tokens_exist,
)


def _make_state(module: str = "InstagramDS") -> dict:
    return {"architecture": {"designSystemModule": module}}


def _write_arch_json(proj: Path, module: str = "InstagramDS") -> None:
    (proj / ".autobot").mkdir(parents=True, exist_ok=True)
    (proj / ".autobot" / "architecture.json").write_text(
        json.dumps({"appName": "Instagram", "designSystemModule": module}),
        encoding="utf-8",
    )


class TestDesignSystemPackageExists(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_package_swift_fails(self) -> None:
        _write_arch_json(self.tmp)
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("Package.swift", result[0]["message"])

    def test_present_package_swift_with_matching_name_passes(self) -> None:
        _write_arch_json(self.tmp)
        pkg = self.tmp / "Packages" / "InstagramDS"
        pkg.mkdir(parents=True)
        (pkg / "Package.swift").write_text(
            'let package = Package(name: "InstagramDS", targets: [])',
            encoding="utf-8",
        )
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], True)

    def test_present_but_name_mismatch_fails(self) -> None:
        _write_arch_json(self.tmp)
        pkg = self.tmp / "Packages" / "InstagramDS"
        pkg.mkdir(parents=True)
        (pkg / "Package.swift").write_text(
            'let package = Package(name: "WrongName", targets: [])',
            encoding="utf-8",
        )
        result = check_design_system_package_exists(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("name", result[0]["message"].lower())

    def test_missing_arch_json_fails_with_clear_message(self) -> None:
        # architecture.json 이 없으면 designSystemModule 을 알 수 없음 — fail
        result = check_design_system_package_exists(self.tmp, "Instagram", {})
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("designSystemModule", result[0]["message"])


class TestDesignSystemTokensExist(unittest.TestCase):
    REQUIRED = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        _write_arch_json(self.tmp)
        self.tokens = self.tmp / "Packages" / "InstagramDS" / "Sources" / "InstagramDS" / "Tokens"
        self.tokens.mkdir(parents=True)

    def test_all_tokens_present_and_non_empty_passes(self) -> None:
        for name in self.REQUIRED:
            (self.tokens / name).write_text("import SwiftUI\nenum X {}\n", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], True)

    def test_missing_one_token_fails(self) -> None:
        for name in self.REQUIRED[:-1]:
            (self.tokens / name).write_text("import SwiftUI\n", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("Radius.swift", result[0]["message"])

    def test_empty_token_file_fails(self) -> None:
        for name in self.REQUIRED:
            (self.tokens / name).write_text("", encoding="utf-8")
        result = check_design_system_tokens_exist(self.tmp, "Instagram", _make_state())
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("empty", result[0]["message"].lower())


if __name__ == "__main__":
    unittest.main()
