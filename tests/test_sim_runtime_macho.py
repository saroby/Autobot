"""Regression for sim_runtime._find_built_app: a candidate whose `<App>` is a
directory (the xcodegen `type: folder` build artifact captured in Solos /
Murmur build-20260526) must be skipped so the smoke gate doesn't try to
install a broken bundle."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from sim_runtime import _find_built_app, _is_valid_app_bundle  # noqa: E402


# Mach-O 64-bit LE magic (cffaedfe). Real binary header but contents are
# truncated — only the magic is checked.
MACH_O_64_LE = struct.pack("<I", 0xFEEDFACF)


def _make_bundle(parent: Path, app_name: str, *, healthy: bool) -> Path:
    bundle = parent / f"{app_name}.app"
    bundle.mkdir(parents=True, exist_ok=True)
    inner = bundle / app_name
    if healthy:
        inner.write_bytes(MACH_O_64_LE + b"\x00" * 28)
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
        attempt = proj / ".autobot" / "phase-5" / "attempt-1" / "Build" / "Products" / "Debug-iphonesimulator"
        attempt.mkdir(parents=True)
        _make_bundle(attempt, "Solos", healthy=True)
        result = _find_built_app(proj, "Solos")
        self.assertIsNotNone(result)
        self.assertEqual(result.parent, attempt)

    def test_phase5_broken_returns_none_when_no_other_candidate(self) -> None:
        proj = Path(tempfile.mkdtemp())
        attempt = proj / ".autobot" / "phase-5" / "attempt-1" / "Build" / "Products" / "Debug-iphonesimulator"
        attempt.mkdir(parents=True)
        _make_bundle(attempt, "Solos", healthy=False)
        # DerivedData scan would also find nothing matching name "Solos" on
        # this temp host. Result must be None — never return the broken one.
        result = _find_built_app(proj, "Solos-not-in-deriveddata-1f7d")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
