#!/usr/bin/env python3
"""device_compare.py — put the original and the reproduction side by side.

`/autobot:clone` Step 6 refuses to call a screen done until a human can see both
at once. Matching numbers are not evidence: a view can measure right and still
look wrong.

    device_compare.py <original.png> <rendered.png> <out.png>

The two are rarely the same pixel size (a 12 mini capture next to a 17 Pro
simulator), so the taller one is scaled to the other's height by nearest
neighbour before they are joined with a divider. stdlib only — the PNG reader is
shared with device_measure, and the writer is a few lines of zlib.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_measure import PNG  # noqa: E402  (same-directory sibling)

DIVIDER = 8
DIVIDER_RGB = (255, 0, 0)


def rows_rgb(png: PNG) -> list[list[tuple[int, int, int]]]:
    ch = png.channels
    return [[tuple(row[x * ch:x * ch + 3]) for x in range(png.width)] for row in png.rows]


def scale_to(rows: list[list[tuple[int, int, int]]], width: int, height: int):
    """Nearest-neighbour resample — exactness is the eye's job here, not the filter's."""
    src_h, src_w = len(rows), len(rows[0])
    return [[rows[min(src_h - 1, y * src_h // height)][min(src_w - 1, x * src_w // width)]
             for x in range(width)] for y in range(height)]


def write_png(path: str, rows: list[list[tuple[int, int, int]]]) -> None:
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


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("ERROR: usage: device_compare.py <original.png> <rendered.png> <out.png>",
              file=sys.stderr)
        return 1
    try:
        left, right = rows_rgb(PNG(argv[1])), rows_rgb(PNG(argv[2]))
    except (OSError, ValueError, zlib.error) as exc:
        print(f"ERROR: cannot read images: {exc}", file=sys.stderr)
        return 1

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
    left = scale_to(left, round(len(left[0]) * height / len(left)), height)
    right = scale_to(right, round(len(right[0]) * height / len(right)), height)
    gap = [DIVIDER_RGB] * DIVIDER
    write_png(argv[3], [left[y] + gap + right[y] for y in range(height)])
    print(f"OK: wrote {argv[3]} ({len(left[0])}+{len(right[0])}px wide, {height}px tall) "
          "— original on the left, reproduction on the right", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
