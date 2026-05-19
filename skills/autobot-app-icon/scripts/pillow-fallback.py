#!/usr/bin/env python3
"""Generate a 1024x1024 iOS app icon using Pillow when imagegen is unavailable.

The output is deterministic from the app name (color is derived from a hash
of the name unless --color is given). Designed as a graceful fallback so the
Autobot pipeline can still ship a recognizable AppIcon without an external
image-generation service.

Usage:
    python3 pillow-fallback.py --name SocialFitness --out .autobot/app-icon-1024.png
    python3 pillow-fallback.py --name SocialFitness --out .autobot/app-icon-1024.png --color "#3366FF"
"""

import argparse
import hashlib
import sys
from pathlib import Path


SIZE = 1024
FOREGROUND = (255, 255, 255)

FONT_CANDIDATES = (
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def parse_color(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"--color must be 6-char hex, got: {s!r}")
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


def hash_color(name: str) -> tuple[int, int, int]:
    """Stable, vivid color from app name."""
    h = hashlib.md5(name.encode("utf-8")).digest()
    # Keep saturation high by clamping each channel to [60, 220].
    return tuple(60 + (b % 161) for b in h[:3])


def adjust(color: tuple[int, int, int], delta: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, c + delta)) for c in color)


def initials_for(name: str) -> str:
    """Up to two ASCII letters for the icon glyph."""
    parts = [p for p in name.replace("-", " ").replace("_", " ").split() if p]
    if len(parts) >= 2:
        s = (parts[0][:1] + parts[1][:1]).upper()
    else:
        s = name[:2].upper() if name else "A"
    # Strip non-ASCII to avoid font rendering surprises.
    s = "".join(c for c in s if c.isascii() and c.isalnum())
    return s or "A"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="App identifier name")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--color", default=None, help="Background hex like #3366FF")
    args = parser.parse_args()

    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError:
        print("ERROR: Pillow not installed. Run: python3 -m pip install --user Pillow", file=sys.stderr)
        return 2

    if args.color:
        bg = parse_color(args.color)
    else:
        bg = hash_color(args.name)

    # Vertical gradient: lighter top → base bottom.
    top = adjust(bg, +30)
    bottom = bg

    img = Image.new("RGB", (SIZE, SIZE), bg)
    pixels = img.load()
    for y in range(SIZE):
        t = y / (SIZE - 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        for x in range(SIZE):
            pixels[x, y] = (r, g, b)

    draw = ImageDraw.Draw(img)
    glyph = initials_for(args.name)

    font = None
    target_px = 600 if len(glyph) == 1 else 460
    for fp in FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(fp, size=target_px)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), glyph, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pos = ((SIZE - tw) // 2 - bbox[0], (SIZE - th) // 2 - bbox[1])

    # Soft drop shadow for depth.
    shadow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shadow_layer).text(
        (pos[0] + 8, pos[1] + 14), glyph, fill=(0, 0, 0, 90), font=font
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=12))
    img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)

    draw = ImageDraw.Draw(img)
    draw.text(pos, glyph, fill=FOREGROUND, font=font)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print(f"Wrote {out} ({SIZE}x{SIZE}, bg=#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}, glyph={glyph!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
