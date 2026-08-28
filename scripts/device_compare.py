#!/usr/bin/env python3
"""device_compare.py — put the original and the reproduction side by side.

`/autobot:clone` Step 6 refuses to call a screen done until a human can see both
at once. Matching numbers are not evidence: a view can measure right and still
look wrong.

    device_compare.py <original.png> <rendered.png> <out.png>
        [--measure screen.json] [--heatmap diff.png]
        [--mask x,y,w,h ...] [--mask-system-chrome] [--exclusions regions.json]
        [--align PX] [--score-log scores.jsonl --label STEM]

The two are rarely the same pixel size (a 12 mini capture next to a 17 Pro
simulator), so the taller one is scaled to the other's height by nearest
neighbour before they are joined with a divider. stdlib only — the PNG reader is
shared with device_measure, and the writer is a few lines of zlib.

Three numbers come out of a same-size pair, and they disagree on purpose:

  mismatch  how many pixels differ. Cheap, and wrong about a screen that is
            correct but shifted two points — nearly every pixel differs.
  mae       how far they differ. Catches a palette that drifted.
  ssim      whether the same structure is in the same place. The one that
            survives anti-aliasing and font hinting, and the one that falls
            when content is in the wrong place or absent.

Nothing here is a similarity target on its own. `--score-log` appends them per
screen per run so a regression is visible as a fall rather than as a number
somebody has to remember.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_measure import PNG  # noqa: E402  (same-directory sibling)

DIVIDER = 8
DIVIDER_RGB = (255, 0, 0)
MASKED_RGB = (32, 32, 32)
PIXEL_DIFF_THRESHOLD = 24
REGION_HIGH_MISMATCH = 0.30
REGION_HIGH_MAE = 0.20
REGION_MEDIUM_MISMATCH = 0.10
REGION_MEDIUM_MAE = 0.05

# SSIM over non-overlapping 8x8 luma windows. Windows, not a single global
# figure: one number for a whole screen averages a broken header into a correct
# feed and reports neither.
SSIM_WINDOW = 8
SSIM_C1 = (0.01 * 255) ** 2
SSIM_C2 = (0.03 * 255) ** 2

# A capture crop is legitimate for an icon and is a forgery for a screen. Past
# this share of the frame the reproduction is showing a photograph of the
# original instead of drawing it, and every pixel score becomes a measure of
# where the photograph was pasted.
MAX_ASSET_COVERAGE = 0.60

# Roughly how many pixels one alignment trial should look at. Alignment costs
# (2*max_shift+1)^2 trials, so this — not the screen size — is what bounds it.
_ALIGN_SAMPLE_TARGET = 20000

RGB = tuple[int, int, int]
Rows = list[list[RGB]]
Bounds = tuple[int, int, int, int]
Mask = list[bytearray]


class DiffMetrics(NamedTuple):
    mismatch: float
    mae: float
    compared_pixels: int
    differing_pixels: int


def rows_rgb(png: PNG) -> Rows:
    ch = png.channels
    return [[tuple(row[x * ch:x * ch + 3]) for x in range(png.width)] for row in png.rows]


def scale_to(rows: Rows, width: int, height: int) -> Rows:
    """Nearest-neighbour resample — exactness is the eye's job here, not the filter's."""
    src_h, src_w = len(rows), len(rows[0])
    if _np is not None:
        ys = _np.minimum(src_h - 1, _np.arange(height) * src_h // height)
        xs = _np.minimum(src_w - 1, _np.arange(width) * src_w // width)
        return _as_array(rows, _np.uint8)[ys][:, xs]
    return [[rows[min(src_h - 1, y * src_h // height)][min(src_w - 1, x * src_w // width)]
             for x in range(width)] for y in range(height)]


def join_side_by_side(left: Rows, right: Rows, gap: int, colour: RGB) -> Rows:
    """The two images with a divider between them, as one image."""
    if _np is not None and hasattr(left, "shape"):
        divider = _np.empty((len(left), gap, 3), dtype=_np.uint8)
        divider[:, :, :] = colour
        return _np.concatenate((left, divider, right), axis=1)
    filler = [colour] * gap
    return [left[y] + filler + right[y] for y in range(len(left))]


def write_png(path: str, rows: Rows) -> None:
    if _np is not None and hasattr(rows, "shape"):
        pixels = _np.ascontiguousarray(rows, dtype=_np.uint8)
        height, width = pixels.shape[0], pixels.shape[1]
        # One leading zero (filter type "none") per scanline, same as below.
        scanlines = _np.zeros((height, width * 3 + 1), dtype=_np.uint8)
        scanlines[:, 1:] = pixels.reshape(height, width * 3)
        raw = scanlines.tobytes()
    else:
        raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in rows)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def _same_dimensions(left: Rows, right: Rows) -> bool:
    # len(), never truthiness: after a resample these are numpy arrays when
    # numpy is installed, and `if array` raises instead of asking about size.
    return bool(len(left) and len(right) and len(left[0]) and len(right[0])
                and len(left) == len(right) and len(left[0]) == len(right[0]))


# Optional, never required: this file is stdlib-only by design (see the module
# docstring) and the pure-Python loop below stays the definition of the metric.
# A verify run compares one full 1124x2436 pair plus a per-element region for
# every measured element — 31 screens of that is minutes of interpreter time,
# and the whole point of the run is a fix/re-verify loop.
try:
    import numpy as _np
except ImportError:  # pragma: no cover - exercised by the pure-Python path test
    _np = None

# Holds the source alongside the array so the id() key cannot be recycled while
# the entry is live. Two images and a mask per run, in up to a couple of dtypes
# each, so eight is plenty.
#
# The dtype is part of the key. Without it a uint8 entry cached for one caller
# is handed back to `_detailed_metrics`, whose `abs(a - b)` then wraps around at
# 255 and reports a large difference as a small one.
_ARRAY_CACHE: list[tuple[int, object, object, object]] = []


def _as_array(rows, dtype):
    key = id(rows)
    for cached_key, source, cached_dtype, array in _ARRAY_CACHE:
        if cached_key == key and source is rows and cached_dtype == dtype:
            return array
    array = _np.asarray(rows, dtype=dtype)
    _ARRAY_CACHE.append((key, rows, dtype, array))
    del _ARRAY_CACHE[:-8]
    return array


def _detailed_metrics(left: Rows, right: Rows, mask: Mask | None = None,
                      bounds: Bounds | None = None) -> DiffMetrics | None:
    if not _same_dimensions(left, right):
        return None

    width, height = len(left[0]), len(left)
    x0, y0, x1, y1 = bounds or (0, 0, width, height)
    x0, x1 = max(0, x0), min(width, x1)
    y0, y1 = max(0, y0), min(height, y1)
    if x0 >= x1 or y0 >= y1:
        return None

    if _np is not None:
        window = (slice(y0, y1), slice(x0, x1))
        delta = _np.abs(_as_array(left, _np.int16)[window]
                        - _as_array(right, _np.int16)[window]).sum(axis=2)
        if mask is not None:
            delta = delta[~_as_array(mask, bool)[window]]
        compared = int(delta.size)
        if not compared:
            return None
        differing = int((delta > PIXEL_DIFF_THRESHOLD).sum())
        error = int(delta.sum())
        return DiffMetrics(differing / compared, error / (compared * 3 * 255),
                           compared, differing)

    compared = differing = error = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if mask is not None and mask[y][x]:
                continue
            delta = sum(abs(a - b) for a, b in zip(left[y][x], right[y][x]))
            error += delta
            differing += delta > PIXEL_DIFF_THRESHOLD
            compared += 1
    if not compared:
        return None
    return DiffMetrics(
        differing / compared,
        error / (compared * 3 * 255),
        compared,
        differing,
    )


def visual_metrics(left: Rows, right: Rows) -> tuple[float, float] | None:
    """Return thresholded mismatch ratio and normalized mean absolute error.

    This is advisory: anti-aliasing, system chrome, and intentionally replaced
    assets make a pixel score insufficient on its own. It is only meaningful
    when both captures were rendered at the same pixel dimensions.
    """
    metrics = _detailed_metrics(left, right)
    return None if metrics is None else (metrics.mismatch, metrics.mae)


def _grayscale(rows: Rows) -> object:
    """Rec.601 luma. SSIM is defined on one channel, not three.

    int16, not float64, deliberately: that is the dtype `_detailed_metrics`
    caches, so asking for it here reuses that array instead of converting 2.7M
    tuples a second time. Measured on a 1124x2436 pair, the redundant
    conversion was 8 of the 8.4 seconds an alignment search cost. The
    multiplications below promote to float64 anyway, so the arithmetic is
    unchanged.
    """
    if _np is not None:
        array = _as_array(rows, _np.int16)
        return (array[:, :, 0] * 0.299 + array[:, :, 1] * 0.587 + array[:, :, 2] * 0.114)
    return [[(pixel[0] * 299 + pixel[1] * 587 + pixel[2] * 114) / 1000.0 for pixel in row]
            for row in rows]


def structural_similarity(left: Rows, right: Rows,
                          mask: Mask | None = None) -> tuple[float, int] | None:
    """Mean SSIM over 8x8 luma windows, and how many windows it averaged.

    A window that touches a mask is dropped whole rather than partially
    compared — a half-excluded window measures the boundary, not the screen.
    Returns None when nothing is left to average, which is the same "this screen
    is unverified" state the pixel metrics report.
    """
    if not _same_dimensions(left, right):
        return None
    height = (len(left) // SSIM_WINDOW) * SSIM_WINDOW
    width = (len(left[0]) // SSIM_WINDOW) * SSIM_WINDOW
    if height == 0 or width == 0:
        return None

    if _np is not None:
        def windows(rows):
            grey = _grayscale(rows)[:height, :width]
            return (grey.reshape(height // SSIM_WINDOW, SSIM_WINDOW,
                                 width // SSIM_WINDOW, SSIM_WINDOW)
                    .transpose(0, 2, 1, 3).reshape(-1, SSIM_WINDOW * SSIM_WINDOW))

        left_windows, right_windows = windows(left), windows(right)
        keep = _np.ones(left_windows.shape[0], dtype=bool)
        if mask is not None:
            excluded = (_as_array(mask, bool)[:height, :width]
                        .reshape(height // SSIM_WINDOW, SSIM_WINDOW,
                                 width // SSIM_WINDOW, SSIM_WINDOW)
                        .transpose(0, 2, 1, 3).reshape(-1, SSIM_WINDOW * SSIM_WINDOW))
            keep = ~excluded.any(axis=1)
        left_windows, right_windows = left_windows[keep], right_windows[keep]
        if not left_windows.shape[0]:
            return None
        mean_left = left_windows.mean(axis=1)
        mean_right = right_windows.mean(axis=1)
        var_left = left_windows.var(axis=1)
        var_right = right_windows.var(axis=1)
        covariance = ((left_windows - mean_left[:, None])
                      * (right_windows - mean_right[:, None])).mean(axis=1)
        scores = (((2 * mean_left * mean_right + SSIM_C1) * (2 * covariance + SSIM_C2))
                  / ((mean_left ** 2 + mean_right ** 2 + SSIM_C1)
                     * (var_left + var_right + SSIM_C2)))
        return float(scores.mean()), int(scores.size)

    grey_left, grey_right = _grayscale(left), _grayscale(right)
    total, counted = 0.0, 0
    for top in range(0, height, SSIM_WINDOW):
        for start in range(0, width, SSIM_WINDOW):
            if mask is not None and any(
                    any(mask[y][start:start + SSIM_WINDOW])
                    for y in range(top, top + SSIM_WINDOW)):
                continue
            values_left = [grey_left[y][x]
                           for y in range(top, top + SSIM_WINDOW)
                           for x in range(start, start + SSIM_WINDOW)]
            values_right = [grey_right[y][x]
                            for y in range(top, top + SSIM_WINDOW)
                            for x in range(start, start + SSIM_WINDOW)]
            size = len(values_left)
            mean_left = sum(values_left) / size
            mean_right = sum(values_right) / size
            var_left = sum((value - mean_left) ** 2 for value in values_left) / size
            var_right = sum((value - mean_right) ** 2 for value in values_right) / size
            covariance = sum((a - mean_left) * (b - mean_right)
                             for a, b in zip(values_left, values_right)) / size
            total += (((2 * mean_left * mean_right + SSIM_C1) * (2 * covariance + SSIM_C2))
                      / ((mean_left ** 2 + mean_right ** 2 + SSIM_C1)
                         * (var_left + var_right + SSIM_C2)))
            counted += 1
    return (total / counted, counted) if counted else None


def _overlap_error(grey_left: object, grey_right: object,
                   dx: int, dy: int, step: int) -> float | None:
    """Mean absolute luma error over the region the two share at offset (dx, dy).

    Only the overlap is scored, sampled every `step` pixels. Padding the edges
    instead would let a large shift win by comparing invented pixels.
    """
    height, width = len(grey_left), len(grey_left[0])
    y0, y1 = max(0, dy), min(height, height + dy)
    x0, x1 = max(0, dx), min(width, width + dx)
    if y1 - y0 < SSIM_WINDOW or x1 - x0 < SSIM_WINDOW:
        return None
    if _np is not None:
        left_window = grey_left[y0:y1:step, x0:x1:step]
        right_window = grey_right[y0 - dy:y1 - dy:step, x0 - dx:x1 - dx:step]
        return float(_np.abs(left_window - right_window).mean())
    total, counted = 0.0, 0
    for y in range(y0, y1, step):
        row_left, row_right = grey_left[y], grey_right[y - dy]
        for x in range(x0, x1, step):
            total += abs(row_left[x] - row_right[x - dx])
            counted += 1
    return total / counted if counted else None


def _sampling_step(width: int, height: int) -> int:
    """A stride that keeps one evaluation near `_ALIGN_SAMPLE_TARGET` pixels.

    Cost is (2*max_shift+1)^2 evaluations, so the per-evaluation cost is what
    has to stay flat as the screen grows. A 1124x2436 capture samples every
    11th pixel; a small fixture samples every one.
    """
    return max(1, int(math.sqrt(width * height / _ALIGN_SAMPLE_TARGET)))


def best_offset(left: Rows, right: Rows, max_shift: int,
                step: int | None = None) -> tuple[int, int] | None:
    """The (dx, dy) that best puts `right` on top of `left`.

    A reproduction that is correct but sits two points low differs in almost
    every pixel, and diffing it before alignment reports a broken screen. This
    finds the translation and nothing else — a rotation or a scale is a real
    difference and must stay visible.

    Cost grows as the square of `max_shift`, so callers keep it small.
    """
    if max_shift <= 0 or not _same_dimensions(left, right):
        return None
    if step is None:
        step = _sampling_step(len(left[0]), len(left))
    grey_left, grey_right = _grayscale(left), _grayscale(right)
    best, best_error = (0, 0), _overlap_error(grey_left, grey_right, 0, 0, step)
    if best_error is None:
        return None
    # Every offset in the box, not a coarse grid refined locally: a coarse grid
    # that steps over the true offset lands in noise, and refining around noise
    # searches the wrong neighbourhood entirely. Measured on a shifted
    # white-noise pair, the coarse version reported dx=4 for a dx=-3 shift.
    # The box is what bounds the cost, so `--align` should stay small.
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            error = _overlap_error(grey_left, grey_right, dx, dy, step)
            if error is not None and error < best_error:
                best, best_error = (dx, dy), error
    if step > 1:
        # The subsampled pass can prefer a neighbour of the true offset, so the
        # winner's neighbours are re-scored on a finer grid. Only nine of them,
        # which is what keeps this affordable. The winner's own error is
        # re-measured on that same finer grid first — errors from two different
        # sample grids are not comparable to each other.
        fine = max(1, step // 4)
        best_error = _overlap_error(grey_left, grey_right, best[0], best[1], fine)
        if best_error is None:
            return best
        for dy in range(best[1] - 1, best[1] + 2):
            for dx in range(best[0] - 1, best[0] + 2):
                if abs(dx) > max_shift or abs(dy) > max_shift:
                    continue
                error = _overlap_error(grey_left, grey_right, dx, dy, fine)
                if error is not None and error < best_error:
                    best, best_error = (dx, dy), error
    return best


def shift_rows(rows: Rows, dx: int, dy: int) -> Rows:
    """Translate by (dx, dy), repeating the edge pixel where nothing exists."""
    if dx == 0 and dy == 0:
        return rows
    height, width = len(rows), len(rows[0])
    if _np is not None:
        # int16 for the same cache-sharing reason as `_grayscale`; every
        # consumer of the shifted result either wants int16 or re-casts anyway.
        pixels = _as_array(rows, _np.int16)
        ys = _np.clip(_np.arange(height) - dy, 0, height - 1)
        xs = _np.clip(_np.arange(width) - dx, 0, width - 1)
        return pixels[ys][:, xs]
    return [[rows[min(height - 1, max(0, y - dy))][min(width - 1, max(0, x - dx))]
             for x in range(width)] for y in range(height)]


def _parse_mask(value: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("mask must be x,y,w,h") from exc
    if len(values) != 4 or not all(math.isfinite(number) for number in values):
        raise argparse.ArgumentTypeError("mask must be four finite numbers: x,y,w,h")
    if values[2] <= 0 or values[3] <= 0:
        raise argparse.ArgumentTypeError("mask width and height must be positive")
    return values


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="device_compare.py",
        description="Write an unmodified side-by-side clone comparison and advisory metrics.",
    )
    parser.add_argument("original")
    parser.add_argument("rendered")
    parser.add_argument("output")
    parser.add_argument("--measure", metavar="SCREEN.JSON",
                        help="report advisory metrics for measured element frames")
    parser.add_argument("--heatmap", metavar="OUT.PNG",
                        help="write a same-size pixel difference heatmap")
    parser.add_argument("--mask", action="append", default=[], type=_parse_mask,
                        metavar="x,y,w,h", help="exclude a pixel rectangle from advisory metrics")
    parser.add_argument("--mask-system-chrome", action="store_true",
                        help="explicitly exclude standard top and bottom volatile system chrome")
    parser.add_argument("--max-mismatch", metavar="RATIO", type=float, default=None,
                        help="fail (exit 1) when the thresholded mismatch ratio exceeds "
                             "RATIO. Without it the visual score stays advisory, which is "
                             "correct for one-off diagnosis and wrong for a gate: "
                             "clone_run.sh polish passes this so a reproduction that does "
                             "not look like the original cannot report success.")
    parser.add_argument("--mask-assets", metavar="MANIFEST.JSON",
                        help="exclude every capture crop this screen draws, so the score "
                             "measures the pixels the reproduction actually draws. A crop is "
                             "cut from the SAME original this compares against, so its region "
                             "is ~0%% mismatch by construction and flatters the total.")
    parser.add_argument("--exclusions", metavar="REGIONS.JSON",
                        help="exclude the pixel rectangles listed in a JSON file "
                             '{"regions":[{"x":..,"y":..,"width":..,"height":..,"reason":".."}]}. '
                             "This is where content that is volatile by nature goes — a clock, "
                             "an unread badge, a feed that reorders — so its noise stops "
                             "drowning the signal. Each region should carry a reason.")
    parser.add_argument("--align", metavar="PX", type=int, default=0,
                        help="search +/-PX for the translation that best lines the "
                             "reproduction up with the original before measuring, and report "
                             "it. A screen that is right but sits two points low differs in "
                             "almost every pixel; without this the score says it is broken. "
                             "The offset found is itself a finding — a non-zero one means a "
                             "systematic inset is wrong.")
    parser.add_argument("--max-asset-coverage", metavar="RATIO", type=float,
                        default=MAX_ASSET_COVERAGE,
                        help="fail (exit 1, only when --max-mismatch is passed) when capture "
                             "crops cover more than RATIO of the frame. A crop is an asset; a "
                             "crop the size of the screen is a photograph of the original "
                             f"standing in for a reproduction. Default {MAX_ASSET_COVERAGE}.")
    parser.add_argument("--score-log", metavar="SCORES.JSONL",
                        help="append one JSON line of this run's numbers, so a screen getting "
                             "worse is visible as a fall instead of as a number somebody has "
                             "to remember")
    parser.add_argument("--label", metavar="NAME",
                        help="name this screen in --score-log (defaults to the original's "
                             "file stem)")
    return parser


def _rect_bounds(rect: tuple[float, float, float, float], width: int, height: int,
                 scale_x: float = 1.0, scale_y: float | None = None) -> Bounds | None:
    scale_y = scale_x if scale_y is None else scale_y
    x, y, region_width, region_height = rect
    values = (x, y, region_width, region_height, scale_x, scale_y)
    if (not all(math.isfinite(value) for value in values)
            or region_width <= 0 or region_height <= 0 or scale_x <= 0 or scale_y <= 0):
        return None
    x0 = max(0, math.floor(x * scale_x))
    y0 = max(0, math.floor(y * scale_y))
    x1 = min(width, math.ceil((x + region_width) * scale_x))
    y1 = min(height, math.ceil((y + region_height) * scale_y))
    return None if x0 >= x1 or y0 >= y1 else (x0, y0, x1, y1)


def _asset_bounds(manifest_path: str, measure_path: str | None,
                  width: int, height: int) -> list[Bounds]:
    """Pixel rectangles of the capture crops drawn on this screen."""
    try:
        entries = json.loads(Path(manifest_path).read_text(encoding="utf-8")).get("assets") or []
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        print(f"WARN: asset masking skipped — cannot read {manifest_path}: {exc}",
              file=sys.stderr)
        return []
    stem = Path(measure_path).stem if measure_path else None
    bounds: list[Bounds] = []
    for entry in entries:
        if stem and Path(str(entry.get("sourceMeasurement") or "")).stem != stem:
            continue
        box = entry.get("pixelBounds") or {}
        try:
            rect = (float(box["x"]), float(box["y"]),
                    float(box["width"]), float(box["height"]))
        except (KeyError, TypeError, ValueError):
            continue
        resolved = _rect_bounds(rect, width, height)
        if resolved is not None:
            bounds.append(resolved)
    return bounds


def _exclusion_bounds(path: str, width: int, height: int) -> list[Bounds]:
    """Pixel rectangles a person declared volatile, with their reasons echoed.

    Read loudly: an exclusions file that silently does nothing is worse than no
    exclusions file, because the score then looks like it accounted for the
    clock and did not.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        regions = document.get("regions") if isinstance(document, dict) else document
        if not isinstance(regions, list):
            raise ValueError("expected a 'regions' list")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, AttributeError) as exc:
        print(f"WARN: exclusions skipped — cannot read {path}: {exc}", file=sys.stderr)
        return []
    bounds: list[Bounds] = []
    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            print(f"WARN: exclusion {index} skipped — not an object", file=sys.stderr)
            continue
        try:
            rect = (float(region["x"]), float(region["y"]),
                    float(region["width"]), float(region["height"]))
        except (KeyError, TypeError, ValueError):
            print(f"WARN: exclusion {index} skipped — needs numeric x, y, width, height",
                  file=sys.stderr)
            continue
        resolved = _rect_bounds(rect, width, height)
        if resolved is None:
            print(f"WARN: exclusion {index} skipped — rectangle is outside image bounds",
                  file=sys.stderr)
            continue
        bounds.append(resolved)
        reason = str(region.get("reason") or "no reason given")
        x0, y0, x1, y1 = resolved
        print(f"INFO: exclusion {index} — frame_px={x0},{y0},{x1 - x0},{y1 - y0}: {reason}",
              file=sys.stderr)
    return bounds


def _append_score(path: str, record: dict[str, object]) -> None:
    """Append one JSON line. A failed write must not fail the comparison."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        print(f"WARN: score not recorded in {path}: {exc}", file=sys.stderr)
        return
    print(f"INFO: score recorded in {path}", file=sys.stderr)


def _system_chrome_bounds(width: int, height: int) -> list[Bounds]:
    """Return conservative status-bar and home-indicator bands in screenshot pixels."""
    top = max(1, math.ceil(height * 0.07))
    bottom = max(1, math.ceil(height * 0.05))
    return [(0, 0, width, min(height, top)),
            (0, max(0, height - bottom), width, height)]


def _mask_rows(width: int, height: int, bounds: list[Bounds]) -> tuple[Mask | None, int]:
    if not bounds:
        return None, 0
    mask = [bytearray(width) for _ in range(height)]
    for x0, y0, x1, y1 in bounds:
        fill = b"\x01" * (x1 - x0)
        for y in range(y0, y1):
            mask[y][x0:x1] = fill
    return mask, sum(sum(row) for row in mask)


def _heatmap(left: Rows, right: Rows, mask: Mask | None) -> Rows:
    maximum = 3 * 255 - PIXEL_DIFF_THRESHOLD
    if _np is not None:
        delta = _np.abs(_as_array(left, _np.int16)
                        - _as_array(right, _np.int16)).sum(axis=2)
        intensity = (delta - PIXEL_DIFF_THRESHOLD) / maximum
        hot = intensity > 0.5
        red = _np.where(hot, 255,
                        _np.minimum(255, (intensity * 2 * 255 + 0.5).astype(_np.int32)))
        green = _np.where(hot,
                          _np.maximum(0, ((1 - intensity) * 2 * 255 + 0.5).astype(_np.int32)),
                          red)
        out = _np.zeros(delta.shape + (3,), dtype=_np.uint8)
        out[:, :, 0] = red
        out[:, :, 1] = green
        out[delta <= PIXEL_DIFF_THRESHOLD] = (0, 0, 0)
        if mask is not None:
            out[_as_array(mask, bool)] = MASKED_RGB
        return out
    rows: Rows = []
    for y, (left_row, right_row) in enumerate(zip(left, right)):
        output_row: list[RGB] = []
        for x, (a, b) in enumerate(zip(left_row, right_row)):
            if mask is not None and mask[y][x]:
                output_row.append(MASKED_RGB)
                continue
            delta = sum(abs(left_channel - right_channel)
                        for left_channel, right_channel in zip(a, b))
            if delta <= PIXEL_DIFF_THRESHOLD:
                output_row.append((0, 0, 0))
                continue
            intensity = (delta - PIXEL_DIFF_THRESHOLD) / maximum
            if intensity <= 0.5:
                value = min(255, int(intensity * 2 * 255 + 0.5))
                output_row.append((value, value, 0))
            else:
                green = max(0, int((1 - intensity) * 2 * 255 + 0.5))
                output_row.append((255, green, 0))
        rows.append(output_row)
    return rows


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _point_scale(measurement: dict[str, object]) -> tuple[float, float] | None:
    screen = measurement.get("screen")
    if not isinstance(screen, dict):
        return None
    scale = _number(screen.get("scale"))
    if scale is not None and scale > 0:
        return scale, scale

    points, pixels = screen.get("points"), screen.get("pixels")
    if not isinstance(points, dict) or not isinstance(pixels, dict):
        return None
    point_width, point_height = _number(points.get("width")), _number(points.get("height"))
    pixel_width, pixel_height = _number(pixels.get("width")), _number(pixels.get("height"))
    if (point_width is None or point_height is None or pixel_width is None or pixel_height is None
            or min(point_width, point_height, pixel_width, pixel_height) <= 0):
        return None
    return pixel_width / point_width, pixel_height / point_height


def _region_level(metrics: DiffMetrics) -> str:
    if metrics.mismatch >= REGION_HIGH_MISMATCH or metrics.mae >= REGION_HIGH_MAE:
        return "high"
    if metrics.mismatch >= REGION_MEDIUM_MISMATCH or metrics.mae >= REGION_MEDIUM_MAE:
        return "medium"
    return "low"


def _element_description(index: int, element: object) -> str:
    if not isinstance(element, dict):
        return f"element {index} role=unknown label=\"\""
    role = str(element.get("role") or "unknown")
    label = " ".join(str(element.get("label") or "").split())
    return f"element {index} role={role} label={json.dumps(label, ensure_ascii=False)}"


def _report_regions(measurement: dict[str, object], left: Rows, right: Rows,
                    mask: Mask | None) -> dict[str, int] | None:
    """Score every measured element frame, and return how many landed where.

    This is the block-matching half of the comparison: the measurement already
    pairs each element with its exact frame, so the blocks are matched by
    construction and no OCR guesswork is needed to find them.
    """
    scale = _point_scale(measurement)
    if scale is None:
        print("WARN: regional diff metrics skipped — measurement has no valid point-to-pixel scale",
              file=sys.stderr)
        return None
    elements = measurement.get("elements")
    if not isinstance(elements, list):
        print("WARN: regional diff metrics skipped — measurement has no elements list",
              file=sys.stderr)
        return None

    width, height = len(left[0]), len(left)
    counts = {"high": 0, "medium": 0, "low": 0}
    metrics_by_bounds: dict[Bounds, DiffMetrics | None] = {}
    reported = 0
    for index, element in enumerate(elements):
        description = _element_description(index, element)
        frame = element.get("frame") if isinstance(element, dict) else None
        if not isinstance(frame, dict):
            print(f"WARN: region advisory skipped {description} — invalid frame", file=sys.stderr)
            continue
        frame_x = _number(frame.get("x"))
        frame_y = _number(frame.get("y"))
        frame_width = _number(frame.get("width"))
        frame_height = _number(frame.get("height"))
        if any(value is None for value in (frame_x, frame_y, frame_width, frame_height)):
            print(f"WARN: region advisory skipped {description} — invalid frame", file=sys.stderr)
            continue
        assert frame_x is not None and frame_y is not None
        assert frame_width is not None and frame_height is not None
        rect = (frame_x, frame_y, frame_width, frame_height)
        bounds = _rect_bounds(rect, width, height, scale[0], scale[1])
        if bounds is None:
            print(f"INFO: region advisory skipped {description} — frame is outside image bounds",
                  file=sys.stderr)
            continue
        if bounds not in metrics_by_bounds:
            metrics_by_bounds[bounds] = _detailed_metrics(left, right, mask, bounds)
        metrics = metrics_by_bounds[bounds]
        if metrics is None:
            print(f"INFO: region advisory skipped {description} — no unmasked pixels",
                  file=sys.stderr)
            continue
        level = _region_level(metrics)
        counts[level] += 1
        reported += 1
        x0, y0, x1, y1 = bounds
        print(
            f"INFO: region advisory [{level}] {description} "
            f"frame_px={x0},{y0},{x1 - x0},{y1 - y0} — "
            f"mismatch {metrics.mismatch:.2%}, mean absolute error {metrics.mae:.2%}",
            file=sys.stderr,
        )
    print(f"INFO: regional diff advisory — {reported} regions: high {counts['high']}, "
          f"medium {counts['medium']}, low {counts['low']}", file=sys.stderr)
    if reported:
        print(f"INFO: region score — {counts['low'] / reported:.2%} of {reported} measured "
              "element frames reproduced at low difference", file=sys.stderr)
    return counts


def main(argv: list[str]) -> int:
    gate_failure: str | None = None
    try:
        args = _parser().parse_args(argv[1:])
    except SystemExit as exc:
        return int(exc.code)
    try:
        left, right = rows_rgb(PNG(args.original)), rows_rgb(PNG(args.rendered))
    except (OSError, ValueError, zlib.error) as exc:
        print(f"ERROR: cannot read images: {exc}", file=sys.stderr)
        return 1

    # A real iPhone 12 mini and its simulator disagree about pixels while agreeing
    # about points: WebDriverAgent returns the 1124x2436 render buffer, simctl
    # returns the 1080x2340 native panel. Both are the same 375x812 points, so
    # refusing to compare them threw away every quantitative metric on that
    # device — measured 2026-08-22, all 60 metric runs skipped. Resample when the
    # shapes agree; only a genuine aspect mismatch is a real mismatch.
    # Kept before any resample: the aspect check below must judge what was
    # actually rendered, not what we normalized it to.
    rendered_shape = (len(right[0]), len(right)) if right and right[0] else (0, 0)
    if not _same_dimensions(left, right) and left and right and left[0] and right[0]:
        left_aspect = len(left[0]) / len(left)
        right_aspect = len(right[0]) / len(right)
        if abs(left_aspect - right_aspect) <= 0.01:
            print(f"INFO: reproduction resampled {len(right[0])}x{len(right)} -> "
                  f"{len(left[0])}x{len(left)} for metrics — same aspect, different "
                  "capture scale (device render buffer vs simulator panel)",
                  file=sys.stderr)
            right = scale_to(right, len(left[0]), len(left))

    # Alignment before measurement, never after: a reproduction that is correct
    # but sits a few pixels off differs in almost every pixel, and a score taken
    # before the shift is found describes the shift, not the screen. The offset
    # is reported because it is itself a finding.
    offset: tuple[int, int] | None = None
    if args.align > 0:
        if not _same_dimensions(left, right):
            print("INFO: alignment skipped — original and reproduction must have the same "
                  "pixel dimensions", file=sys.stderr)
        else:
            offset = best_offset(left, right, args.align)
            if offset is None:
                print("INFO: alignment skipped — nothing large enough to align", file=sys.stderr)
            elif offset == (0, 0):
                print(f"INFO: alignment searched +/-{args.align}px — already aligned",
                      file=sys.stderr)
            else:
                right = shift_rows(right, offset[0], offset[1])
                print(f"INFO: reproduction shifted dx={offset[0]} dy={offset[1]} to align "
                      f"(searched +/-{args.align}px). A non-zero offset is a finding: some "
                      "inset or safe-area value is systematically wrong.", file=sys.stderr)

    same_size = _same_dimensions(left, right)
    mask: Mask | None = None
    metrics: DiffMetrics | None = None
    ssim: tuple[float, int] | None = None
    region_counts: dict[str, int] | None = None
    asset_coverage = 0.0
    if not same_size:
        print("INFO: visual diff metrics skipped — original and reproduction must have "
              "the same pixel dimensions", file=sys.stderr)
        print("INFO: regional diff metrics skipped — original and reproduction must have "
              "the same pixel dimensions", file=sys.stderr)
        if args.heatmap:
            print("INFO: diff heatmap skipped — original and reproduction must have "
                  "the same pixel dimensions", file=sys.stderr)
        if args.mask or args.mask_system_chrome:
            print("INFO: masks not applied — same-size metrics are unavailable", file=sys.stderr)
    else:
        width, height = len(left[0]), len(left)
        mask_bounds: list[Bounds] = []
        for index, rect in enumerate(args.mask, start=1):
            bounds = _rect_bounds(rect, width, height)
            if bounds is None:
                print(f"WARN: custom mask {index} skipped — rectangle is outside image bounds",
                      file=sys.stderr)
            else:
                mask_bounds.append(bounds)
                x0, y0, x1, y1 = bounds
                print(f"INFO: custom mask {index} requested — "
                      f"frame_px={x0},{y0},{x1 - x0},{y1 - y0}", file=sys.stderr)
        if args.mask_system_chrome:
            chrome = _system_chrome_bounds(width, height)
            mask_bounds.extend(chrome)
            top, bottom = chrome
            print("INFO: system chrome masking explicitly requested — "
                  f"status_px={top[0]},{top[1]},{top[2] - top[0]},{top[3] - top[1]} "
                  f"home_px={bottom[0]},{bottom[1]},{bottom[2] - bottom[0]},{bottom[3] - bottom[1]}",
                  file=sys.stderr)
        if args.exclusions:
            mask_bounds.extend(_exclusion_bounds(args.exclusions, width, height))
        if args.mask_assets:
            assets = _asset_bounds(args.mask_assets, args.measure, width, height)
            mask_bounds.extend(assets)
            covered = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in assets)
            asset_coverage = covered / (width * height)
            print(f"INFO: capture crops excluded — {len(assets)} region(s), "
                  f"{asset_coverage:.1%} of the screen. What remains is the "
                  "part the reproduction draws itself.", file=sys.stderr)
        mask, masked_pixels = _mask_rows(width, height, mask_bounds)
        if mask_bounds:
            print(f"INFO: mask advisory — {masked_pixels}/{width * height} pixels excluded; "
                  "side-by-side evidence remains unmasked", file=sys.stderr)

        metrics = _detailed_metrics(left, right, mask)
        ssim = structural_similarity(left, right, mask)
        # "advisory" stops being true the moment something gates on the number,
        # and a log line that misreports its own authority is how this check
        # went unnoticed for as long as it did.
        armed = args.max_mismatch is not None
        if metrics is None:
            print("INFO: visual diff skipped — no unmasked pixels", file=sys.stderr)
            if armed:
                # Masking is what makes the score meaningful; masking everything
                # makes it meaningless. Passing here would report an unverified
                # screen as a correct one.
                gate_failure = ("nothing was compared — no unmasked pixels remain, so this "
                                "screen is unverified, not reproduced")
        else:
            print(f"INFO: visual diff {'gate' if armed else 'advisory'} — "
                  f"mismatch {metrics.mismatch:.2%}, "
                  f"mean absolute error {metrics.mae:.2%}"
                  + (f", bound {args.max_mismatch:.2%}" if armed else ""), file=sys.stderr)
            if armed and metrics.mismatch > args.max_mismatch:
                # Recorded, not returned: the side-by-side written below is the
                # evidence a person needs to act on this failure, so it is
                # produced first and the verdict is applied at the end.
                gate_failure = (f"visual mismatch {metrics.mismatch:.2%} exceeds the "
                                f"{args.max_mismatch:.2%} bound — the reproduction does not "
                                f"look like the original")

        if ssim is None:
            print("INFO: structural similarity skipped — no unmasked 8x8 window remains",
                  file=sys.stderr)
        else:
            print(f"INFO: structural similarity — SSIM {ssim[0]:.4f} over {ssim[1]} "
                  "window(s). Unlike mismatch this survives anti-aliasing and font "
                  "hinting, and falls when content is in the wrong place or absent.",
                  file=sys.stderr)

        # A crop is an asset. A crop the size of the screen is the original
        # itself, pasted in — and every pixel score then measures where it was
        # pasted. The bound is only armed alongside the mismatch gate, because
        # that is the run whose verdict something depends on.
        if args.mask_assets and asset_coverage > args.max_asset_coverage:
            message = (f"capture crops cover {asset_coverage:.1%} of the screen, past the "
                       f"{args.max_asset_coverage:.0%} bound — this is the original shown as "
                       "an image, not a reproduction that draws itself. Crops belong in asset "
                       "slots (icons, illustrations), never as a stand-in for layout.")
            if armed:
                gate_failure = gate_failure or message
            else:
                print(f"WARN: {message}", file=sys.stderr)

        if args.heatmap:
            try:
                write_png(args.heatmap, _heatmap(left, right, mask))
            except OSError as exc:
                print(f"ERROR: cannot write heatmap: {exc}", file=sys.stderr)
                return 1
            print(f"OK: wrote advisory diff heatmap {args.heatmap}", file=sys.stderr)

        if args.measure:
            try:
                measurement = json.loads(Path(args.measure).read_text(encoding="utf-8"))
                if not isinstance(measurement, dict):
                    raise ValueError("root must be an object")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                print(f"WARN: regional diff metrics skipped — cannot read measurement: {exc}",
                      file=sys.stderr)
            else:
                region_counts = _report_regions(measurement, left, right, mask)

    # Same aspect ratio is not the same layout: reproducing 375x812 numbers on a
    # 402x874 simulator shifts everything, and scaling the screenshot afterwards
    # hides it. Say so — the fix is to render on a matching device.
    la = len(left[0]) / len(left)
    ra = rendered_shape[0] / rendered_shape[1] if rendered_shape[1] else la
    if abs(la - ra) > 0.005:
        print(f"WARN: aspect mismatch — original {len(left[0])}x{len(left)}, "
              f"reproduction {rendered_shape[0]}x{rendered_shape[1]}. Render on a simulator "
              "whose logical size matches the captured device, or the comparison is "
              "misleading.", file=sys.stderr)

    height = min(len(left), len(right))
    scaled_left = scale_to(left, round(len(left[0]) * height / len(left)), height)
    scaled_right = scale_to(right, round(len(right[0]) * height / len(right)), height)
    try:
        write_png(args.output,
                  join_side_by_side(scaled_left, scaled_right, DIVIDER, DIVIDER_RGB))
    except OSError as exc:
        print(f"ERROR: cannot write comparison: {exc}", file=sys.stderr)
        return 1
    print(f"OK: wrote {args.output} ({len(scaled_left[0])}+{len(scaled_right[0])}px wide, "
          f"{height}px tall) — original on the left, reproduction on the right", file=sys.stderr)

    # Written for every run, passing or failing. A log that only records
    # successes cannot show a regression, which is the one thing it is for.
    if args.score_log:
        reported = sum(region_counts.values()) if region_counts else 0
        _append_score(args.score_log, {
            "label": args.label or Path(args.original).stem,
            "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "comparable": same_size,
            "mismatch": None if metrics is None else round(metrics.mismatch, 6),
            "meanAbsoluteError": None if metrics is None else round(metrics.mae, 6),
            "ssim": None if ssim is None else round(ssim[0], 6),
            "ssimWindows": None if ssim is None else ssim[1],
            "regionScore": None if not reported else round(region_counts["low"] / reported, 6),
            "regions": region_counts,
            "assetCoverage": round(asset_coverage, 6),
            "alignment": None if offset is None else {"dx": offset[0], "dy": offset[1]},
            "gated": args.max_mismatch is not None,
            "passed": gate_failure is None,
        })

    if gate_failure is not None:
        print(f"ERROR: {gate_failure}. Compare {args.output} and fix the screen, "
              "or raise --max-mismatch only with a reason.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
