#!/usr/bin/env python3
"""Phase-level artifact snapshot/restore driven by spec.fileOwnership.

The hard-coded shell `case` block in snapshot-contracts.sh was the last place
where phase ↔ directory relationships lived outside spec/pipeline.json. This
runner derives the snapshot set from spec.fileOwnership.agents + the agents
declared on each phase, so adding a new phase or adjusting writes paths
automatically propagates here.

Subcommands:
    save-phase    --phase N --app-name App
    restore-phase --phase N --app-name App
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
# Bypass runtime.py facade — load only the spec module, no CLI surface.
sys.path.insert(0, str(SCRIPT_DIR))
from spec_loader import load_spec, resolve_app_template  # noqa: E402


def directories_for_phase(spec: dict, phase: str, app_name: str) -> list[str]:
    """Return the relative paths that should be snapshotted for the given phase.

    Drawn from fileOwnership.agents.<agent>.writes for every agent listed on
    the phase. Paths ending in '/' are treated as directories; bare paths are
    treated as files.
    """
    phase_spec = spec.get("phases", {}).get(phase, {})
    agents: Iterable[str] = phase_spec.get("agents", [])
    if not agents:
        return []
    ownership = spec.get("fileOwnership", {}).get("agents", {})
    paths: list[str] = []
    seen: set[str] = set()
    for agent in agents:
        for raw in ownership.get(agent, {}).get("writes", []):
            resolved = resolve_app_template(raw, app_name)
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
    return paths


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def cmd_save(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()
    snap_root = project_dir / ".autobot" / "contracts" / f"phase-{args.phase}-snapshot"

    # Tmp dir + atomic rename so a partial snapshot can never be observed.
    tmp_root = project_dir / ".autobot" / "contracts" / f".phase-{args.phase}-snapshot.tmp"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True)

    targets = directories_for_phase(spec, str(args.phase), args.app_name)
    if not targets:
        print(f"WARN: phase {args.phase} declares no agents/writes — empty snapshot", file=sys.stderr)

    saved: list[str] = []
    for rel in targets:
        is_dir = rel.endswith("/")
        src = project_dir / rel.rstrip("/")
        dst = tmp_root / rel.rstrip("/")
        if not src.exists():
            continue
        _copy(src, dst)
        saved.append(rel + ("" if is_dir else ""))

    if snap_root.exists():
        shutil.rmtree(snap_root)
    tmp_root.rename(snap_root)

    print(f"saved phase-{args.phase} → {snap_root}")
    for rel in saved:
        print(f"  ✓ {rel}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    spec = load_spec()
    project_dir = Path(args.project_dir).resolve()
    snap_root = project_dir / ".autobot" / "contracts" / f"phase-{args.phase}-snapshot"

    if not snap_root.is_dir():
        print(f"snapshot_missing: {snap_root}", file=sys.stderr)
        return 2

    targets = directories_for_phase(spec, str(args.phase), args.app_name)
    restored: list[str] = []
    for rel in targets:
        is_dir = rel.endswith("/")
        src = snap_root / rel.rstrip("/")
        dst = project_dir / rel.rstrip("/")
        if not src.exists():
            continue
        if is_dir and dst.exists():
            shutil.rmtree(dst)
        elif (not is_dir) and dst.exists():
            dst.unlink()
        _copy(src, dst)
        restored.append(rel)

    print(f"restored phase-{args.phase} from {snap_root}")
    for rel in restored:
        print(f"  ✓ {rel}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase snapshot runner (spec-driven)")
    sub = parser.add_subparsers(dest="command", required=True)

    save = sub.add_parser("save-phase")
    save.add_argument("--phase", required=True, type=int)
    save.add_argument("--app-name", required=True)
    save.add_argument("--project-dir", default=".")
    save.set_defaults(func=cmd_save)

    restore = sub.add_parser("restore-phase")
    restore.add_argument("--phase", required=True, type=int)
    restore.add_argument("--app-name", required=True)
    restore.add_argument("--project-dir", default=".")
    restore.set_defaults(func=cmd_restore)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
