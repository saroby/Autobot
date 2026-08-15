#!/usr/bin/env python3
"""device_compare.py — put the original and the reproduction side by side.

`/autobot:clone` Step 6 refuses to call a screen done until a human can see both
at once. Matching numbers are not evidence: a view can measure right and still
look wrong.

    device_compare.py <original.png> <rendered.png> <out.png>
        [--measure screen.json] [--heatmap diff.png]
        [--mask x,y,w,h ...] [--mask-system-chrome]

The two are rarely the same pixel size (a 12 mini capture next to a 17 Pro
simulator), so the taller one is scaled to the other's height by nearest
neighbour before they are joined with a divider. stdlib only — the PNG reader is
shared with device_measure, and the writer is a few lines of zlib.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
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
    return [[rows[min(src_h - 1, y * src_h // height)][min(src_w - 1, x * src_w // width)]
             for x in range(width)] for y in range(height)]


def write_png(path: str, rows: Rows) -> None:
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
    return bool(left and right and left[0] and right[0]
                and len(left) == len(right) and len(left[0]) == len(right[0]))


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
    rows: Rows = []
    maximum = 3 * 255 - PIXEL_DIFF_THRESHOLD
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
                    mask: Mask | None) -> None:
    scale = _point_scale(measurement)
    if scale is None:
        print("WARN: regional diff metrics skipped — measurement has no valid point-to-pixel scale",
              file=sys.stderr)
        return
    elements = measurement.get("elements")
    if not isinstance(elements, list):
        print("WARN: regional diff metrics skipped — measurement has no elements list",
              file=sys.stderr)
        return

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


def main(argv: list[str]) -> int:
    try:
        args = _parser().parse_args(argv[1:])
    except SystemExit as exc:
        return int(exc.code)
    try:
        left, right = rows_rgb(PNG(args.original)), rows_rgb(PNG(args.rendered))
    except (OSError, ValueError, zlib.error) as exc:
        print(f"ERROR: cannot read images: {exc}", file=sys.stderr)
        return 1

    same_size = _same_dimensions(left, right)
    mask: Mask | None = None
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
        mask, masked_pixels = _mask_rows(width, height, mask_bounds)
        if mask_bounds:
            print(f"INFO: mask advisory — {masked_pixels}/{width * height} pixels excluded; "
                  "side-by-side evidence remains unmasked", file=sys.stderr)

        metrics = _detailed_metrics(left, right, mask)
        if metrics is None:
            print("INFO: visual diff advisory skipped — no unmasked pixels", file=sys.stderr)
        else:
            print(f"INFO: visual diff advisory — mismatch {metrics.mismatch:.2%}, "
                  f"mean absolute error {metrics.mae:.2%}", file=sys.stderr)

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
                _report_regions(measurement, left, right, mask)

    # Same aspect ratio is not the same layout: reproducing 375x812 numbers on a
    # 402x874 simulator shifts everything, and scaling the screenshot afterwards
    # hides it. Say so — the fix is to render on a matching device.
    la, ra = len(left[0]) / len(left), len(right[0]) / len(right)
    if abs(la - ra) > 0.005:
        print(f"WARN: aspect mismatch — original {len(left[0])}x{len(left)}, "
              f"reproduction {len(right[0])}x{len(right)}. Render on a simulator whose "
              "logical size matches the captured device, or the comparison is misleading.",
              file=sys.stderr)

    height = min(len(left), len(right))
    scaled_left = scale_to(left, round(len(left[0]) * height / len(left)), height)
    scaled_right = scale_to(right, round(len(right[0]) * height / len(right)), height)
    gap = [DIVIDER_RGB] * DIVIDER
    try:
        write_png(args.output, [scaled_left[y] + gap + scaled_right[y] for y in range(height)])
    except OSError as exc:
        print(f"ERROR: cannot write comparison: {exc}", file=sys.stderr)
        return 1
    print(f"OK: wrote {args.output} ({len(scaled_left[0])}+{len(scaled_right[0])}px wide, "
          f"{height}px tall) — original on the left, reproduction on the right", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
