#!/usr/bin/env python3
"""clone_structural_diff.py — count missing elements mechanically.

    clone_structural_diff.py <measurement.json> <rendered-tree.json> [--tolerance 8]

The measurement JSON is Step 3's per-screen output; the rendered tree is
`axe describe-ui` against the simulator that just rendered the clone
(`device_render.sh` writes it next to the screenshot whenever AXe is installed).

The dominant reproduction failure is a wholesale MISSING element (DCGen,
arXiv 2406.16386: 85.3% of failures), and Step 6-4 asks a human to walk the
spec's element table row by row. This automates that walk: every spec element
must have a rendered counterpart — matched by label first, then by frame — and
label-matched elements that drifted beyond the tolerance are reported as layout
mismatches. Missing elements exit 1 so the convergence loop cannot call itself
done with a hole in the screen; pixel similarity stays device_compare's job.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# Spec containers at (nearly) screen size are layout plumbing, not content —
# same 90% rule the measurement's uncovered-region scan uses.
FULLSCREEN_RATIO = 0.9


def _flatten(data) -> list[dict]:
    """Every node of AXe's describe-ui tree (accepts a flat list too)."""
    roots = data if isinstance(data, list) else [data]
    flat: list[dict] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            flat.append(node)
            for child in node.get("children") or []:
                walk(child)

    for root in roots:
        walk(root)
    return flat


def _rendered_label(node: dict) -> str:
    """The label AXe actually emits.

    `axe describe-ui` writes `AXLabel` (plus `title`/`AXValue`); it never writes
    a lowercase `label`. Reading only `label` made the label match silently
    unreachable, so every element fell through to the frame match and anything
    shifted past the tolerance — a safe-area inset is enough — was reported as
    MISSING. That inverts Step 6-5: real position drift arrived as the
    top-priority "element is absent". Measured against a real render 2026-08-22.
    """
    for key in ("AXLabel", "label", "title", "AXValue"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _center(frame: dict) -> tuple[float, float]:
    return (float(frame.get("x", 0)) + float(frame.get("width", 0)) / 2,
            float(frame.get("y", 0)) + float(frame.get("height", 0)) / 2)


def _distance(a: dict, b: dict) -> float:
    (ax, ay), (bx, by) = _center(a), _center(b)
    return math.hypot(ax - bx, ay - by)


def _fmt(frame: dict) -> str:
    return ("(" + ", ".join(str(round(float(frame.get(key, 0)), 1))
                            for key in ("x", "y", "width", "height")) + ")")


def diff(measurement: dict, rendered_tree, tolerance: float) -> tuple[list[str], int]:
    """Return (report lines, missing count)."""
    points = (measurement.get("screen") or {}).get("points") or {}
    screen_area = float(points.get("width", 0)) * float(points.get("height", 0))
    spec = [
        element for element in measurement.get("elements") or []
        if not (screen_area
                and element["frame"]["width"] * element["frame"]["height"]
                >= FULLSCREEN_RATIO * screen_area)
    ]
    rendered = [node for node in _flatten(rendered_tree) if node.get("frame")]
    unclaimed = list(range(len(rendered)))
    lines: list[str] = []
    missing = 0

    def claim(index: int) -> None:
        unclaimed.remove(index)

    for element in spec:
        label = (element.get("label") or "").strip()
        frame = element["frame"]
        by_label = [i for i in unclaimed
                    if label and _rendered_label(rendered[i]) == label]
        if by_label:
            best = min(by_label, key=lambda i: _distance(frame, rendered[i]["frame"]))
            claim(best)
            drift = _distance(frame, rendered[best]["frame"])
            if drift > tolerance:
                lines.append(
                    f"WARN: moved {element.get('role')} '{label}' — "
                    f"spec {_fmt(frame)} rendered {_fmt(rendered[best]['frame'])} "
                    f"(center off by {round(drift, 1)}pt)")
            continue
        by_frame = [i for i in unclaimed
                    if _distance(frame, rendered[i]["frame"]) <= tolerance
                    and abs(float(rendered[i]["frame"].get("width", 0))
                            - frame["width"]) <= 2 * tolerance
                    and abs(float(rendered[i]["frame"].get("height", 0))
                            - frame["height"]) <= 2 * tolerance]
        if by_frame:
            claim(min(by_frame, key=lambda i: _distance(frame, rendered[i]["frame"])))
            continue
        missing += 1
        lines.append(f"ERROR: missing {element.get('role')} '{label}' @ {_fmt(frame)}")

    extras = sorted({_rendered_label(rendered[i]) for i in unclaimed} - {""})
    for label in extras:
        lines.append(f"INFO: extra rendered element '{label}' — not in the spec")

    if missing:
        lines.append(f"ERROR: {missing}/{len(spec)} spec element(s) have no rendered "
                     "counterpart — fix these before spacing/typography/polish")
    else:
        lines.append(f"OK: all {len(spec)} spec elements are present in the render")
    return lines, missing


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurement")
    parser.add_argument("rendered_tree")
    parser.add_argument("--tolerance", type=float, default=8.0,
                        help="max center drift in points before an element counts as moved")
    args = parser.parse_args(argv[1:])
    try:
        measurement = json.loads(Path(args.measurement).read_text(encoding="utf-8"))
        rendered = json.loads(Path(args.rendered_tree).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    lines, missing = diff(measurement, rendered, args.tolerance)
    for line in lines:
        print(line)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
