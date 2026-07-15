"""Regression for sim_runtime._find_built_app: a candidate whose `<App>` is a
directory (the xcodegen `type: folder` build artifact captured in Solos /
Murmur build-20260526) must be skipped so the smoke gate doesn't try to
install a broken bundle."""

from __future__ import annotations

import struct
import tempfile
import unittest
import json
import plistlib
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from sim_runtime import _find_built_app, _is_valid_app_bundle  # noqa: E402
from artifact_provenance import write_app_manifest  # noqa: E402


# Mach-O 64-bit LE magic (cffaedfe). Real binary header but contents are
# truncated — only the magic is checked.
MACH_O_64_LE = struct.pack("<I", 0xFEEDFACF)


def _make_bundle(parent: Path, app_name: str, *, healthy: bool) -> Path:
    bundle = parent / f"{app_name}.app"
    bundle.mkdir(parents=True, exist_ok=True)
    inner = bundle / app_name
    if healthy:
        inner.write_bytes(MACH_O_64_LE + b"\x00" * 28)
        with (bundle / "Info.plist").open("wb") as f:
            plistlib.dump({
                "CFBundleIdentifier": f"com.example.{app_name.lower()}",
                "CFBundleShortVersionString": "1.0",
                "CFBundleVersion": "1",
                "CFBundleExecutable": app_name,
            }, f)
    else:
        # broken: inner is a directory, matching the xcodegen type: folder regression
        inner.mkdir(parents=True, exist_ok=True)
    return bundle


class TestIsValidAppBundle(unittest.TestCase):
    def test_directory_inner_is_invalid(self) -> None:
        d = Path(tempfile.mkdtemp())
        b = _make_bundle(d, "Solos", healthy=False)
        self.assertFalse(_is_valid_app_bundle(b, "Solos"))

    def test_mach_o_inner_is_valid(self) -> None:
        d = Path(tempfile.mkdtemp())
        b = _make_bundle(d, "Solos", healthy=True)
        self.assertTrue(_is_valid_app_bundle(b, "Solos"))

    def test_missing_inner_is_invalid(self) -> None:
        d = Path(tempfile.mkdtemp())
        b = d / "X.app"
        b.mkdir()
        self.assertFalse(_is_valid_app_bundle(b, "X"))


class TestFindBuiltAppPrefersValid(unittest.TestCase):
    def test_phase5_attempt_with_healthy_binary_is_returned(self) -> None:
        proj = Path(tempfile.mkdtemp())
        (proj / ".autobot").mkdir()
        (proj / ".autobot" / "build-state.json").write_text(json.dumps({"buildId": "build-123"}))
        attempt_root = proj / "artifacts" / "build-123" / "phase-5" / "attempt-1"
        products = attempt_root / "DerivedData" / "Build" / "Products" / "Debug-iphonesimulator"
        products.mkdir(parents=True)
        app = _make_bundle(products, "Solos", healthy=True)
        write_app_manifest(
            app, attempt_root / "artifact-provenance.json",
            build_id="build-123", app_name="Solos", attempt=1,
            derived_data_path=attempt_root / "DerivedData",
        )
        result = _find_built_app(proj, "Solos")
        self.assertIsNotNone(result)
        self.assertEqual(result, app.resolve())

    def test_legacy_or_global_candidate_without_manifest_is_rejected(self) -> None:
        proj = Path(tempfile.mkdtemp())
        attempt = proj / ".autobot" / "phase-5" / "attempt-1" / "Build" / "Products" / "Debug-iphonesimulator"
        attempt.mkdir(parents=True)
        _make_bundle(attempt, "Solos", healthy=True)
        self.assertIsNone(_find_built_app(proj, "Solos"))

    def test_manifest_digest_mismatch_is_rejected(self) -> None:
        proj = Path(tempfile.mkdtemp())
        (proj / ".autobot").mkdir()
        (proj / ".autobot" / "build-state.json").write_text(json.dumps({"buildId": "build-123"}))
        attempt_root = proj / "artifacts" / "build-123" / "phase-5" / "attempt-1"
        products = attempt_root / "DerivedData" / "Build" / "Products" / "Debug-iphonesimulator"
        products.mkdir(parents=True)
        app = _make_bundle(products, "Solos", healthy=True)
        write_app_manifest(
            app, attempt_root / "artifact-provenance.json",
            build_id="build-123", app_name="Solos", attempt=1,
            derived_data_path=attempt_root / "DerivedData",
        )
        (app / "unexpected.txt").write_text("tampered")
        self.assertIsNone(_find_built_app(proj, "Solos"))

    def test_newer_attempt_without_manifest_does_not_fall_back(self) -> None:
        proj = Path(tempfile.mkdtemp())
        (proj / ".autobot").mkdir()
        (proj / ".autobot" / "build-state.json").write_text(json.dumps({"buildId": "build-123"}))
        attempt_one = proj / "artifacts" / "build-123" / "phase-5" / "attempt-1"
        products = attempt_one / "DerivedData" / "Build" / "Products" / "Debug-iphonesimulator"
        products.mkdir(parents=True)
        app = _make_bundle(products, "Solos", healthy=True)
        write_app_manifest(
            app, attempt_one / "artifact-provenance.json",
            build_id="build-123", app_name="Solos", attempt=1,
            derived_data_path=attempt_one / "DerivedData",
        )
        (proj / "artifacts" / "build-123" / "phase-5" / "attempt-2").mkdir()
        self.assertIsNone(_find_built_app(proj, "Solos"))


if __name__ == "__main__":
    unittest.main()
