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

import metadata_validator  # noqa: E402
import sim_runtime  # noqa: E402
import visual_contract  # noqa: E402
from gate_checks.app import (  # noqa: E402
    check_composition_seam_intact,
    check_models_checksum_matches,
    check_no_hardcoded_font_sizes,
)
from gate_checks.build import (  # noqa: E402
    check_app_uses_real_repositories,
    check_metadata_readiness,
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

    def test_denylist_covers_mock_fake_inmemory_dummy_preview(self):
        # Renaming a stub (Mock*/InMemory*/…) must not slip past the hard gate.
        for prefix in ("Mock", "Fake", "InMemory", "Dummy", "Preview"):
            with self.subTest(prefix=prefix):
                self._entry(f"@main struct DemoApp: App {{ let repo = {prefix}ItemRepository() }}\n")
                results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
                self.assertFalse(results["no_stubs_in_app"]["passed"],
                                 results["no_stubs_in_app"]["message"])

    def test_comment_only_repository_mention_does_not_satisfy_services(self):
        # `// TODO: wire FooRepository` must not green-light has_real_services.
        self._entry("@main struct DemoApp: App {}\n"
                    "// TODO: wire FooRepository and ModelContainer here\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["has_real_services"]["passed"])
        self.assertFalse(results["has_model_container"]["passed"])

    def test_wiring_in_composition_root_satisfies_services(self):
        # Documented contract puts production wiring in CompositionRoot.swift —
        # the entry-file-only grep used to false-fail this legitimate layout.
        self._entry("@main struct DemoApp: App { var body: some Scene { WindowGroup { CompositionRoot() } } }\n")
        self.write(f"{APP}/App/CompositionRoot.swift",
                   "enum CompositionRoot { static let repo = ItemRepository() }\n"
                   ".modelContainer(for: Item.self)\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"])
        self.assertTrue(results["has_real_services"]["passed"])
        self.assertTrue(results["has_model_container"]["passed"])

    def test_type_annotation_only_does_not_satisfy_services(self):
        # `var repo: ItemRepository?` is a type reference, NOT production wiring —
        # only an instantiation `FooRepository(` counts.
        self._entry("@main struct DemoApp: App { var repo: ItemRepository? }\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["has_real_services"]["passed"],
                         results["has_real_services"]["message"])

    def test_real_wiring_pattern_satisfies_services(self):
        # The documented wiring form (wiring-patterns.md) instantiates the repo
        # with the model context — this MUST pass the hard gate.
        self.write(f"{APP}/App/CompositionRoot.swift",
                   "struct CompositionRoot: View {\n"
                   "    let container: ModelContainer\n"
                   "    var body: some View {\n"
                   "        RootView(itemService: ItemRepository(modelContext: container.mainContext))\n"
                   "    }\n"
                   "}\n")
        self._entry("@main struct DemoApp: App {}\n")
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["has_real_services"]["passed"],
                        results["has_real_services"]["message"])
        self.assertTrue(results["has_model_container"]["passed"])

    def test_stub_in_string_literal_does_not_fail(self):
        # `MockItemRepository()` inside a STRING (log message, test name) must
        # not trip the hard no_stubs gate — only executable code counts.
        self._entry('@main struct DemoApp: App { let repo = ItemRepository()\n'
                    'let msg = "do not use MockItemRepository() in prod" }\n')
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertTrue(results["no_stubs_in_app"]["passed"],
                        results["no_stubs_in_app"]["message"])

    def test_stub_in_code_still_fails_when_a_string_stub_also_present(self):
        # A real stub instantiation in code fails even if a sibling line has the
        # stub name only inside a string.
        self._entry('@main struct DemoApp: App { let repo = StubItemRepository()\n'
                    'let msg = "ignore MockItemRepository() text" }\n')
        results = {r["check"]: r for r in check_app_uses_real_repositories(self.proj, APP, {})}
        self.assertFalse(results["no_stubs_in_app"]["passed"],
                         results["no_stubs_in_app"]["message"])


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

    def test_env_killswitch_skip_is_degraded_not_benign(self):
        # AUTOBOT_DISABLE_VISUAL_CONTRACT=1 must leave an audit trail: DEGRADED,
        # never a clean pass (unlike ordinary resource skips).
        with mock.patch.object(
            visual_contract, "evaluate",
            return_value={"status": "skipped", "skipReason": "visual_contract_disabled"},
        ):
            r = check_visual_contract(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))

    def test_ordinary_skip_stays_benign(self):
        with mock.patch.object(
            visual_contract, "evaluate",
            return_value={"status": "skipped", "skipReason": "screenshot_missing"},
        ):
            r = check_visual_contract(self.proj, APP, {})[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))


class TestMetadataReadinessMapping(_TempProject):
    """check_metadata_readiness maps metadata_validator.evaluate's 3-state
    result to (passed, skipped, degraded) — pinned with evaluate mocked."""

    def _run(self, result: dict, *, asc: bool = False) -> dict:
        state = {"environment": {"ascConfigured": asc}}
        with mock.patch.object(metadata_validator, "evaluate", return_value=result) as ev:
            out = check_metadata_readiness(self.proj, APP, state)[0]
            # asc_configured must be forwarded — the skip↔hard-require flip
            # lives inside evaluate.
            self.assertEqual(ev.call_args.kwargs.get("asc_configured"), asc)
        return out

    def test_skipped_is_benign(self):
        r = self._run({"status": "skipped", "skipReason": "asc_not_configured"})
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_passed_is_green(self):
        r = self._run({
            "status": "passed", "locale": "ko", "category": "PRODUCTIVITY",
            "age_rating": "4+", "export_compliance": "false",
            "screenshotCounts": {"6.9": 3},
        }, asc=True)
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_failed_is_degraded_not_a_hard_fail(self):
        # Was a hard fail. `ascConfigured` describes the MACHINE (an ASC key is
        # on disk), not the RUN, so a purely local /autobot:mvp build on any
        # developer machine that ever configured ASC was failed by a shipping
        # gate it cannot satisfy — /autobot:mvp produces no store screenshots
        # and no privacy questionnaire at all. Worse, gate56Status=failed then
        # dragged functionalVerification.badge to UNVERIFIED even with every
        # functional flow green (measured 2026-08-29: 12/12 flows, badge
        # UNVERIFIED, this the sole failing check). DEGRADED still blocks
        # shipping via check_functional_verification_passed + preflight-ship.
        r = self._run({"status": "failed", "reason": "age rating config missing"}, asc=True)
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))
        self.assertIn("age rating", r["message"])

    def test_env_killswitch_skip_is_degraded(self):
        r = self._run({"status": "skipped", "skipReason": "metadata_gate_disabled"}, asc=True)
        self.assertFalse(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))


class TestCompositionSeamIntact(_TempProject):
    def _write_seam(self):
        self.write(f"{APP}/App/{APP}App.swift",
                   "@main\nstruct DemoApp: App {}\n")
        self.write(f"{APP}/App/ServiceStubs.swift", "struct StubItemRepository {}\n")

    def _by_check(self, state=None) -> dict:
        return {r["check"]: r for r in check_composition_seam_intact(self.proj, APP, state or {})}

    def test_single_main_and_stubs_pass(self):
        self._write_seam()
        r = self._by_check()
        self.assertTrue(r["single_main_entry"]["passed"])
        self.assertTrue(r["service_stubs_present"]["passed"])

    def test_duplicate_main_fails(self):
        self._write_seam()
        self.write(f"{APP}/Views/Second.swift", "@main\nstruct Second: App {}\n")
        r = self._by_check()
        self.assertFalse(r["single_main_entry"]["passed"])
        self.assertIn("multiple @main", r["single_main_entry"]["message"])

    def test_no_main_fails(self):
        self.write(f"{APP}/App/ServiceStubs.swift", "struct StubItemRepository {}\n")
        r = self._by_check()
        self.assertFalse(r["single_main_entry"]["passed"])

    def test_fatalerror_in_composition_root_fails(self):
        self._write_seam()
        self.write(f"{APP}/App/CompositionRoot.swift",
                   "struct CompositionRoot: View { init() { fatalError(\"unwired\") } }\n")
        r = self._by_check()
        self.assertFalse(r["composition_root_clean"]["passed"])

    def test_clean_composition_root_passes(self):
        self._write_seam()
        self.write(f"{APP}/App/CompositionRoot.swift",
                   "struct CompositionRoot: View { var body: some View { RootView() } }\n")
        r = self._by_check()
        self.assertTrue(r["composition_root_clean"]["passed"])


class TestModelsChecksumMatches(_TempProject):
    def test_missing_snapshot_fails(self):
        self.write(f"{APP}/Models/Item.swift", "struct Item {}\n")
        r = check_models_checksum_matches(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertIn("snapshot missing", r["message"])

    def test_save_then_verify_passes_and_mutation_fails(self):
        import subprocess
        from conftest import SCRIPTS_DIR
        self.write(f"{APP}/Models/Item.swift", "struct Item {}\n")
        save = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "snapshot-contracts.sh"), "save",
             "--app-name", APP, "--project-dir", str(self.proj)],
            capture_output=True, text=True,
        )
        self.assertEqual(save.returncode, 0, msg=save.stdout + save.stderr)
        r = check_models_checksum_matches(self.proj, APP, {})[0]
        self.assertTrue(r["passed"], r["message"])

        self.write(f"{APP}/Models/Item.swift", "struct Item { var mutated = true }\n")
        r = check_models_checksum_matches(self.proj, APP, {})[0]
        self.assertFalse(r["passed"])
        self.assertIn("MISMATCH", r["message"])


class TestFastlaneMetadataFilenames(unittest.TestCase):
    """`fastlane/metadata/` fields are `<field>.txt` — read them that way.

    The reader looked for extensionless `<field>`, so every field this plugin's
    own `write-metadata.sh` produces came back empty and a correctly generated
    listing always failed `metadata_readiness`. Measured 2026-08-29 on a real
    build: `ko/description.txt` held 2,469 bytes and the validator read "".
    """

    def _project(self) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root, True)
        locale = root / "fastlane" / "metadata" / "ko"
        locale.mkdir(parents=True)
        for field, value in (
            ("name", "눈치"),
            ("subtitle", "지금 사도 되나"),
            ("description", "본문"),
            ("keywords", "공포지수,투자심리"),
            ("support_url", "https://example.com/support"),
        ):
            (locale / f"{field}.txt").write_text(value, encoding="utf-8")
        # Catalog fields live at the metadata ROOT, not under the locale.
        (root / "fastlane" / "metadata" / "primary_category.txt").write_text(
            "FINANCE", encoding="utf-8")
        return root

    def test_locale_fields_are_read(self):
        payload = metadata_validator._load_fastlane_metadata(self._project())
        self.assertEqual(payload["locale"], "ko")
        self.assertEqual(payload["name"], "눈치")
        self.assertEqual(payload["description"], "본문")
        self.assertEqual(payload["keywords"], "공포지수,투자심리")
        self.assertEqual(payload["support_url"], "https://example.com/support")

    def test_catalog_fields_fall_back_to_the_metadata_root(self):
        payload = metadata_validator._load_fastlane_metadata(self._project())
        self.assertEqual(payload["category"], "FINANCE")

    def test_genuinely_absent_fields_stay_empty(self):
        # The fix must not paper over real gaps: screenshots and the privacy
        # questionnaire are produced by /autobot:app-review, not by this reader.
        payload = metadata_validator._load_fastlane_metadata(self._project())
        self.assertEqual(payload["screenshots"], {})
        self.assertEqual(payload["privacy_questionnaire"], "")


if __name__ == "__main__":
    unittest.main()
