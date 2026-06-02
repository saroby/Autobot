"""Gate 1->2 check_design_direction_complete — Signature Layout enforcement.

The Signature Layout subsection is the app-specific layout contract that prevents
every generated app from looking like one of 4 molds (visual homogeneity / AI
slop). The architect MUST emit it; this gate greps for the heading.

The key enforcement (advisor verification (a)): a Design Direction complete in
every OTHER way but missing Signature Layout must STILL FAIL — otherwise the
prompt instruction is unenforced and rots like app-review:233 did for seeding.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.setup import check_design_direction_complete  # noqa: E402

_WITHOUT_SIGNATURE = """# Architecture

## Design Direction

### App Personality
warm, organic, personal

### Color Palette
| Role | Name | Light | Dark | Usage |
|------|------|-------|------|-------|
| Primary | terracotta | #C66 | #844 | CTAs |

### Typography Style
| Element | Font Design | Weight |
|---------|------------|--------|
| Display | .rounded | .bold |

### Component Patterns
| Component | Style |
|-----------|-------|
| Cards | photo-forward |
"""

_SIGNATURE_BLOCK = """
### Signature Layout
| 항목 | 설명 |
|------|------|
| Hero element | Today: full-bleed cover photo + countdown |
| 정보 위계 | date/place first, details on tap |
| Density | spacious |
| 화면 간 차별화 | Today=hero card / Map=fullscreen + sheet |
"""


class TestSignatureLayoutGate(unittest.TestCase):
    APP = "Trips"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_arch(self, content: str):
        (self.proj / ".autobot" / "architecture.md").write_text(content)

    def _results(self) -> dict[str, bool]:
        return {
            r["check"]: r["passed"]
            for r in check_design_direction_complete(self.proj, self.APP, {})
        }

    def test_missing_signature_layout_fails_even_when_otherwise_complete(self):
        # Every other Design Direction subsection present — only Signature missing.
        self._write_arch(_WITHOUT_SIGNATURE)
        results = self._results()
        self.assertFalse(results["signature_layout_heading"], "signature must be required")
        # The other subsections still pass — isolating the enforcement to Signature.
        self.assertTrue(results["app_personality_heading"])
        self.assertTrue(results["color_palette_heading"])
        self.assertTrue(results["component_patterns_heading"])

    def test_with_signature_layout_passes(self):
        self._write_arch(_WITHOUT_SIGNATURE + _SIGNATURE_BLOCK)
        results = self._results()
        self.assertTrue(all(results.values()), f"all should pass: {results}")
        self.assertTrue(results["signature_layout_heading"])


if __name__ == "__main__":
    unittest.main()
