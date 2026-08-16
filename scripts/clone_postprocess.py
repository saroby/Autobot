#!/usr/bin/env python3
"""Batch-measure clone captures, cache unchanged inputs, and emit evidence specs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device_assets  # noqa: E402
import device_measure  # noqa: E402

CACHE_VERSION = 1
MAX_WORKERS = 32


@dataclass(frozen=True)
class ScreenPair:
    stem: str
    xml: Path
    png: Path


@dataclass(frozen=True)
class PostprocessSummary:
    processed: int
    cached: int
    failed: int
    failures: tuple[str, ...]


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


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_pairs(raw_dir: str | Path) -> tuple[list[ScreenPair], list[str]]:
    raw = Path(raw_dir)
    if not raw.is_dir():
        return [], [f"raw directory not found: {raw}"]
    xml = {path.stem: path for path in raw.glob("*.xml") if path.is_file()}
    png = {path.stem: path for path in raw.glob("*.png") if path.is_file()}
    pairs: list[ScreenPair] = []
    failures: list[str] = []
    for stem in sorted(set(xml) | set(png)):
        if stem not in xml:
            failures.append(f"{stem}: missing XML pair for {png[stem]}")
        elif stem not in png:
            failures.append(f"{stem}: missing PNG pair for {xml[stem]}")
        else:
            pairs.append(ScreenPair(stem, xml[stem], png[stem]))
    if not pairs and not failures:
        failures.append(f"no raw XML/PNG pairs found in {raw}")
    return pairs, failures


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _input_hashes(pair: ScreenPair) -> dict[str, str]:
    return {"xmlSha256": _sha256(pair.xml), "pngSha256": _sha256(pair.png)}


def _load_cached_measurement(output: Path, cache_entry: dict, hashes: dict[str, str]) -> dict | None:
    if any(cache_entry.get(key) != value for key, value in hashes.items()) or not output.is_file():
        return None
    try:
        if cache_entry.get("outputSha256") != _sha256(output):
            return None
        value = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and isinstance(value.get("elements"), list) else None


def _relative_link(target: Path, start: Path) -> str:
    relative = Path(os.path.relpath(target, start)).as_posix()
    return quote(relative, safe="/._-")


def _escape_cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")


def evidence_markdown(
    stem: str,
    measurement: dict,
    *,
    json_path: Path,
    xml_path: Path,
    png_path: Path,
    manifest_path: Path,
) -> str:
    elements = measurement.get("elements") or []
    screen = measurement.get("screen") or {}
    points = screen.get("points") or {}
    pixels = screen.get("pixels") or {}
    layouts = Counter(
        element.get("layout", {}).get("axis")
        for element in elements
        if element.get("layout", {}).get("axis")
    )
    layout_text = ", ".join(f"{axis}={layouts[axis]}" for axis in sorted(layouts)) or "none inferred"
    source_dir = json_path.parent
    lines = [
        f"# {stem} screen evidence",
        "",
        "## Sources",
        "",
        f"- Screenshot: [raw PNG]({_relative_link(png_path, source_dir)})",
        f"- Accessibility tree: [raw XML]({_relative_link(xml_path, source_dir)})",
        f"- Measurement: [JSON]({_relative_link(json_path, source_dir)})",
        "",
        "## Layout summary",
        "",
        f"- Points: {points.get('width', 0)} × {points.get('height', 0)}",
        f"- Pixels: {pixels.get('width', 0)} × {pixels.get('height', 0)}",
        f"- Point-to-pixel scale: {screen.get('scale', 1.0)}",
        f"- Elements: {len(elements)}; layouts: {layout_text}",
        "",
        "## Elements",
        "",
        "| # | Role | Label | Frame (pt) | Layout | Colors |",
        "|---:|---|---|---|---|---|",
    ]
    asset_line = (
        f"- Extracted assets: [manifest]({_relative_link(manifest_path, source_dir)})"
        if manifest_path.is_file()
        else "- Extracted assets: not generated for this run"
    )
    lines.insert(7, asset_line)
    for index, element in enumerate(elements):
        frame = element.get("frame") or {}
        frame_text = ", ".join(
            str(frame.get(key, "?")) for key in ("x", "y", "width", "height")
        )
        layout = element.get("layout") or {}
        layout_bits = [str(layout.get("axis", ""))]
        if "spacing" in layout:
            layout_bits.append(f"spacing={layout['spacing']}")
        colors = ", ".join(
            f"{key}={value}" for key, value in sorted((element.get("colors") or {}).items())
        )
        lines.append(
            f"| {index} | {_escape_cell(element.get('role'))} | "
            f"{_escape_cell(element.get('label'))} | {_escape_cell(frame_text)} | "
            f"{_escape_cell('; '.join(bit for bit in layout_bits if bit))} | "
            f"{_escape_cell(colors)} |"
        )
    uncovered = measurement.get("uncoveredRegions") or []
    lines.extend(["", "## Uncovered regions", ""])
    if uncovered:
        lines.append(
            "Non-background areas no measured element covers — content the chrome "
            "filter may have dropped. Check each against the screenshot BEFORE "
            "writing the spec; a missing element here becomes a missing element "
            "in the reproduction."
        )
        lines.append("")
        lines.extend(
            f"- ({region.get('x')}, {region.get('y')}) "
            f"{region.get('width')} × {region.get('height')} pt"
            for region in uncovered
        )
    else:
        lines.append("- None — every visible region is covered by a measured element.")
    lines.extend(["", "## Unmeasurable", ""])
    unmeasurable = measurement.get("unmeasurable") or []
    if unmeasurable:
        lines.extend(f"- {item}" for item in unmeasurable)
    else:
        lines.append("- None reported.")
    return "\n".join(lines) + "\n"


def _measure(pair: ScreenPair) -> dict:
    return device_measure.measure(str(pair.xml), str(pair.png))


def postprocess(
    clone_root: str | Path,
    *,
    raw_dir: str | Path | None = None,
    screens_dir: str | Path | None = None,
    assets_dir: str | Path | None = None,
    workers: int = 4,
    extract_assets: bool = False,
    assets_catalog: str | Path | None = None,
) -> PostprocessSummary:
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    root = Path(clone_root)
    raw = Path(raw_dir) if raw_dir is not None else root / "raw"
    screens = Path(screens_dir) if screens_dir is not None else root / "screens"
    assets = Path(assets_dir) if assets_dir is not None else root / "assets"
    screens.mkdir(parents=True, exist_ok=True)

    pairs, discovery_failures = discover_pairs(raw)
    states = {failure.split(":", 1)[0]: "failed" for failure in discovery_failures}
    failure_messages = list(discovery_failures)
    # Keep cache metadata out of screens/*.json so every JSON in that directory
    # remains a consumable screen measurement.
    cache_path = root / ".postprocess-cache.json"
    old_cache = _load_cache(cache_path)
    tool_digest = _sha256(Path(device_measure.__file__))
    cache_usable = (
        old_cache.get("version") == CACHE_VERSION
        and old_cache.get("measurementToolSha256") == tool_digest
        and isinstance(old_cache.get("screens"), dict)
    )
    old_entries = old_cache.get("screens", {}) if cache_usable else {}

    results: dict[str, dict] = {}
    hashes_by_stem: dict[str, dict[str, str]] = {}
    pending: list[ScreenPair] = []
    for pair in pairs:
        try:
            hashes = _input_hashes(pair)
        except OSError as exc:
            states[pair.stem] = "failed"
            failure_messages.append(f"{pair.stem}: cannot hash inputs: {exc}")
            continue
        hashes_by_stem[pair.stem] = hashes
        output = screens / f"{pair.stem}.json"
        cached = _load_cached_measurement(output, old_entries.get(pair.stem, {}), hashes)
        if cached is None:
            pending.append(pair)
        else:
            results[pair.stem] = cached
            states[pair.stem] = "cached"

    if pending:
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as executor:
            future_to_pair = {executor.submit(_measure, pair): pair for pair in pending}
            for future in as_completed(future_to_pair):
                pair = future_to_pair[future]
                try:
                    measured = future.result()
                    if not isinstance(measured, dict) or not isinstance(measured.get("elements"), list):
                        raise ValueError("measurement returned invalid data")
                    results[pair.stem] = measured
                    states[pair.stem] = "processed"
                except Exception as exc:  # keep other independent screens running
                    states[pair.stem] = "failed"
                    failure_messages.append(f"{pair.stem}: measurement failed: {exc}")

    pairs_by_stem = {pair.stem: pair for pair in pairs}
    new_cache_entries: dict[str, dict] = {}
    manifest_path = assets / "manifest.json"
    for stem in sorted(results):
        pair = pairs_by_stem[stem]
        json_path = screens / f"{stem}.json"
        md_path = screens / f"{stem}.md"
        measured = results[stem]
        try:
            _atomic_write_text(json_path, _json_text(measured))
            if extract_assets:
                device_assets.extract_assets(
                    json_path,
                    pair.png,
                    assets_dir=assets,
                    assets_catalog=assets_catalog,
                )
            _atomic_write_text(
                md_path,
                evidence_markdown(
                    stem,
                    measured,
                    json_path=json_path,
                    xml_path=pair.xml,
                    png_path=pair.png,
                    manifest_path=manifest_path,
                ),
            )
            new_cache_entries[stem] = {
                **hashes_by_stem[stem],
                "outputSha256": _sha256(json_path),
            }
        except (OSError, ValueError, zlib.error) as exc:
            states[stem] = "failed"
            failure_messages.append(f"{stem}: output stage failed: {exc}")

    cache = {
        "version": CACHE_VERSION,
        "measurementToolSha256": tool_digest,
        "screens": {stem: new_cache_entries[stem] for stem in sorted(new_cache_entries)},
    }
    try:
        _atomic_write_text(cache_path, _json_text(cache))
    except OSError as exc:
        states["cache"] = "failed"
        failure_messages.append(f"cache: cannot write {cache_path}: {exc}")

    return PostprocessSummary(
        processed=sum(state == "processed" for state in states.values()),
        cached=sum(state == "cached" for state in states.values()),
        failed=sum(state == "failed" for state in states.values()),
        failures=tuple(sorted(failure_messages)),
    )


def _worker_count(value: str) -> int:
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer") from exc
    if not 1 <= workers <= MAX_WORKERS:
        raise argparse.ArgumentTypeError(f"workers must be between 1 and {MAX_WORKERS}")
    return workers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clone_root", nargs="?", default=".autobot/clone")
    parser.add_argument("--raw-dir")
    parser.add_argument("--screens-dir")
    parser.add_argument("--assets-dir")
    parser.add_argument("--workers", type=_worker_count, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--extract-assets", action="store_true")
    parser.add_argument("--assets-catalog")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = postprocess(
            args.clone_root,
            raw_dir=args.raw_dir,
            screens_dir=args.screens_dir,
            assets_dir=args.assets_dir,
            workers=args.workers,
            extract_assets=args.extract_assets,
            assets_catalog=args.assets_catalog,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("SUMMARY processed=0 cached=0 failed=1")
        return 1
    for failure in summary.failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    print(
        f"SUMMARY processed={summary.processed} cached={summary.cached} "
        f"failed={summary.failed}"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
