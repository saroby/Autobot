"""WS5 shipping-gate mechanization checks.

Covers the runtime enforcement added for previously prose-only policies:
  - no_swallowed_errors    — try?/try! in ViewModels/Services (DEGRADED-only)
  - no_hardcoded_font_sizes — .font(.system(size:)) in Views/ (DEGRADED-only)
  - runtime_smoke skips     — degraded unless the explicit CI opt-out env is set
  - app_uses_real_repositories — App/*.swift scope + comment exclusion
  - visual_contract darkMode sub-check mapping (DEGRADED-only)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import sim_runtime  # noqa: E402
import visual_contract  # noqa: E402
from gate_checks.app import check_no_hardcoded_font_sizes  # noqa: E402
from gate_checks.build import (  # noqa: E402
    check_app_uses_real_repositories,
    check_no_swallowed_errors,
    check_runtime_smoke,
    check_visual_contract,
)

APP = "Demo"


class _TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, content: str) -> None:
        path = self.proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class TestNoSwallowedErrors(_TempProject):
    def test_clean_code_passes(self):
        self.write(f"{APP}/ViewModels/ItemVM.swift",
                   "func load() { do { items = try service.fetchAll() } catch { errorMessage = error.localizedDescription } }\n")
        r = check_no_swallowed_errors(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))

    def test_try_optional_is_degraded_not_hard_fail(self):
        self.write(f"{APP}/ViewModels/ItemVM.swift",
                   "func load() { items = (try? service.fetchAll()) ?? [] }\n")
        r = check_no_swallowed_errors(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))    # DEGRADED shape, not a hard fail
        self.assertTrue(r.get("degraded"))
        self.assertIn("try?", r["message"])

    def test_try_bang_in_services_is_degraded(self):
        self.write(f"{APP}/Services/Store.swift",
                   "let container = try! ModelContainer(for: Item.self)\n")
        r = check_no_swallowed_errors(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("degraded"))

    def test_comment_lines_ignored(self):
        self.write(f"{APP}/Services/Store.swift",
                   "// never use try? here\nfunc ok() throws {}\n")
        r = check_no_swallowed_errors(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])

    def test_missing_dirs_pass(self):
        r = check_no_swallowed_errors(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])


class TestNoHardcodedFontSizes(_TempProject):
    def test_no_views_dir_is_benign_skip(self):
        r = check_no_hardcoded_font_sizes(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))

    def test_semantic_fonts_pass(self):
        self.write(f"{APP}/Views/Home.swift",
                   'Text("hi").font(.headline)\nText("x").font(DemoFont.title())\n')
        r = check_no_hardcoded_font_sizes(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])

    def test_hardcoded_size_is_degraded_not_hard_fail(self):
        self.write(f"{APP}/Views/Home.swift",
                   'Text("hi").font(.system(size: 17))\n')
        r = check_no_hardcoded_font_sizes(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))    # DEGRADED-only — never a hard fail
        self.assertTrue(r.get("degraded"))
        self.assertIn("Dynamic Type", r["message"])

    def test_justified_line_is_allowed(self):
        self.write(f"{APP}/Views/Logo.swift",
                   'Text("BRAND").font(.system(size: 42)) // fixed brand wordmark, not body text\n')
        r = check_no_hardcoded_font_sizes(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])

    def test_comment_only_line_ignored(self):
        self.write(f"{APP}/Views/Home.swift",
                   '// .font(.system(size: 17)) is forbidden\nText("hi").font(.body)\n')
        r = check_no_hardcoded_font_sizes(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])


class TestRuntimeSmokeSkipGrades(_TempProject):
    """A build whose app was never launched must not roll up green — the only
    benign skip is the explicit AUTOBOT_DISABLE_SIMULATOR CI opt-out."""

    def _run_with_skip(self, reason: str, *, env_optout: bool) -> dict:
        with mock.patch.dict(os.environ):
            if env_optout:
                os.environ["AUTOBOT_DISABLE_SIMULATOR"] = "1"
            else:
                os.environ.pop("AUTOBOT_DISABLE_SIMULATOR", None)
            with mock.patch.object(
                sim_runtime, "smoke",
                return_value={"status": "skipped", "skipReason": reason},
            ):
                return check_runtime_smoke(self.proj, APP, {})[0]

    def test_resource_skip_is_degraded(self):
        for reason in ("app_artifact_missing", "no_ios_simulator_available", "simctl_unavailable"):
            r = self._run_with_skip(reason, env_optout=False)
            self.assertFalse(r["passed"], reason)
            self.assertTrue(r.get("skipped"), reason)
            self.assertTrue(r.get("degraded"), reason)

    def test_explicit_env_optout_is_benign(self):
        r = self._run_with_skip("simctl_unavailable", env_optout=True)
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_passed_smoke_still_green(self):
        with mock.patch.object(
            sim_runtime, "smoke",
            return_value={"status": "passed", "udidSource": "cached",
                          "processDetail": "pid=1", "screenshotPath": "x.png"},
        ):
            r = check_runtime_smoke(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])


class TestAppUsesRealRepositories(_TempProject):
    def _entry(self, body: str) -> None:
        self.write(f"{APP}/App/{APP}App.swift", body)

    def test_clean_wiring_passes(self):
        self._entry("@main struct DemoApp: App { let repo = ItemRepository() }\n"
                    ".modelContainer(for: Item.self)\nService()\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"], results["no_stubs_in_app"]["message"])

    def test_stub_comment_no_longer_fails(self):
        # The old single-file `Stub` grep hard-failed on a harmless comment —
        # a false-positive that consumed the circuit breaker.
        self._entry("// previews use ServiceStubs\n"
                    "@main struct DemoApp: App { let repo = ItemRepository() }\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"], results["no_stubs_in_app"]["message"])

    def test_stub_instantiation_in_composition_root_fails(self):
        # Stub wiring moved to CompositionRoot.swift used to slip through the
        # entry-file-only grep.
        self._entry("@main struct DemoApp: App {}\n")
        self.write(f"{APP}/App/CompositionRoot.swift",
                   "enum CompositionRoot { static let repo = StubItemRepository() }\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["no_stubs_in_app"]["passed"])
        self.assertIn("CompositionRoot.swift", results["no_stubs_in_app"]["message"])

    def test_stub_in_block_comment_no_longer_fails(self):
        # /* block comments */ (single- and multi-line) must not trip a
        # HARD-FAIL check — false positives here burn the circuit breaker.
        self._entry("@main struct DemoApp: App { let repo = ItemRepository() }\n"
                    "/* legacy: StubItemRepository() was used here */\n"
                    "/*\n let old = StubItemRepository()\n*/\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"], results["no_stubs_in_app"]["message"])

    def test_stub_after_block_comment_still_fails_with_right_line(self):
        self._entry("@main struct DemoApp: App {}\n"
                    "/* comment */\n"
                    "let repo = StubItemRepository()\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["no_stubs_in_app"]["passed"])
        self.assertIn(":3", results["no_stubs_in_app"]["message"])

    def test_service_stubs_file_itself_is_exempt(self):
        self._entry("@main struct DemoApp: App {}\n")
        self.write(f"{APP}/App/ServiceStubs.swift",
                   "struct StubItemRepository {}\nlet preview = StubItemRepository()\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"], results["no_stubs_in_app"]["message"])

    def test_missing_app_dir_fails(self):
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["no_stubs_in_app"]["passed"])


class TestVisualContractDarkMapping(_TempProject):
    """check_visual_contract maps the darkMode sub-result to DEGRADED-only."""

    def _run(self, dark: dict | None) -> list[dict]:
        result = {"status": "passed", "paletteMatch": None, "notes": "full-pillow-analysis"}
        if dark is not None:
            result["darkMode"] = dark
        with mock.patch.object(visual_contract, "evaluate", return_value=result):
            return check_visual_contract(self.proj, APP, {})

    def test_dark_failed_is_degraded_sub_check(self):
        out = self._run({"status": "failed", "reason": "low luminance variance (0.0) in dark mode"})
        dark = next(r for r in out if r["check"] == "visual_contract_dark")
        self.assertFalse(dark["passed"])
        self.assertTrue(dark.get("skipped"))
        self.assertTrue(dark.get("degraded"))
        light = next(r for r in out if r["check"] == "visual_contract")
        self.assertTrue(light["passed"])  # light render itself stays green

    def test_dark_passed_is_green(self):
        out = self._run({"status": "passed", "notes": "variance check"})
        dark = next(r for r in out if r["check"] == "visual_contract_dark")
        self.assertTrue(dark["passed"])
        self.assertFalse(dark.get("degraded", False))

    def test_dark_missing_is_benign_skip(self):
        out = self._run({"status": "skipped", "skipReason": "dark_screenshot_missing"})
        dark = next(r for r in out if r["check"] == "visual_contract_dark")
        self.assertTrue(dark["passed"])
        self.assertTrue(dark.get("skipped"))
        self.assertFalse(dark.get("degraded", False))

    def test_legacy_result_without_dark_field_keeps_single_check(self):
        out = self._run(None)
        self.assertEqual([r["check"] for r in out], ["visual_contract"])


if __name__ == "__main__":
    unittest.main()
