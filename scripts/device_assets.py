#!/usr/bin/env python3
"""Extract screenshot-backed assets from one measured clone screen.

The accessibility measurement stores element frames in points while the source
screenshot stores pixels. This module applies the recorded scale, crops visible
AXImage elements (plus explicitly requested element indices), and records the
research provenance of every crop in an atomic manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from device_compare import write_png  # noqa: E402
from device_measure import PNG  # noqa: E402

MANIFEST_VERSION = 1
RESEARCH_SCOPE = "research-only"
METHOD = "capture-crop"
QUALITY_CAVEAT = (
    "Screenshot crop only; pixels may include compositing, scaling, clipping, "
    "or overlays and are not the app's original binary asset."
)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, value: object) -> None:
    _atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_path(measurement_path: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute() or path.exists():
        return path
    adjacent = measurement_path.parent / path
    if adjacent.exists():
        return adjacent
    return path


def _default_assets_dir(measurement_path: Path) -> Path:
    if measurement_path.parent.name == "screens":
        return measurement_path.parent.parent / "assets"
    return measurement_path.parent / "assets"


def _parse_indices(value: str | None) -> set[int]:
    if not value:
        return set()
    indices: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            index = int(token)
        except ValueError as exc:
            raise ValueError(f"invalid element index: {token}") from exc
        if index < 0:
            raise ValueError(f"element index must be non-negative: {index}")
        indices.add(index)
    return indices


def _crop_bounds(frame: dict, scale: float, width: int, height: int) -> tuple[int, int, int, int]:
    try:
        x = float(frame["x"])
        y = float(frame["y"])
        frame_width = float(frame["width"])
        frame_height = float(frame["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid element frame: {frame!r}") from exc
    values = (x, y, frame_width, frame_height, scale)
    if not all(math.isfinite(value) for value in values) or scale <= 0:
        raise ValueError(f"invalid frame or scale: frame={frame!r}, scale={scale!r}")
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError(f"element frame has no visible area: {frame!r}")

    # Floor the origin and ceil the far edge so fractional point coordinates do
    # not discard an anti-aliased edge pixel. Clip only after both are computed.
    left = max(0, min(width, math.floor(x * scale)))
    top = max(0, min(height, math.floor(y * scale)))
    right = max(0, min(width, math.ceil((x + frame_width) * scale)))
    bottom = max(0, min(height, math.ceil((y + frame_height) * scale)))
    if right <= left or bottom <= top:
        raise ValueError(f"element frame falls outside the screenshot: {frame!r}")
    return left, top, right, bottom


def _crop_rows(png: PNG, bounds: tuple[int, int, int, int]) -> list[list[tuple[int, int, int]]]:
    left, top, right, bottom = bounds
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(top, bottom):
        source = png.rows[y]
        rows.append([
            tuple(source[x * png.channels:x * png.channels + 3])
            for x in range(left, right)
        ])
    return rows


def _write_crop(crops_dir: Path, rows: list[list[tuple[int, int, int]]]) -> tuple[str, Path]:
    crops_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".crop.", suffix=".png", dir=crops_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        write_png(str(temporary), rows)
        digest = _sha256(temporary)
        destination = crops_dir / f"{digest}.png"
        if destination.exists():
            if _sha256(destination) != digest:
                raise ValueError(f"digest collision at {destination}")
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        return digest, destination
    finally:
        if temporary.exists():
            temporary.unlink()


def _imageset_scale(scale: float) -> str:
    for candidate in (1, 2, 3):
        if abs(scale - candidate) < 0.01:
            return f"{candidate}x"
    return "1x"


def _write_imageset(catalog: Path, digest: str, crop: Path, scale: float) -> tuple[str, Path]:
    catalog.mkdir(parents=True, exist_ok=True)
    asset_name = f"capture_{digest}"
    imageset = catalog / f"{asset_name}.imageset"
    imageset.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_name}.png"
    image_path = imageset / filename
    if not image_path.exists() or _sha256(image_path) != digest:
        fd, temporary_name = tempfile.mkstemp(prefix=".image.", suffix=".png", dir=imageset)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(crop, temporary)
            os.replace(temporary, image_path)
        finally:
            if temporary.exists():
                temporary.unlink()
    contents = {
        "images": [{
            "filename": filename,
            "idiom": "universal",
            "scale": _imageset_scale(scale),
        }],
        "info": {"author": "xcode", "version": 1},
    }
    _write_json(imageset / "Contents.json", contents)
    return asset_name, imageset


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": MANIFEST_VERSION, "scope": RESEARCH_SCOPE, "assets": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read asset manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
        raise ValueError(f"invalid asset manifest: {path}")
    return value


def _manifest_identity(entry: dict) -> tuple[str, int]:
    element = entry.get("element") or {}
    try:
        index = int(element.get("index", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid asset manifest entry: {entry!r}") from exc
    return str(entry.get("sourceMeasurement", "")), index


def _merge_manifest(path: Path, entries: list[dict]) -> None:
    manifest = _load_manifest(path)
    merged = {
        _manifest_identity(entry): entry
        for entry in manifest.get("assets", [])
        if isinstance(entry, dict)
    }
    for entry in entries:
        merged[_manifest_identity(entry)] = entry
    manifest = {
        "version": MANIFEST_VERSION,
        "scope": RESEARCH_SCOPE,
        "assets": [merged[key] for key in sorted(merged)],
    }
    _write_json(path, manifest)


# An icon exists in the accessibility tree only as a description ("좋아요.
# 226명이 이 게시물을 좋아합니다."), never as a picture, so nothing in the
# measurement can reproduce it. Rendering these from the label was tried and
# measured worse than useless on 2026-08-23. A crop of the capture is the
# documented research-only path, and `device_compare --mask-assets` keeps the
# score honest about which pixels came from it.
# AXLink is text, not an icon — and text is already reproduced from the
# measured AXStaticText, so pasting it would draw the same words twice.
CONTROL_ROLES = {"AXButton", "AXKey", "AXSwitch"}
MAX_CONTROL_SIDE = 128.0
MAX_CONTROL_AREA = 88.0 * 88.0


def _is_flat(png, frame: dict, scale: float, tolerance: int = 12) -> bool:
    """True when a solid fill could reproduce this region.

    A separator or a card background is flat and the measurement already
    reproduces it from `colors.fill`. A logo or a glyph is not — and a fill is
    all the reproduction has for it, which is why the Threads wordmark rendered
    as empty space. Sampled on a coarse grid; exactness is not the question.
    """
    try:
        x = int(float(frame["x"]) * scale)
        y = int(float(frame["y"]) * scale)
        width = int(float(frame["width"]) * scale)
        height = int(float(frame["height"]) * scale)
    except (KeyError, TypeError, ValueError):
        return True
    if width <= 0 or height <= 0:
        return True
    seen = []
    steps = 5
    for row in range(steps):
        for column in range(steps):
            hexv = png.hex_at(min(png.width - 1, x + width * column // (steps - 1 or 1)),
                              min(png.height - 1, y + height * row // (steps - 1 or 1)))
            if hexv:
                seen.append(tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5)))
    if not seen:
        return True
    return all(max(abs(a[channel] - b[channel]) for channel in range(3)) <= tolerance
               for a in seen for b in seen)


def _auto_selected(elements: list[dict], png=None, scale: float = 1.0) -> set[int]:
    """Images, plus leaf controls small enough to be an icon.

    A label-less `AXOther` leaf joins them when its pixels are not flat: it is
    the wrapper an icon or a wordmark lives in, it has no label to identify it,
    and a solid fill cannot stand in for it.
    """
    parents = {element.get("parent") for element in elements}
    # Labels this screen already draws from measured type. A control repeating
    # one of them is a text button, not an icon.
    reproduced = {(element.get("label") or "").strip()
                  for element in elements if element.get("text")} - {""}
    selected: set[int] = set()
    for index, element in enumerate(elements):
        if not element.get("visible", True):
            continue
        if element.get("role") == "AXImage":
            selected.add(index)
            continue
        role = element.get("role")
        decorative = (role == "AXOther" and not (element.get("label") or "").strip()
                      and png is not None)
        if (role not in CONTROL_ROLES and not decorative) or index in parents:
            continue
        if element.get("text") or (element.get("label") or "").strip() in reproduced:
            # Measured type is reproducible; do not paste it back.
            continue
        frame = element.get("frame") or {}
        try:
            width, height = float(frame["width"]), float(frame["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        if max(width, height) > MAX_CONTROL_SIDE or width * height > MAX_CONTROL_AREA:
            continue
        if decorative and _is_flat(png, frame, scale):
            # A flat wrapper is already reproduced from its measured fill.
            continue
        selected.add(index)
    return selected


def extract_assets(
    measurement: str | Path,
    screenshot: str | Path | None = None,
    *,
    assets_dir: str | Path | None = None,
    assets_catalog: str | Path | None = None,
    indices: set[int] | list[int] | tuple[int, ...] | None = None,
) -> dict:
    """Extract selected screenshot crops and merge their provenance manifest."""

    measurement_path = Path(measurement)
    try:
        measured = json.loads(measurement_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read measurement {measurement_path}: {exc}") from exc
    if not isinstance(measured, dict) or not isinstance(measured.get("elements"), list):
        raise ValueError(f"invalid measurement JSON: {measurement_path}")

    source = measured.get("source") or {}
    screenshot_path = Path(screenshot) if screenshot is not None else _source_path(
        measurement_path, source.get("image")
    )
    if screenshot_path is None:
        raise ValueError("measurement has no source screenshot")
    try:
        png = PNG(str(screenshot_path))
    except (OSError, ValueError, zlib.error) as exc:
        raise ValueError(f"cannot read source screenshot {screenshot_path}: {exc}") from exc

    try:
        scale = float((measured.get("screen") or {})["scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("measurement has no valid screen scale") from exc
    selected = set(indices or ())
    elements = measured["elements"]
    invalid = sorted(index for index in selected if index < 0 or index >= len(elements))
    if invalid:
        raise ValueError(f"element indices out of range: {invalid}")
    selected.update(_auto_selected(elements, png, scale))

    # Pixels no leaf element accounts for. Threads exposes a post avatar to no
    # accessibility element at all, so nothing in the tree can reproduce it —
    # five of them were simply absent from the reproduction until the scan
    # started counting only leaves as covering. Indexed negatively so they sit
    # beside the element crops in the same manifest without colliding.
    uncovered = [region for region in (measured.get("uncoveredRegions") or [])
                 if isinstance(region, dict)]

    assets_root = Path(assets_dir) if assets_dir is not None else _default_assets_dir(measurement_path)
    crops_dir = assets_root / "crops"
    catalog = Path(assets_catalog) if assets_catalog is not None else None
    entries: list[dict] = []
    unique_digests: set[str] = set()
    targets: list[tuple[int, dict]] = [(index, elements[index]) for index in sorted(selected)]
    targets += [
        (-(offset + 1),
         {"role": "uncoveredRegion", "label": "",
          "frame": {key: region.get(key, 0.0)
                    for key in ("x", "y", "width", "height")}})
        for offset, region in enumerate(uncovered)
    ]
    for index, element in targets:
        frame = element.get("frame")
        bounds = _crop_bounds(frame, scale, png.width, png.height)
        digest, output = _write_crop(crops_dir, _crop_rows(png, bounds))
        unique_digests.add(digest)
        entry = {
            "sourceScreenshot": str(screenshot_path),
            "sourceXML": source.get("tree"),
            "sourceMeasurement": str(measurement_path),
            "element": {
                "index": index,
                "role": element.get("role"),
                "label": element.get("label"),
                "frame": frame,
            },
            "method": METHOD,
            "qualityCaveat": QUALITY_CAVEAT,
            "scope": RESEARCH_SCOPE,
            "sha256": digest,
            "outputPath": output.relative_to(assets_root).as_posix(),
            "pixelBounds": {
                "x": bounds[0],
                "y": bounds[1],
                "width": bounds[2] - bounds[0],
                "height": bounds[3] - bounds[1],
            },
            "pointToPixelScale": scale,
        }
        if catalog is not None:
            asset_name, imageset = _write_imageset(catalog, digest, output, scale)
            entry["assetName"] = asset_name
            entry["imagesetPath"] = str(imageset)
        entries.append(entry)

    manifest_path = assets_root / "manifest.json"
    _merge_manifest(manifest_path, entries)
    return {
        "selected": len(selected),
        "unique": len(unique_digests),
        "entries": entries,
        "manifest": str(manifest_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurement", help="measured screen JSON")
    parser.add_argument("screenshot", nargs="?", help="override source screenshot PNG")
    parser.add_argument("--assets-dir", help="assets output directory")
    parser.add_argument("--assets-catalog", help="optional Assets.xcassets directory")
    parser.add_argument(
        "--indices",
        help="comma-separated extra measured element indices to crop in addition to AXImage",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = extract_assets(
            args.measurement,
            args.screenshot,
            assets_dir=args.assets_dir,
            assets_catalog=args.assets_catalog,
            indices=_parse_indices(args.indices),
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"OK: extracted={result['selected']} unique={result['unique']} "
        f"manifest={result['manifest']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
