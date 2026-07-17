"""Gate 3→4 design-system 체크 회귀 테스트."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import SCRIPTS_DIR, import_runtime_modules

import_runtime_modules()

from gate_runner import (  # noqa: E402  (after sys.path injection)
    check_design_system_components_exist,
    check_design_system_package_exists,
    check_design_system_tokens_exist,
    check_ds_primitives_used,
    check_no_legacy_theme_refs,
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
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

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

    def test_malformed_arch_json_fails(self) -> None:
        (self.tmp / ".autobot").mkdir(parents=True, exist_ok=True)
        (self.tmp / ".autobot" / "architecture.json").write_text("{INVALID", encoding="utf-8")
        result = check_design_system_package_exists(self.tmp, "Instagram", {})
        self.assertEqual(result[0]["passed"], False)
        self.assertIn("designSystemModule", result[0]["message"])


class TestDesignSystemTokensExist(unittest.TestCase):
    REQUIRED = ["Color.swift", "Typography.swift", "Spacing.swift", "Radius.swift"]

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        _write_arch_json(self.tmp)
        self.tokens = self.tmp / "Packages" / "InstagramDS" / "Sources" / "InstagramDS" / "Tokens"
        self.tokens.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

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


COMPONENTS = ["PrimaryButton", "Card", "SectionHeader", "EmptyStateView", "ListRow"]


class TestDesignSystemComponentsExist(unittest.TestCase):
    """5종 컴포넌트 이름 계약 — prose 였던 것을 Gate 3→4 hard check 로 고정."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        _write_arch_json(self.tmp)
        self.comps = self.tmp / "Packages" / "InstagramDS" / "Sources" / "InstagramDS" / "Components"
        self.comps.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_all(self) -> None:
        for name in COMPONENTS:
            generic = "<Content: View>" if name == "Card" else ""
            (self.comps / f"{name}.swift").write_text(
                f"import SwiftUI\npublic struct InstagramDS{name}{generic}: View {{}}\n",
                encoding="utf-8",
            )

    def test_all_components_with_module_prefixed_structs_pass(self) -> None:
        self._write_all()
        result = check_design_system_components_exist(self.tmp, "Instagram", _make_state())
        self.assertTrue(result[0]["passed"], result[0]["message"])

    def test_missing_component_fails(self) -> None:
        self._write_all()
        (self.comps / "ListRow.swift").unlink()
        result = check_design_system_components_exist(self.tmp, "Instagram", _make_state())
        self.assertFalse(result[0]["passed"])
        self.assertIn("ListRow.swift missing", result[0]["message"])

    def test_renamed_struct_fails(self) -> None:
        # ListRow → WorkoutRow 같은 앱별 개명이 Phase 5 빌드 파손의 실제 사례.
        self._write_all()
        (self.comps / "ListRow.swift").write_text(
            "import SwiftUI\npublic struct InstagramDSWorkoutRow: View {}\n",
            encoding="utf-8",
        )
        result = check_design_system_components_exist(self.tmp, "Instagram", _make_state())
        self.assertFalse(result[0]["passed"])
        self.assertIn("InstagramDSListRow", result[0]["message"])

    def test_empty_component_fails(self) -> None:
        self._write_all()
        (self.comps / "Card.swift").write_text("", encoding="utf-8")
        result = check_design_system_components_exist(self.tmp, "Instagram", _make_state())
        self.assertFalse(result[0]["passed"])
        self.assertIn("Card.swift empty", result[0]["message"])

    def test_unresolved_module_fails(self) -> None:
        (self.tmp / ".autobot" / "architecture.json").unlink()
        result = check_design_system_components_exist(self.tmp, "Instagram", {})
        self.assertFalse(result[0]["passed"])
        self.assertIn("designSystemModule", result[0]["message"])

    def test_declaration_only_in_comment_fails(self) -> None:
        # A `// public struct InstagramDSListRow` mention must not satisfy the
        # HARD contract — only a real declaration counts.
        self._write_all()
        (self.comps / "ListRow.swift").write_text(
            "import SwiftUI\n// public struct InstagramDSListRow: View {}\n"
            "struct SomethingElse {}\n",
            encoding="utf-8",
        )
        result = check_design_system_components_exist(self.tmp, "Instagram", _make_state())
        self.assertFalse(result[0]["passed"])
        self.assertIn("InstagramDSListRow", result[0]["message"])


class TestDsPrimitivesUsed(unittest.TestCase):
    """Gate 4→5 — Views/ 가 DS primitive 를 실제로 쓰는지. DEGRADED-only."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        _write_arch_json(self.tmp)
        self.views = self.tmp / "Instagram" / "Views"
        self.views.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_import_plus_primitive_usage_passes(self) -> None:
        (self.views / "Home.swift").write_text(
            "import InstagramDS\nInstagramDSPrimaryButton(title: \"Go\")\n",
            encoding="utf-8",
        )
        r = check_ds_primitives_used(self.tmp, "Instagram", _make_state())[0]
        self.assertTrue(r["passed"], r["message"])
        self.assertFalse(r.get("degraded", False))

    def test_reimplemented_primitives_degrade_not_hard_fail(self) -> None:
        # DS 레이어를 죽은 코드로 만든 실사례(CHANGELOG) — 신호는 DEGRADED 로만.
        (self.views / "Home.swift").write_text(
            "import SwiftUI\nButton(\"Go\") {}\n", encoding="utf-8",
        )
        r = check_ds_primitives_used(self.tmp, "Instagram", _make_state())[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))     # DEGRADED shape — never a hard fail
        self.assertTrue(r.get("degraded"))

    def test_no_views_dir_is_benign_skip(self) -> None:
        import shutil
        shutil.rmtree(self.views)
        r = check_ds_primitives_used(self.tmp, "Instagram", _make_state())[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_legacy_build_without_module_is_benign_skip(self) -> None:
        (self.tmp / ".autobot" / "architecture.json").unlink()
        r = check_ds_primitives_used(self.tmp, "Instagram", {})[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))


class TestNoLegacyThemeRefs(unittest.TestCase):
    """Gate 4→5 — 삭제된 Theme.* / 시스템 .accentColor 우회 grep. DEGRADED-only."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.views = self.tmp / "Instagram" / "Views"
        self.views.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> dict:
        return check_no_legacy_theme_refs(self.tmp, "Instagram", {})[0]

    def test_ds_tokens_pass(self) -> None:
        (self.views / "Home.swift").write_text(
            "Text(\"hi\").foregroundStyle(InstagramDSColor.primary)\n"
            ".tint(InstagramDSColor.accent)\n",
            encoding="utf-8",
        )
        r = self._run()
        self.assertTrue(r["passed"], r["message"])

    def test_accent_color_degrades_not_hard_fail(self) -> None:
        (self.views / "Home.swift").write_text(
            "Button(\"Go\") {}.tint(.accentColor)\n", encoding="utf-8",
        )
        r = self._run()
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))

    def test_theme_reference_degrades(self) -> None:
        (self.views / "Home.swift").write_text(
            "Text(\"hi\").foregroundStyle(Theme.primary)\n", encoding="utf-8",
        )
        r = self._run()
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))

    def test_module_prefixed_theme_like_name_not_flagged(self) -> None:
        # `\bTheme\.` 는 식별자 내부(InstagramTheme.x)에 매치되면 안 된다.
        (self.views / "Home.swift").write_text(
            "Text(\"hi\").foregroundStyle(InstagramTheme.primary)\n", encoding="utf-8",
        )
        r = self._run()
        self.assertTrue(r["passed"], r["message"])

    def test_comment_lines_ignored(self) -> None:
        (self.views / "Home.swift").write_text(
            "// never use Color.accentColor or Theme.primary\nText(\"hi\")\n",
            encoding="utf-8",
        )
        r = self._run()
        self.assertTrue(r["passed"])

    def test_no_views_dir_is_benign_skip(self) -> None:
        import shutil
        shutil.rmtree(self.views)
        r = self._run()
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))


if __name__ == "__main__":
    unittest.main()
