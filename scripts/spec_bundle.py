#!/usr/bin/env python3
"""Assemble and verify the split pipeline spec.

``spec/pipeline.json`` remains the executable compatibility bundle because
older commands and tests read it directly. ``spec/parts/*.json`` are the
smaller editing units. This tool keeps the two views byte-order independent
but semantically identical.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
BUNDLE_PATH = PLUGIN_DIR / "spec" / "pipeline.json"
PARTS_DIR = PLUGIN_DIR / "spec" / "parts"

PART_FILES = [
    "00-core.json",
    "01-state-schema.json",
    "02-transitions.json",
    "03-policies.json",
    "04-log-events.json",
    "05-file-ownership.json",
    "06-phases.json",
    "07-gates.json",
]

PART_KEYS: dict[str, list[str]] = {
    "00-core.json": ["schemaVersion", "statuses", "terminalStatuses"],
    "01-state-schema.json": ["stateSchema"],
    "02-transitions.json": ["transitions"],
    "03-policies.json": ["policies"],
    "04-log-events.json": ["logEvents"],
    "05-file-ownership.json": ["fileOwnership"],
    "06-phases.json": ["phases"],
    "07-gates.json": ["gates"],
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def assemble_parts(parts_dir: Path = PARTS_DIR) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    seen: set[str] = set()
    for filename in PART_FILES:
        path = parts_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"missing spec part: {path}")
        part = _read_json(path)
        expected = set(PART_KEYS[filename])
        actual = set(part)
        if actual != expected:
            raise ValueError(
                f"{path} must contain exactly {sorted(expected)}, got {sorted(actual)}"
            )
        overlap = seen & actual
        if overlap:
            raise ValueError(f"duplicate spec key(s) across parts: {sorted(overlap)}")
        spec.update(part)
        seen.update(actual)
    return spec


def split_bundle(bundle_path: Path = BUNDLE_PATH, parts_dir: Path = PARTS_DIR) -> None:
    bundle = _read_json(bundle_path)
    for filename, keys in PART_KEYS.items():
        missing = [key for key in keys if key not in bundle]
        if missing:
            raise ValueError(f"{bundle_path} missing key(s) for {filename}: {missing}")
        _write_json(parts_dir / filename, {key: bundle[key] for key in keys})


def write_bundle(bundle_path: Path = BUNDLE_PATH, parts_dir: Path = PARTS_DIR) -> None:
    _write_json(bundle_path, assemble_parts(parts_dir))


def diff_bundle(bundle_path: Path = BUNDLE_PATH, parts_dir: Path = PARTS_DIR) -> list[str]:
    bundled = _read_json(bundle_path)
    assembled = assemble_parts(parts_dir)
    if bundled == assembled:
        return []
    errors: list[str] = []
    all_keys = list(dict.fromkeys([*bundled.keys(), *assembled.keys()]))
    for key in all_keys:
        if bundled.get(key) != assembled.get(key):
            errors.append(f"spec section drift: {key}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="verify spec/parts and spec/pipeline.json match")
    sub.add_parser("split-bundle", help="write spec/parts from spec/pipeline.json")
    sub.add_parser("write-bundle", help="write spec/pipeline.json from spec/parts")
    sub.add_parser("print", help="print assembled spec JSON to stdout")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "check":
            errors = diff_bundle()
            if errors:
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                print("Run: python3 scripts/spec_bundle.py write-bundle", file=sys.stderr)
                return 1
            print("OK: spec parts match spec/pipeline.json")
            return 0
        if args.cmd == "split-bundle":
            split_bundle()
            print("OK: wrote spec/parts from spec/pipeline.json")
            return 0
        if args.cmd == "write-bundle":
            write_bundle()
            print("OK: wrote spec/pipeline.json from spec/parts")
            return 0
        if args.cmd == "print":
            print(json.dumps(assemble_parts(), ensure_ascii=False, indent=2))
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
