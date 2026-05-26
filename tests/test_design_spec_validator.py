"""Tests for scripts/design_spec_validator.py — schema validation +
deterministic synthesis from architecture.md / design-spec.md / app idea.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from design_spec_validator import (  # noqa: E402
    CATEGORY_PALETTES,
    DEFAULT_ANCHORS,
    SCHEMA_VERSION,
    detect_category,
    ensure,
    synthesize,
    validate,
)


class TestValidate(unittest.TestCase):
    def _base(self, **overrides):
        payload = {
            "version": SCHEMA_VERSION,
            "appName": "Demo",
            "colorTokens": {
                "primary": "#3B5BDB", "secondary": "#15AABF",
                "accent": "#FAB005", "surface": "#F4F6FB",
            },
            "typography": {"design": "rounded", "headingWeight": "semibold"},
            "spacing": {"base": 4, "card": 16, "section": 24},
            "visualAnchors": list(DEFAULT_ANCHORS),
        }
        payload.update(overrides)
        return payload

    def test_complete_payload_passes(self):
        self.assertEqual(validate(self._base()), [])

    def test_wrong_version_flagged(self):
        problems = validate(self._base(version=99))
        self.assertTrue(any("version" in p for p in problems))

    def test_invalid_hex_flagged(self):
        bad = self._base()
        bad["colorTokens"]["primary"] = "not-a-color"
        problems = validate(bad)
        self.assertTrue(any("primary" in p for p in problems))

    def test_invalid_typography_design_flagged(self):
        bad = self._base()
        bad["typography"]["design"] = "comic-sans"
        problems = validate(bad)
        self.assertTrue(any("typography.design" in p for p in problems))

    def test_empty_anchors_flagged(self):
        bad = self._base(visualAnchors=[])
        problems = validate(bad)
        self.assertTrue(any("visualAnchors" in p for p in problems))

    def test_non_positive_spacing_flagged(self):
        bad = self._base()
        bad["spacing"]["base"] = 0
        problems = validate(bad)
        self.assertTrue(any("spacing.base" in p for p in problems))


class TestDetectCategory(unittest.TestCase):
    def test_korean_fitness_keyword(self):
        self.assertEqual(detect_category("달리기 트래커"), "fitness")

    def test_english_finance_keyword(self):
        self.assertEqual(detect_category("simple budget tracker"), "finance")

    def test_unknown_falls_back_to_default(self):
        self.assertEqual(detect_category("completely abstract concept"), "default")

    def test_food_korean_keyword(self):
        self.assertEqual(detect_category("레시피 공유 앱"), "food")


class TestSynthesize(unittest.TestCase):
    def test_synthesizes_valid_spec_with_no_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = synthesize(Path(tmp), app_name="Demo", idea="여행 일기")
            self.assertEqual(spec["version"], SCHEMA_VERSION)
            self.assertEqual(spec["appName"], "Demo")
            self.assertEqual(spec["appCategory"], "travel")
            self.assertEqual(validate(spec), [])

    def test_extracts_palette_from_design_spec_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            (proj / ".autobot" / "design-spec.md").write_text(
                "## Palette\n- primary: #112233\n- secondary: #445566\n"
                "- accent: #778899\n- surface: #AABBCC\n"
            )
            spec = synthesize(proj, app_name="X", idea="x")
            # Primary should come from md, not from fallback
            self.assertEqual(spec["colorTokens"]["primary"], "#112233")
            self.assertEqual(spec["_synthesizedFrom"]["fallbackPalette"], False)

    def test_falls_back_to_category_palette_when_no_hex(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = synthesize(Path(tmp), app_name="Demo", idea="달리기 트래커")
            self.assertEqual(spec["colorTokens"]["primary"], CATEGORY_PALETTES["fitness"]["primary"])
            self.assertTrue(spec["_synthesizedFrom"]["fallbackPalette"])

    def test_typography_picks_rounded_for_fitness(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = synthesize(Path(tmp), app_name="X", idea="달리기 트래커")
            self.assertEqual(spec["typography"]["design"], "rounded")

    def test_typography_default_for_finance(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = synthesize(Path(tmp), app_name="X", idea="budget tracker")
            self.assertEqual(spec["typography"]["design"], "default")


class TestEnsure(unittest.TestCase):
    def test_writes_synthesized_spec_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            path, payload, problems = ensure(proj, app_name="Demo", idea="달리기")
            self.assertEqual(problems, [])
            self.assertTrue(path.is_file())
            saved = json.loads(path.read_text())
            self.assertEqual(saved["appName"], "Demo")
            self.assertEqual(saved["appCategory"], "fitness")

    def test_preserves_existing_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            existing = {
                "version": SCHEMA_VERSION,
                "appName": "Curated",
                "colorTokens": {
                    "primary": "#000000", "secondary": "#111111",
                    "accent": "#222222", "surface": "#FFFFFF",
                },
                "typography": {"design": "serif", "headingWeight": "bold"},
                "spacing": {"base": 8, "card": 20, "section": 32},
                "visualAnchors": ["autobot.root"],
            }
            spec_path = proj / ".autobot" / "design-spec.json"
            spec_path.write_text(json.dumps(existing))
            path, payload, problems = ensure(proj, app_name="Other", idea="other")
            self.assertEqual(problems, [])
            self.assertEqual(payload["appName"], "Curated")  # not overwritten
            self.assertEqual(payload["typography"]["design"], "serif")


if __name__ == "__main__":
    unittest.main()
