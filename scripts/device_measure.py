#!/usr/bin/env python3
"""device_measure.py — turn one captured screen into reproduction numbers.

`/autobot:clone` reproduces screens pixel-faithfully, which means the SwiftUI it
writes must come from measurements, not from eyeballing a screenshot. This reads
the pair that `device_wda.sh screen` produces — the accessibility tree (exact
frames) and the PNG (real colors) — and emits one JSON per screen:

    device_measure.py <tree.xml|tree.json> <screen.png> > screen.json

Frames come from the tree, colors are sampled out of the PNG at each element's
own rectangle, and text style is estimated from measured glyph height and then
snapped to the nearest iOS text style. Anything that cannot be measured (binary
assets, custom font files, animation timing) is listed under "unmeasurable" so
the spec can say so instead of inventing it.

PNG decoding is stdlib-only (zlib + struct) — no Pillow, matching the repo's
no-new-dependency rule. Only the 8-bit RGB/RGBA color types Apple's screenshots
use are supported; anything else degrades to "colors unavailable", never a crash.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device_a11y  # noqa: E402  (same-directory sibling)

# iOS text styles by point size — measured glyph height is snapped to the
# nearest of these so generated code says `.headline`, not a magic number.
TEXT_STYLES = [
    ("largeTitle", 34), ("title", 28), ("title2", 22), ("title3", 20),
    ("headline", 17), ("body", 17), ("callout", 16), ("subheadline", 15),
    ("footnote", 13), ("caption", 12), ("caption2", 11),
]
# A text element's frame is taller than its glyphs by roughly this factor.
GLYPH_TO_FRAME = 1.35
# Parent marker for elements dropped as chrome — their subtree goes with them.
CHROME = -2

# Uncovered-region scan: the dominant clone failure is a wholesale MISSING
# element (DCGen, arXiv 2406.16386: 85.3% of failures), and our own chrome
# filter can drop content along with the chrome. Blocks of visibly
# non-background pixels that no measured frame covers turn that silent loss
# into a warning at measurement time instead of a human count at Step 6.
UNCOVERED_BLOCK_PX = 16     # scan granularity, in screenshot pixels
UNCOVERED_MIN_BLOCKS = 3    # smaller clusters are antialiasing/shadow specks
UNCOVERED_COLOR_DELTA = 24  # max per-channel distance still "background"
UNCOVERED_MAX_REGIONS = 10


class PNG:
    """Minimal 8-bit RGB/RGBA PNG reader: enough to sample pixels."""

    def __init__(self, path: str):
        raw = Path(path).read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG")
        idat, pos = bytearray(), 8
        self.width = self.height = self.channels = 0
        while pos < len(raw):
            (length,) = struct.unpack(">I", raw[pos:pos + 4])
            kind = raw[pos + 4:pos + 8]
            body = raw[pos + 8:pos + 8 + length]
            if kind == b"IHDR":
                self.width, self.height, depth, color = struct.unpack(">IIBB", body[:10])
                if depth != 8 or color not in (2, 6):
                    raise ValueError(f"unsupported PNG (depth={depth}, color={color})")
                self.channels = 3 if color == 2 else 4
            elif kind == b"IDAT":
                idat += body
            elif kind == b"IEND":
                break
            pos += 12 + length
        self.rows = self._unfilter(zlib.decompress(bytes(idat)))

    def _unfilter(self, data: bytes) -> list[bytearray]:
        """Undo the per-scanline filters PNG applies before compression."""
        ch, w = self.channels, self.width
        stride, rows, prev, pos = w * ch, [], bytearray(w * ch), 0
        for _ in range(self.height):
            ftype = data[pos]
            line = bytearray(data[pos + 1:pos + 1 + stride])
            pos += 1 + stride
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                if ftype == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif ftype == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif ftype == 3:
                    line[i] = (line[i] + (a + b) // 2) & 0xFF
                elif ftype == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
            rows.append(line)
            prev = line
        return rows

    def hex_at(self, x: int, y: int) -> str | None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        i = x * self.channels
        r, g, b = self.rows[y][i:i + 3]
        return f"#{r:02X}{g:02X}{b:02X}"


def _luma(hexv: str) -> float:
    r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def sample(png: PNG | None, frame: dict, scale: float, *, text: bool = False) -> dict:
    """Background (frame corners) and, for text, the actual glyph color.

    A text element's center pixel is as likely to fall between strokes as on
    them, so the foreground is taken as the pixel furthest in luminance from the
    background across a grid — that is the ink. Without this the generated code
    has no text color at all, which is not reproducible.
    """
    if png is None:
        return {}
    x, y = frame["x"] * scale, frame["y"] * scale
    w, h = frame["width"] * scale, frame["height"] * scale
    if w < 2 or h < 2:
        return {}
    corners = [
        png.hex_at(int(x + 1), int(y + 1)), png.hex_at(int(x + w - 2), int(y + 1)),
        png.hex_at(int(x + 1), int(y + h - 2)), png.hex_at(int(x + w - 2), int(y + h - 2)),
    ]
    corners = [c for c in corners if c]
    out = {}
    if corners:
        out["background"] = Counter(corners).most_common(1)[0][0]
    center = png.hex_at(int(x + w / 2), int(y + h / 2))
    if center:
        out["center"] = center
    grid = [
        png.hex_at(int(x + w * gx), int(y + h * gy))
        for gx in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
        for gy in (0.2, 0.35, 0.5, 0.65, 0.8)
    ]
    grid = [c for c in grid if c]
    if not grid:
        return out
    if text and out.get("background"):
        base = _luma(out["background"])
        ink = max(grid, key=lambda c: abs(_luma(c) - base))
        if abs(_luma(ink) - base) > 12:  # below this it is all background
            out["foreground"] = ink
    else:
        # A control's real fill is neither its corner (that is whatever sits
        # behind it) nor its center (that is the glyph): the blue circle of a
        # floating action button was lost to both. The dominant interior color is
        # the fill.
        out["fill"] = Counter(grid).most_common(1)[0][0]
    return out


def text_style(frame: dict, label: str) -> dict:
    """Estimate point size from frame height, then snap to an iOS text style.

    Height only measures glyphs on a single line. A wrapped label's frame is a
    multiple of that, which read as a 67pt "largeTitle" on a real screen — so
    explicit line breaks are divided out, and anything still larger than the
    biggest iOS style is reported as unreliable rather than guessed at.
    """
    lines = label.count("\n") + 1
    pt = frame["height"] / lines / GLYPH_TO_FRAME
    if pt > TEXT_STYLES[0][1] + 6:
        return {
            "estimatedPointSize": round(pt, 1),
            "iosTextStyle": None,
            "note": "unreliable — frame is taller than any text style; wrapped text or a container",
        }
    name, size = min(TEXT_STYLES, key=lambda s: abs(s[1] - pt))
    out = {"estimatedPointSize": round(pt, 1), "iosTextStyle": name, "styleSize": size}
    if lines > 1:
        out["lines"] = lines
    return out


def _overlap(boxes: list[dict], pos: str, size: str) -> float:
    """Mean overlap between neighbours on one axis, 0 (apart) to 1 (stacked).

    Relative to the elements' own size, not the parent's: two 80pt buttons at the
    same spot overlap fully whether the screen is 375pt or 1024pt wide.
    """
    ratios = []
    for a, b in zip(boxes, boxes[1:]):
        over = min(a[pos] + a[size], b[pos] + b[size]) - max(a[pos], b[pos])
        ratios.append(max(0.0, over) / max(min(a[size], b[size]), 1))
    return sum(ratios) / len(ratios) if ratios else 0.0


def _rgb(hexv: str) -> tuple[int, int, int]:
    return tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))


def uncovered_regions(png: PNG | None, measured: list[dict], root_frame: dict,
                      scale: float) -> list[dict]:
    """Point-space rectangles of non-background pixels no measured frame covers.

    Coarse by design: block centers on a 16px grid, clustered by adjacency.
    The same top/bottom bands device_compare masks as system chrome are skipped
    — the status bar rarely has measurable tree elements and would flag on
    every screen.
    """
    if png is None or not root_frame.get("width"):
        return []
    background = sample(png, root_frame, scale).get("background")
    if not background:
        return []
    bg = _rgb(background)
    top = max(1, math.ceil(png.height * 0.07))
    bottom_start = png.height - max(1, math.ceil(png.height * 0.05))
    # Near-full-screen containers (the AXApplication root, list wrappers) cover
    # every pixel and say nothing about content — counting them would mark the
    # whole screen "covered" and blind the scan.
    screen_area = root_frame["width"] * root_frame["height"]
    frames_px = [
        (m["frame"]["x"] * scale, m["frame"]["y"] * scale,
         (m["frame"]["x"] + m["frame"]["width"]) * scale,
         (m["frame"]["y"] + m["frame"]["height"]) * scale)
        for m in measured
        if m["frame"]["width"] * m["frame"]["height"] < 0.9 * screen_area
    ]
    block = UNCOVERED_BLOCK_PX
    grid_w = png.width // block
    grid_h = png.height // block
    flagged: set[tuple[int, int]] = set()
    for by in range(grid_h):
        cy = by * block + block // 2
        if cy < top or cy >= bottom_start:
            continue
        for bx in range(grid_w):
            cx = bx * block + block // 2
            if any(x1 <= cx < x2 and y1 <= cy < y2 for x1, y1, x2, y2 in frames_px):
                continue
            hexv = png.hex_at(cx, cy)
            if not hexv:
                continue
            pixel = _rgb(hexv)
            if max(abs(a - b) for a, b in zip(pixel, bg)) > UNCOVERED_COLOR_DELTA:
                flagged.add((bx, by))
    regions = []
    while flagged:
        stack = [flagged.pop()]
        cluster = []
        while stack:
            bx, by = stack.pop()
            cluster.append((bx, by))
            for neighbor in ((bx + 1, by), (bx - 1, by), (bx, by + 1), (bx, by - 1)):
                if neighbor in flagged:
                    flagged.remove(neighbor)
                    stack.append(neighbor)
        if len(cluster) < UNCOVERED_MIN_BLOCKS:
            continue
        xs = [bx for bx, _ in cluster]
        ys = [by for _, by in cluster]
        regions.append({
            "x": round(min(xs) * block / scale, 1),
            "y": round(min(ys) * block / scale, 1),
            "width": round((max(xs) - min(xs) + 1) * block / scale, 1),
            "height": round((max(ys) - min(ys) + 1) * block / scale, 1),
            "blocks": len(cluster),
        })
    regions.sort(key=lambda r: r["blocks"], reverse=True)
    return regions[:UNCOVERED_MAX_REGIONS]


def measure(tree: str, image: str | None) -> dict:
    els = device_a11y.load(tree)
    png, note = None, None
    if image:
        try:
            png = PNG(image)
        except (OSError, ValueError, zlib.error) as exc:
            note = f"colors unavailable: {exc}"

    root = next((e for e in els if e["role"] == "AXApplication"), None)
    bounds = root["frame"] if root else {"width": 0, "height": 0}
    # Screenshots are in pixels, the tree is in points — one scale factor links them.
    scale = round(png.width / bounds["width"], 3) if png and bounds.get("width") else 1.0

    measured, dropped = [], 0
    # Original index → index in `measured`, or the nearest KEPT ancestor when the
    # element itself was dropped. Without the ancestor fallback every child of a
    # discarded wrapper loses its parent link and layout inference collapses.
    remap: dict[int, int] = {-1: -1}
    seen: set[tuple] = set()
    for i, e in enumerate(els):
        f = e["frame"]
        parent = remap.get(e.get("parent", -1), -1)
        # A dropped wrapper hands its children up; dropped chrome does not — a
        # scroll bar's children are more scroll bar. Re-parenting them put two
        # 3pt scroll indicators among the root's cards and broke its spacing.
        if parent == CHROME:
            dropped += 1
            remap[i] = CHROME
            continue
        if f["width"] <= 0 or f["height"] <= 0 or e["visible"] is False:
            remap[i] = parent
            continue
        # Scroll bars and page controls are chrome, not content: on a real screen
        # they arrived as full-height siblings of the cards and turned the root's
        # inferred spacing into noise. Same vocabulary the tap loop already skips.
        # Checked BEFORE the duplicate rule — a chrome element that is also a
        # duplicate must still mark its subtree, or its children get promoted.
        if device_a11y.NOISE.search(e["label"] or ""):
            dropped += 1
            remap[i] = CHROME
            continue
        # WDA reports two windows for one screen, so every element arrives twice.
        # Same role, same label, same rectangle is the same thing, not a sibling.
        key = (e["role"], e["label"], f["x"], f["y"], f["width"], f["height"])
        if key in seen:
            dropped += 1
            remap[i] = parent
            continue
        seen.add(key)
        # A real screen carried 20 unlabelled full-screen AXOther wrappers. They
        # are layout plumbing with nothing to reproduce, and they drown the spec.
        if (not e["label"] and e["role"] in ("AXOther", "AXWindow")
                and f["width"] >= bounds.get("width", 0) and f["height"] >= bounds.get("height", 0)):
            dropped += 1
            remap[i] = parent
            continue
        is_text = e["role"] in ("AXStaticText", "AXTextField", "AXTextView") and e["label"]
        remap[i] = len(measured)
        item = {
            "role": e["role"],
            "label": e["label"],
            "frame": {k: round(f[k], 1) for k in ("x", "y", "width", "height")},
            "enabled": e["enabled"],
            "depth": e.get("depth"),
            "parent": parent,
        }
        colors = sample(png, f, scale, text=bool(is_text))
        if colors:
            item["colors"] = colors
        if is_text:
            item["text"] = text_style(f, e["label"])
        measured.append(item)

    # Layout: the SKILL promises stack direction and spacing, and those are only
    # derivable from the hierarchy — hence depth/parent above. Children that line
    # up on one axis and spread on the other are that axis's stack; the gaps
    # between them are the spacing the generated code should use.
    children: dict[int, list[int]] = {}
    for i, m in enumerate(measured):
        if m["parent"] >= 0:
            children.setdefault(m["parent"], []).append(i)
    for parent, kids in children.items():
        if len(kids) < 2:
            continue
        pf = measured[parent]["frame"]
        boxes = [measured[k]["frame"] for k in kids]
        # A card's own background fills its parent and therefore overlaps every
        # sibling — counting it reported a row of icon/label/count as gaps of
        # "-343". It is drawn behind, not laid out beside.
        content = [b for b in boxes
                   if b["width"] * b["height"] < 0.9 * pf["width"] * pf["height"]]
        if len(content) >= 2:
            boxes = content
        if len(boxes) < 2:
            continue
        xs = sorted(boxes, key=lambda b: b["x"])
        ys = sorted(boxes, key=lambda b: b["y"])
        x_gaps = [round(b["x"] - (a["x"] + a["width"]), 1) for a, b in zip(xs, xs[1:])]
        y_gaps = [round(b["y"] - (a["y"] + a["height"]), 1) for a, b in zip(ys, ys[1:])]
        # The stack axis is the one the siblings do NOT overlap on. Summing only
        # positive gaps (the earlier rule) called a label sitting 6pt into the
        # number above it a zstack, because "no gap" and "slight overlap" were
        # the same number. Overlap is the signal, measured against the elements'
        # own size — only when both axes are mostly overlapped is it a zstack.
        x_over = _overlap(xs, "x", "width")
        y_over = _overlap(ys, "y", "height")
        if x_over > 0.5 and y_over > 0.5:
            axis, gaps = "zstack", []
        elif y_over <= x_over:
            axis, gaps = "vstack", y_gaps
        else:
            axis, gaps = "hstack", x_gaps
        layout = {"axis": axis, "children": len(kids)}
        positive = [g for g in gaps if g > 0]
        if positive:
            layout["spacing"] = round(sum(positive) / len(positive), 1)
            layout["gaps"] = gaps
        measured[parent]["layout"] = layout

    palette = Counter()
    for m in measured:
        for hexv in m.get("colors", {}).values():
            palette[hexv] += 1

    unmeasurable = [
        "binary assets (icons, images, fonts) — sandboxed on device, not extractable",
        "exact font family — system font is assumed",
        "animation timing and easing",
        "colors behind translucency (measured value is the composited result)",
    ]
    if note:
        unmeasurable.insert(0, note)

    return {
        "source": {"tree": tree, "image": image},
        "screen": {
            "points": {"width": bounds.get("width", 0), "height": bounds.get("height", 0)},
            "pixels": {"width": png.width, "height": png.height} if png else None,
            "scale": scale,
        },
        "palette": [{"hex": h, "count": n} for h, n in palette.most_common(12)],
        "droppedWrappers": dropped,
        "elements": measured,
        "uncoveredRegions": uncovered_regions(
            png, measured, root["frame"] if root else {}, scale),
        "unmeasurable": unmeasurable,
    }


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print("ERROR: usage: device_measure.py <tree.xml|tree.json> [screen.png]", file=sys.stderr)
        return 1
    try:
        result = measure(argv[1], argv[2] if len(argv) == 3 else None)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    uncovered = result.get("uncoveredRegions") or []
    if uncovered:
        print(f"WARN: {len(uncovered)} non-background region(s) not covered by any "
              "measured element — content may have been dropped with chrome; "
              "inspect uncoveredRegions before writing the spec", file=sys.stderr)
    print(f"OK: measured {len(result['elements'])} elements, "
          f"{len(result['palette'])} colors", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
