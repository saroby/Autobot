"""Gate 4→5 primary-CTA visibility check — captures Solos build-20260526
'invisible 시작하기' regression. The disabled-state background must not tie
to a page surface color, otherwise the only forward path disappears."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import check_primary_cta_visibility  # noqa: E402


def _proj_with_view(body: str) -> Path:
    d = Path(tempfile.mkdtemp())
    v = d / "Solos" / "Views" / "Onboarding"
    v.mkdir(parents=True)
    (v / "OnboardingView.swift").write_text(body, encoding="utf-8")
    return d


class TestPrimaryCTAVisibility(unittest.TestCase):
    def test_collision_with_theme_surface_fails(self) -> None:
        proj = _proj_with_view(
            'Button(action: {}) {\n'
            '    Text("시작")\n'
            '        .background(canContinue ? Theme.primary : Theme.surface)\n'
            '        .accessibilityIdentifier("autobot.onboarding.primaryCTA")\n'
            '}\n'
        )
        r = check_primary_cta_visibility(proj, "Solos", {})
        self.assertFalse(r[0]["passed"])
        self.assertIn("invisible button", r[0]["message"])

    def test_collision_with_theme_background_fails(self) -> None:
        proj = _proj_with_view(
            'Text("시작")\n'
            '    .background(viewModel.canPost ? Color("Theme/Primary") : Color("Theme/Background"))\n'
            '    .accessibilityIdentifier("autobot.primaryCTA")\n'
        )
        r = check_primary_cta_visibility(proj, "Solos", {})
        self.assertFalse(r[0]["passed"])

    def test_outline_only_pattern_passes(self) -> None:
        proj = _proj_with_view(
            'Text("시작")\n'
            '    .background(enabled ? Theme.primary : Color.clear)\n'
            '    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.primary, lineWidth: 2))\n'
            '    .accessibilityIdentifier("autobot.onboarding.primaryCTA")\n'
        )
        r = check_primary_cta_visibility(proj, "Solos", {})
        self.assertTrue(r[0]["passed"])

    def test_no_anchor_skips(self) -> None:
        proj = _proj_with_view('Text("plain")\n')
        r = check_primary_cta_visibility(proj, "Solos", {})
        self.assertTrue(r[0]["passed"])
        self.assertTrue(r[0].get("skipped"))

    def test_no_views_dir_skips(self) -> None:
        d = Path(tempfile.mkdtemp())
        r = check_primary_cta_visibility(d, "Solos", {})
        self.assertTrue(r[0]["passed"])
        self.assertTrue(r[0].get("skipped"))


if __name__ == "__main__":
    unittest.main()
