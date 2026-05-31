#!/usr/bin/env python3
"""Phase 5→6 visual contract: did the rendered screen actually look like the
design spec said it should?

Checks (in order of cheapness):
  1. screenshot exists and is not a 1×1 / all-blank placeholder
  2. dimensions match a plausible iPhone simulator output (or whatever sips reports)
  3. variance across pixels is non-trivial — catches "blank loading view" regressions
  4. dominant color clusters are within tolerance of the design-spec primary/surface tokens

(4) needs the design-spec to actually declare tokens (`design-spec.json` is the
hard contract, `design-spec.md` is parsed for the legacy primary color block).
When neither source declares a palette, the dominant-color check is `skipped`
but everything else still runs.

All image math is done via either:
  - the macOS-bundled `sips` for metadata, plus
  - `Pillow` when installed (graceful fallback to "metadata-only" mode otherwise).

The result schema is JSON serialisable and matches the shape expected by
`gate_runner.check_visual_contract`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

DOMINANT_COLOR_TOLERANCE_DELTAE = 28  # generous: catches "wildly wrong" only
MIN_SCREENSHOT_BYTES = 4096
MIN_PIXEL_VARIANCE = 90  # below this the screen is effectively monochrome
HEX_RE = re.compile(r"#?([0-9a-fA-F]{6})\b")

# --- Screen-occupancy (the "꽉찬 / fills the screen" floor) ------------------
# The deterministic teeth behind the quality loop: when the user's own idea
# asks for a screen-filling / full-screen layout, a rendered UI whose content
# spans only a small fraction of the device frame (a fixed-size window
# letterboxed in black — the 13%-of-screen Winamp) is a HARD failure, not a
# passing "not blank" screenshot. Guarded by layout-intent so apps that never
# asked for full-screen are unaffected. Content vs background is measured by
# bounding-box SPAN per axis (not pixel density) so a legitimately full-screen
# app with a sparse/dark layout is not false-flagged.
CONTENT_DELTAE = 24            # a pixel is "content" if this far from the bg color
FILL_DEFAULT_MIN_EXTENT = 0.6  # idea says "fill" but no explicit min → span >= 60% of axis
_OCC_W, _OCC_H = 80, 160       # downsample grid for occupancy (tall = phone-shaped)


def _disabled() -> bool:
    return os.environ.get("AUTOBOT_DISABLE_VISUAL_CONTRACT") == "1"


def _result(status: str, **fields) -> dict:
    fields["status"] = status
    return fields


def _sips_dimensions(path: Path) -> tuple[int, int] | None:
    if not shutil.which("sips"):
        return None
    try:
        proc = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    w = h = None
    for line in proc.stdout.splitlines():
        if "pixelWidth" in line:
            try: w = int(line.split(":")[1])
            except (IndexError, ValueError): pass
        if "pixelHeight" in line:
            try: h = int(line.split(":")[1])
            except (IndexError, ValueError): pass
    if w and h:
        return w, h
    return None


def _pillow_stats(path: Path):
    """Return (variance, dominant_rgb) using Pillow if available, else (None, None).

    Dominant color is the centroid of the most populous quantized bucket
    (8-step buckets per channel). This reflects "what color does the user
    actually perceive when looking at the screen" — chrome / status bar
    contribute their pixels but cannot drag dominant to white the way a
    "brightest 25%" sample would.
    """
    try:
        from PIL import Image
    except ImportError:
        return None, None
    try:
        with Image.open(path) as img:
            small = img.convert("RGB").resize((64, 96))  # downsample for speed
            pixels = list(small.get_flattened_data())
    except Exception:
        return None, None
    if not pixels:
        return None, None
    luma = [int(0.299 * r + 0.587 * g + 0.114 * b) for r, g, b in pixels]
    mean_y = sum(luma) / len(luma)
    variance = sum((y - mean_y) ** 2 for y in luma) / len(luma)

    # Histogram of 8-step quantized buckets. Ignore near-white chrome (luma > 230)
    # so dominant reflects the actual UI surface color, not nav-bar pixels.
    buckets: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for px, y in zip(pixels, luma):
        if y > 230:
            continue
        key = (px[0] // 8, px[1] // 8, px[2] // 8)
        buckets.setdefault(key, []).append(px)
    if not buckets:
        # All chrome — fall back to global mean
        rs = [p[0] for p in pixels]; gs = [p[1] for p in pixels]; bs = [p[2] for p in pixels]
        dominant = (sum(rs) // len(rs), sum(gs) // len(gs), sum(bs) // len(bs))
        return variance, dominant
    largest_bucket = max(buckets.values(), key=len)
    rs = [p[0] for p in largest_bucket]
    gs = [p[1] for p in largest_bucket]
    bs = [p[2] for p in largest_bucket]
    dominant = (sum(rs) // len(rs), sum(gs) // len(gs), sum(bs) // len(bs))
    return variance, dominant


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int] | None:
    match = HEX_RE.search(hex_str)
    if not match:
        return None
    h = match.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _delta_e_approx(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    # Cheap deltaE approximation: weighted Euclidean in RGB. Good enough for
    # "is the dominant color the right family" checks (we're not grading print).
    dr = (a[0] - b[0]) * 0.30
    dg = (a[1] - b[1]) * 0.59
    db = (a[2] - b[2]) * 0.11
    return (dr * dr + dg * dg + db * db) ** 0.5


def _palette_from_design_spec(project_root: Path) -> list[tuple[str, tuple[int, int, int]]]:
    """Read primary/secondary/surface tokens from design-spec.json first, then
    fall back to scanning design-spec.md for `#RRGGBB` hex codes under a
    "Primary" / "Secondary" / "Surface" heading.
    """
    palette: list[tuple[str, tuple[int, int, int]]] = []

    spec_json = project_root / ".autobot" / "design-spec.json"
    if spec_json.is_file():
        try:
            data = json.loads(spec_json.read_text(encoding="utf-8"))
            tokens = (data.get("colorTokens") or data.get("palette") or {}) if isinstance(data, dict) else {}
            for label in ("primary", "secondary", "accent", "surface"):
                value = tokens.get(label)
                if isinstance(value, str):
                    rgb = _hex_to_rgb(value)
                    if rgb:
                        palette.append((label, rgb))
        except (json.JSONDecodeError, OSError):
            pass

    if not palette:
        spec_md = project_root / ".autobot" / "design-spec.md"
        if spec_md.is_file():
            try:
                content = spec_md.read_text(encoding="utf-8")
            except OSError:
                content = ""
            for label in ("primary", "secondary", "accent", "surface"):
                pattern = re.compile(rf"{label}[^\n#]*?(#?[0-9a-fA-F]{{6}})", re.IGNORECASE)
                match = pattern.search(content)
                if match:
                    rgb = _hex_to_rgb(match.group(1))
                    if rgb:
                        palette.append((label, rgb))
    return palette


def _default_screenshot(project_root: Path) -> Path:
    state = project_root / ".autobot" / "build-state.json"
    build_id = "unknown-build"
    if state.is_file():
        try:
            build_id = json.loads(state.read_text(encoding="utf-8")).get("buildId") or build_id
        except (json.JSONDecodeError, OSError):
            pass
    candidate = project_root / "artifacts" / build_id / "phase-5" / "runtime-smoke" / "screenshot.png"
    if candidate.is_file():
        return candidate
    return project_root / ".autobot" / "phase-5" / "runtime-smoke" / "screenshot.png"


def _occupancy_stats(path: Path) -> dict | None:
    """Measure how much of the device frame the app's UI actually spans.

    Returns {occupancy, verticalExtent, horizontalExtent, background} or None
    when Pillow is unavailable. `background` is the modal color of the outer
    border ring (the letterbox / device matte); a pixel is "content" when it is
    > CONTENT_DELTAE from that background. verticalExtent / horizontalExtent are
    the fraction of rows / columns that contain ANY content — i.e. the content
    bounding box span per axis. A small fixed-size window pinned to the top of a
    tall screen yields a low verticalExtent (the exact 꽉찬 violation), while a
    full-screen app — even a dark, sparse one — spans most of both axes.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as img:
            small = img.convert("RGB").resize((_OCC_W, _OCC_H))
            try:
                px = list(small.get_flattened_data())  # current Pillow API
            except AttributeError:
                px = list(small.getdata())             # older Pillow
    except Exception:
        return None
    if not px or len(px) != _OCC_W * _OCC_H:
        return None

    def q(p: tuple[int, int, int]) -> tuple[int, int, int]:
        return (p[0] // 16, p[1] // 16, p[2] // 16)

    border: list[tuple[int, int, int]] = []
    for x in range(_OCC_W):
        border.append(px[x])
        border.append(px[(_OCC_H - 1) * _OCC_W + x])
    for y in range(_OCC_H):
        border.append(px[y * _OCC_W])
        border.append(px[y * _OCC_W + _OCC_W - 1])
    counts: dict[tuple[int, int, int], int] = {}
    for p in border:
        k = q(p)
        counts[k] = counts.get(k, 0) + 1
    bgq = max(counts, key=lambda k: counts[k])
    bg = (bgq[0] * 16 + 8, bgq[1] * 16 + 8, bgq[2] * 16 + 8)

    rows: set[int] = set()
    cols: set[int] = set()
    n_content = 0
    for i, p in enumerate(px):
        if _delta_e_approx(p, bg) > CONTENT_DELTAE:
            n_content += 1
            rows.add(i // _OCC_W)
            cols.add(i % _OCC_W)
    return {
        "occupancy": round(n_content / len(px), 3),
        "verticalExtent": round(len(rows) / _OCC_H, 3) if rows else 0.0,
        "horizontalExtent": round(len(cols) / _OCC_W, 3) if cols else 0.0,
        "background": list(bg),
    }


def _raw_idea(project_root: Path) -> str:
    state = project_root / ".autobot" / "build-state.json"
    if state.is_file():
        try:
            idea = json.loads(state.read_text(encoding="utf-8")).get("idea")
            if isinstance(idea, str):
                return idea
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def _fill_requirement(project_root: Path) -> dict | None:
    """Return {min, axis, source} when the build is REQUIRED to fill the screen.

    Priority: an explicit `occupies_screen_fraction` acceptance in feature-spec
    (the architect encoded it — gate 1->2 forces this when the idea has a layout
    clause) → use its params. Else a layout-intent phrase in the raw idea → a
    conservative default min. Else None (no fill requirement → occupancy is
    informational and never fails the gate).
    """
    try:
        from intent_spec import layout_intent_signal, load_feature_spec
    except Exception:
        return None

    features = load_feature_spec(project_root) or []
    for feat in features:
        for acc in getattr(feat, "acceptance", ()):  # type: ignore[attr-defined]
            pc = getattr(acc, "postcondition", None)
            if pc is not None and pc.kind == "occupies_screen_fraction":
                params = pc.params if isinstance(pc.params, dict) else {}
                try:
                    minv = float(params.get("min", FILL_DEFAULT_MIN_EXTENT))
                except (TypeError, ValueError):
                    minv = FILL_DEFAULT_MIN_EXTENT
                axis = params.get("axis", "both")
                if axis not in ("both", "width", "height"):
                    axis = "both"
                return {"min": minv, "axis": axis, "source": f"feature-spec:{getattr(feat,'id','?')}"}

    phrase = layout_intent_signal(_raw_idea(project_root))
    if phrase:
        return {"min": FILL_DEFAULT_MIN_EXTENT, "axis": "both", "source": f"idea-signal:{phrase}"}
    return None


def evaluate(project_root: Path, screenshot: Path | None = None) -> dict:
    if _disabled():
        return _result("skipped", skipReason="visual_contract_disabled")

    screenshot = screenshot or _default_screenshot(project_root)
    if not screenshot.is_file():
        return _result("skipped", skipReason="screenshot_missing", screenshotPath=str(screenshot))

    size = screenshot.stat().st_size
    if size < MIN_SCREENSHOT_BYTES:
        return _result(
            "failed",
            reason=f"screenshot too small ({size} bytes) — likely all-black or empty",
            screenshotPath=str(screenshot),
        )

    dims = _sips_dimensions(screenshot)
    variance, dominant = _pillow_stats(screenshot)
    palette = _palette_from_design_spec(project_root)

    palette_match: dict | None = None
    if dominant and palette:
        best = min(palette, key=lambda item: _delta_e_approx(item[1], dominant))
        palette_match = {
            "dominant": list(dominant),
            "closestToken": best[0],
            "closestTokenRgb": list(best[1]),
            "deltaE": round(_delta_e_approx(best[1], dominant), 1),
            "tolerance": DOMINANT_COLOR_TOLERANCE_DELTAE,
        }

    # Screen-occupancy: does the rendered UI actually fill the frame the way the
    # user asked? Measured always (informational); enforced as a HARD failure
    # only when the build is REQUIRED to fill the screen (idea layout clause or
    # an occupies_screen_fraction acceptance). This is deterministic, so unlike
    # the LLM visual_judge it can legitimately block.
    occ = _occupancy_stats(screenshot)
    fill_req = _fill_requirement(project_root)
    fill_eval: dict | None = None
    if fill_req is not None and occ is not None:
        axis = fill_req["axis"]
        measured = (
            occ["verticalExtent"] if axis == "height"
            else occ["horizontalExtent"] if axis == "width"
            else min(occ["verticalExtent"], occ["horizontalExtent"])
        )
        fill_eval = {
            "required": fill_req, "measuredExtent": round(measured, 3),
            "occupancy": occ["occupancy"], "met": measured >= fill_req["min"],
        }

    # Hard failures (only structural problems that we're confident about
    # without first-build calibration data):
    #   - screenshot too small (already returned above)
    #   - dimensions absurdly small (caught here)
    #   - all-monochrome (variance below threshold)
    #   - REQUIRED to fill the screen but content spans only a small fraction
    #
    # Color-match (deltaE vs design tokens) is recorded but NOT a fail signal.
    # The deltaE tolerance was picked from one synthetic fixture — we need
    # real-screenshot data to know what threshold catches real regressions
    # without false-positives. Until then, palette_match is informational only.
    hard_findings: list[str] = []
    if dims and (dims[0] < 200 or dims[1] < 400):
        hard_findings.append(f"dimensions {dims[0]}x{dims[1]} are smaller than any iPhone simulator")
    if variance is not None and variance < MIN_PIXEL_VARIANCE:
        hard_findings.append(f"low luminance variance ({variance:.1f}) — screen looks monochrome")
    if fill_eval is not None and not fill_eval["met"]:
        hard_findings.append(
            f"screen-fill requirement unmet: the idea asks the UI to fill the screen "
            f"({fill_req['source']}, min span {fill_req['min']} on '{fill_req['axis']}') but "
            f"content spans only {fill_eval['measuredExtent']:.2f} (occupancy {occ['occupancy']:.2f}) "
            f"— the window is letterboxed, not filling the screen. Scale the UI to fill the frame "
            f"(and/or stack sub-windows) and re-render."
        )

    if hard_findings:
        return _result(
            "failed",
            reason="; ".join(hard_findings),
            screenshotPath=str(screenshot),
            dimensions=list(dims) if dims else None,
            variance=variance,
            dominant=list(dominant) if dominant else None,
            paletteMatch=palette_match,
            occupancy=occ,
            fillRequirement=fill_eval,
        )

    # Informational note about palette mismatch when present, but never fails.
    palette_warning = None
    if palette_match and palette_match.get("deltaE", 0) > DOMINANT_COLOR_TOLERANCE_DELTAE:
        palette_warning = (
            f"dominant {dominant} is {palette_match['deltaE']:.1f}ΔE from nearest design "
            f"token '{palette_match['closestToken']}' — review (informational, not blocking)"
        )

    return _result(
        "passed",
        screenshotPath=str(screenshot),
        dimensions=list(dims) if dims else None,
        variance=variance,
        dominant=list(dominant) if dominant else None,
        paletteMatch=palette_match,
        paletteWarning=palette_warning,
        occupancy=occ,
        fillRequirement=fill_eval,
        notes="metadata-only" if variance is None else "full-pillow-analysis",
    )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--screenshot", default=None, help="override screenshot path")
    args = parser.parse_args()

    shot = Path(args.screenshot) if args.screenshot else None
    result = evaluate(Path(args.project_dir).resolve(), shot)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in ("passed", "skipped"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
