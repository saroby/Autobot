"""Tests for scripts/build_preview.py — the /plan storyboard preview builder.

Locks the storyboard-quality strengthening:
  B   — screen PNGs are shown un-cropped (object-fit: contain, never cover)
  A1  — screens ordered (entry → tab groups) + numbered + flow diagram
  A2  — design-spec states + interaction surfaced
  A3  — authoritative screen↔PNG matching via design-spec `## Screen Designs`
  C2  — per-card #screen-N anchors + critique deep-link styling/marker contract
plus graceful fallback (no architecture.json / design-spec) and the FATAL path.
"""

from __future__ import annotations

import base64
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import build_preview  # noqa: E402

# Canonical 1x1 transparent PNG.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

ARCH_MD = """# MyApp

## Overview
A demo app for logging things.

## Features
| # | Feature | Priority | Description |
|---|---------|----------|-------------|
| 1 | Log | P0 | Log stuff |

## Screens
| Screen | Purpose | Tab | Key UI Elements |
|--------|---------|-----|-----------------|
| FeedView | Browse the feed | Feed | list |
| HomeView | Entry dashboard | Home | dashboard |
| SettingsView | App settings | Settings | toggles |
| DetailView | Item detail | Feed | detail |

## Navigation Structure
```
TabView
  Home
  Feed
  Settings
```

## Design Direction
Warm, energetic.
"""

ARCH_JSON = '{"rootScreens": ["HomeView"], "featureModules": ["Home", "Feed", "Settings"]}'

# FeedView maps to a PNG whose stem (scr_feed_v2) does NOT match the screen name
# by any heuristic — so a match can only come from this authoritative table.
SPEC_MD = """# UX Design Specification

## Color Tokens
| Role | Source | SwiftUI | Usage |
|------|--------|---------|-------|
| Primary | #FF6B35 | Theme.primary | brand |

## Typography
| Element | Source | SwiftUI |
|---------|--------|---------|
| Body | 17px regular | .body |

## Screen Designs
| Screen | Design File | Screen ID | Description |
|--------|-------------|------------------|-------------|
| FeedView | designs/scr_feed_v2.png | s1 | the feed |

## Empty, Loading, Error States
| State | Visual Treatment | Copy Tone | Action |
|-------|------------------|-----------|--------|
| Empty | illustrated card | friendly | Add item |
| Loading | skeleton rows | neutral | N/A |

## Interaction Feel
Smooth spring transitions with light haptics on tap.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(root: Path, *, with_json=True, with_spec=True, with_png=True) -> Path:
    autobot = root / ".autobot"
    _write(autobot / "architecture.md", ARCH_MD)
    _write(autobot / "build-state.json", '{"appName": "MyApp", "displayName": "My App"}')
    if with_json:
        _write(autobot / "architecture.json", ARCH_JSON)
    if with_spec:
        _write(autobot / "design-spec.md", SPEC_MD)
    if with_png:
        (autobot / "designs").mkdir(parents=True, exist_ok=True)
        (autobot / "designs" / "scr_feed_v2.png").write_bytes(_PNG_1X1)
    return root


def _build(proj: Path) -> tuple[int, str]:
    out = proj / ".autobot" / "designs" / "preview" / "index.html"
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        rc = build_preview.main(["--project-dir", str(proj)])
    html = out.read_text(encoding="utf-8") if out.is_file() else ""
    return rc, html


class TestStoryboardPreview(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_project(self.root)
        self.rc, self.html = _build(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_builds_successfully(self):
        self.assertEqual(self.rc, 0)
        self.assertIn("<title>MyApp — Plan Preview</title>", self.html)

    # --- B: crop fix -------------------------------------------------------
    def test_screens_not_cropped(self):
        self.assertIn("object-fit: contain", self.html)
        self.assertNotIn("object-fit: cover", self.html)

    # --- A1: ordering + numbering + flow -----------------------------------
    def test_entry_screen_is_numbered_first(self):
        # rootScreens=[HomeView] → HomeView must be storyboard screen #1.
        home = self.html.index('id="screen-1"')
        # its card meta names HomeView
        self.assertIn("HomeView", self.html[home:home + 400])

    def test_screens_ordered_by_tab_group(self):
        order = [self.html.index(f'id="screen-{n}"') for n in (1, 2, 3, 4)]
        self.assertEqual(order, sorted(order))  # ids appear in numeric order
        names = []
        for n in (1, 2, 3, 4):
            i = self.html.index(f'id="screen-{n}"')
            seg = self.html[i:i + 400]
            for nm in ("HomeView", "FeedView", "DetailView", "SettingsView"):
                if nm in seg:
                    names.append(nm)
                    break
        # entry first, then Feed group (Feed module before Settings), then Settings
        self.assertEqual(names, ["HomeView", "FeedView", "DetailView", "SettingsView"])

    def test_flow_diagram_has_lanes(self):
        self.assertIn("화면 흐름 (스토리보드)", self.html)
        self.assertIn('class="flow-node"', self.html)
        self.assertIn(">진입<", self.html)        # root lane label
        self.assertIn('href="#screen-1"', self.html)

    def test_raw_navigation_preserved_in_details(self):
        self.assertIn("<details>", self.html)
        self.assertIn("원본 네비게이션 정의", self.html)
        self.assertIn("TabView", self.html)

    # --- A2: states + interaction ------------------------------------------
    def test_states_section_rendered(self):
        self.assertIn("상태 &amp; 인터랙션", self.html)
        self.assertIn("illustrated card", self.html)
        self.assertIn("skeleton rows", self.html)

    def test_interaction_feel_rendered(self):
        self.assertIn("Smooth spring transitions", self.html)

    # --- A3: authoritative screen↔PNG matching -----------------------------
    def test_authoritative_mapping_matches_nonobvious_filename(self):
        # FeedView (screen-2) is matched only via the Screen Designs table
        # (stem 'scr_feed_v2' matches no heuristic) → must render an <img>.
        i = self.html.index('id="screen-2"')
        seg = self.html[i:i + 500]
        self.assertIn("FeedView", seg)
        self.assertIn("iphone-png", seg)  # an image, not a placeholder

    def test_unmapped_screen_shows_placeholder(self):
        # HomeView (screen-1) has no PNG and no mapping → placeholder.
        i = self.html.index('id="screen-1"')
        seg = self.html[i:i + 500]
        self.assertIn("디자인 미생성", seg)

    # --- C2: critique anchoring contract -----------------------------------
    def test_critique_anchor_affordances_present(self):
        self.assertIn(".critique-screen", self.html)          # deep-link chip style
        self.assertIn(".screen-card:target", self.html)        # highlight on jump
        self.assertIn("→ 화면 N", self.html)                   # persistent hint

    def test_critique_placeholder_marker_preserved(self):
        # autobot-plan-preview skill Step 3 Edit depends on this exact marker.
        self.assertIn("<!-- CRITIQUE_PLACEHOLDER -->", self.html)


class TestFallbacks(unittest.TestCase):
    def test_builds_without_architecture_json_or_spec(self):
        with tempfile.TemporaryDirectory() as d:
            proj = _make_project(Path(d), with_json=False, with_spec=False, with_png=False)
            rc, html = _build(proj)
            self.assertEqual(rc, 0)
            # screens still numbered (storyboard order falls back to tab/original)
            self.assertIn('id="screen-1"', html)
            self.assertIn("화면 흐름 (스토리보드)", html)
            # no design-spec → no states section, no crash
            self.assertNotIn("상태 &amp; 인터랙션", html)
            self.assertIn("<!-- CRITIQUE_PLACEHOLDER -->", html)

    def test_fatal_when_architecture_md_missing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".autobot").mkdir(parents=True)
            buf = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(buf):
                rc = build_preview.main(["--project-dir", d])
            self.assertEqual(rc, 1)
            self.assertIn("FATAL", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
