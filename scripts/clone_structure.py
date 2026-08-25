#!/usr/bin/env python3
"""clone_structure.py — find the repeating units a measurement cannot express.

A measurement is a flat list of elements at absolute frames. A feed of 30 cards
is 30 independent element groups in it, and `clone_view_codegen.py` faithfully
replays all 30 as separate absolute-positioned blocks. That output scores
perfectly against every check the pipeline had — every element is present, at
the right place, in the right colour — and is still not code anyone can edit,
because the one thing it does not say is "this is one card, thirty times".

That layer is not measurable, but it is *derivable*: siblings whose subtrees
have the same shape, laid out at a regular pitch along one axis, are a repeat.
Detecting it mechanically is what makes the human step cheap — confirming a
detected group costs a glance, authoring the same claim in prose costs a page.

Only the shape is compared, never the content: on a real feed the per-item text
is the one thing that always differs, so requiring equal labels or equal widths
finds nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Text is measured from its own glyphs, so its width carries the content, not
# the shape — two cards differ there by construction. Height is the line box and
# stays put, which is why it is the half that is compared.
TEXT_ROLES = {"AXStaticText", "AXTextField", "AXTextView"}

# Two is a pair, which is often just a pair. Three in a row with one shape and
# one pitch is a pattern — the smallest run that is not plausibly coincidence.
MIN_GROUP = 3


def _children_of(elements: list[dict]) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for index, element in enumerate(elements):
        parent = element.get("parent", -1)
        if isinstance(parent, int) and parent >= 0:
            children.setdefault(parent, []).append(index)
    return children


def _signature(elements: list[dict], children: dict[int, list[int]], index: int) -> tuple:
    """The shape of one subtree: roles, depths and the dimensions that hold still."""
    parts: list[tuple] = []

    def walk(at: int, depth: int) -> None:
        element = elements[at]
        frame = element.get("frame") or {}
        height = round(float(frame.get("height", 0)))
        if element.get("role") in TEXT_ROLES:
            dimensions: tuple = (height,)
        else:
            dimensions = (round(float(frame.get("width", 0))), height)
        parts.append((depth, element.get("role")) + dimensions)
        for kid in children.get(at, []):
            walk(kid, depth + 1)

    walk(index, 0)
    return tuple(parts)


def _regular(steps: list[float]) -> bool:
    """One pitch, not an average of several.

    Shape alone is not a pattern: three same-shaped blocks scattered down a page
    are three blocks, and averaging their gaps into a single pitch invents a
    loop the screen does not have. Frames are rounded to 0.1pt and real layouts
    carry sub-point drift, so the bound is a tolerance, not equality.
    """
    if not all(step > 0 for step in steps):
        return False
    mean = sum(steps) / len(steps)
    tolerance = max(2.0, mean * 0.02)
    return all(abs(step - mean) <= tolerance for step in steps)


def _axis_and_pitch(elements: list[dict], run: list[int]) -> tuple[str | None, float | None]:
    origins = [(float(elements[i]["frame"]["x"]), float(elements[i]["frame"]["y"]))
               for i in run]
    dx = [b[0] - a[0] for a, b in zip(origins, origins[1:])]
    dy = [b[1] - a[1] for a, b in zip(origins, origins[1:])]
    if all(abs(step) < 0.5 for step in dx) and _regular(dy):
        return "vertical", round(sum(dy) / len(dy), 1)
    if all(abs(step) < 0.5 for step in dy) and _regular(dx):
        return "horizontal", round(sum(dx) / len(dx), 1)
    return None, None


def detect_repeats(measurement: dict, min_group: int = MIN_GROUP) -> list[dict]:
    """Every run of same-shaped siblings laid out at a regular pitch."""
    elements = measurement.get("elements") or []
    children = _children_of(elements)
    groups: list[dict] = []
    for parent, kids in sorted(children.items()):
        if len(kids) < min_group:
            continue
        signatures = [_signature(elements, children, kid) for kid in kids]
        start = 0
        for position in range(1, len(kids) + 1):
            if position < len(kids) and signatures[position] == signatures[start]:
                continue
            run = kids[start:position]
            if len(run) >= min_group:
                axis, pitch = _axis_and_pitch(elements, run)
                if axis is not None:
                    groups.append({
                        "parent": parent,
                        "children": run,
                        "axis": axis,
                        "pitch": pitch,
                        "count": len(run),
                    })
            start = position
    return groups


# The same ownership boundary the generated views use, expressed for JSON: while
# this key is present the file is a machine draft and every run rewrites it.
# Delete the key and the file is yours — no run touches it again. Without this
# the confirm step would be worthless, because the next `observe` would erase
# every correction, which is exactly what made hand-written specs pointless.
MARKER = "generated_by_clone_structure"


def _component_name(stem: str, ordinal: int) -> str:
    """A name for the extracted unit. A suggestion — renaming it is expected."""
    words = [part for part in re.split(r"[^A-Za-z]+", stem) if part]
    base = "".join(word.capitalize() for word in words) or "Screen"
    return f"{base}Item" + ("" if ordinal == 0 else str(ordinal + 1))


def write_structure(root: Path | str) -> list[Path]:
    """Draft one structure file per measurement. Returns the paths written."""
    root = Path(root)
    out_dir = root / "structure"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for measurement_path in sorted((root / "screens").glob("*.json")):
        stem = measurement_path.stem
        target = out_dir / f"{stem}.json"
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                existing = {}
            if not (isinstance(existing, dict) and existing.get(MARKER)):
                continue          # a person owns this file now
        try:
            measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"WARN: cannot read {measurement_path}: {exc}", file=sys.stderr)
            continue
        groups = detect_repeats(measurement)
        for ordinal, group in enumerate(groups):
            group["component"] = _component_name(stem, ordinal)
        payload = {
            MARKER: True,
            "version": 1,
            "source": str(measurement_path.relative_to(root)),
            "groups": groups,
        }
        _write_atomic(target, payload)
        written.append(target)
    return written


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("ERROR: usage: clone_structure.py <clone-root>", file=sys.stderr)
        return 2
    written = write_structure(argv[1])
    total = sum(len(json.loads(path.read_text(encoding="utf-8"))["groups"]) for path in written)
    print(f"INFO: {len(written)} structure draft(s), {total} repeat group(s) — "
          f"confirm them in {Path(argv[1]) / 'structure'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
