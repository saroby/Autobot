#!/usr/bin/env python3
"""Frozen-by-default contracts for /autobot:resume into Phase 1.

Background
----------
Phase 1 (architect) emits the type contract: ``<App>/Models/*.swift`` plus
``Models/ServiceProtocols.swift``. Downstream Phase-4 code (``Views/``,
``ViewModels/``, ``App/``, ``Services/``, ``Utilities/``) is written against
those exact symbol names.

architect output is nondeterministic. A plain ``/autobot:resume 1`` (or
``--force``, or an older build with no stored input hash) re-runs architect
from scratch; a renamed Model field produces a NEW contract while the
already-written downstream Swift still references the OLD names — a silent
compile break — and the Models snapshot is overwritten, so there is no way
back.

``input_hash.should_skip_phase`` already protects the "inputs unchanged" path:
it skips the phase entirely, so architect never runs. This module covers the
orthogonal case — architect is ABOUT to re-run AND downstream code already
exists. The safe default is to FREEZE: restore the saved contract snapshot and
skip architect, unless the operator explicitly opts into regeneration with
``--regenerate`` (which cascades to a full downstream rebuild via the normal
forward flow, since Models checksums change and every later phase's input hash
misses).

Decision
--------
``frozen = snapshotPresent AND downstreamPresent AND NOT regenerate``

  snapshotPresent   ``.autobot/contracts/phase-1-models`` holds .swift AND
                    ``.autobot/contracts/models.sha256`` exists
  downstreamPresent any Phase-4-owned code dir (derived from
                    spec.fileOwnership, SSOT) holds a .swift file

Public API
----------
decide(project_root, spec, state, phase, *, regenerate) -> dict
apply(project_root, spec, state, phase, *, regenerate) -> dict   # decide + restore + log
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# In-tree import surface — bypass the runtime.py facade (see tasks/lessons.md #20).
sys.path.insert(0, str(SCRIPT_DIR))

CONTRACTS_SUBDIR = (".autobot", "contracts")
SNAPSHOT_DIRNAME = "phase-1-models"
CHECKSUM_FILENAME = "models.sha256"


def _snapshot_present(project_root: Path) -> bool:
    contracts = project_root.joinpath(*CONTRACTS_SUBDIR)
    snap = contracts / SNAPSHOT_DIRNAME
    checksum = contracts / CHECKSUM_FILENAME
    if not checksum.is_file() or not snap.is_dir():
        return False
    return any(p.suffix == ".swift" for p in snap.rglob("*") if p.is_file())


def _downstream_swift_dirs(spec: dict, app_name: str) -> list[Path]:
    """Phase-4 code directories, derived from spec.fileOwnership (SSOT).

    Only directory writes are returned (Views/, ViewModels/, App/, Services/,
    Utilities/, ...). Non-code dirs like backend/ or Assets.xcassets/ are
    returned too but never match because they hold no .swift — keeping the
    derivation purely spec-driven without hard-coding which dirs are "code".
    """
    phase4 = (spec.get("phases") or {}).get("4") or {}
    agents = phase4.get("agents") or []
    ownership = (spec.get("fileOwnership") or {}).get("agents") or {}
    rels: list[str] = []
    for agent in agents:
        for raw in (ownership.get(agent, {}).get("writes") or []):
            if raw.endswith("/"):
                rels.append(raw.replace("{appName}", app_name) if app_name else raw)
    return [Path(r.rstrip("/")) for r in rels]


def _downstream_present(project_root: Path, dirs: list[Path]) -> bool:
    for rel in dirs:
        d = project_root / rel
        if d.is_dir() and any(p.suffix == ".swift" for p in d.rglob("*") if p.is_file()):
            return True
    return False


def decide(project_root: Path, spec: dict, state: dict, phase, *, regenerate: bool = False) -> dict:
    app_name = state.get("appName") or ""
    snap = _snapshot_present(Path(project_root))
    down = _downstream_present(Path(project_root), _downstream_swift_dirs(spec, app_name))
    frozen = snap and down and not regenerate

    if frozen:
        action = "restore"
        reason = (
            "contract snapshot present and downstream code exists; "
            "preserving the contract downstream was built against"
        )
    elif regenerate:
        action = "regenerate"
        reason = "--regenerate-contracts set; architect regenerates (downstream rebuilds on the forward pass)"
    elif not snap:
        action = "regenerate"
        reason = "no contract snapshot to restore; architect regenerates and saves a fresh snapshot"
    else:  # snapshot present but no downstream depends on it yet
        action = "regenerate"
        reason = "no downstream code depends on the contract yet; architect may regenerate freely"

    return {
        "frozen": frozen,
        "action": action,
        "reason": reason,
        "phase": str(phase),
        "snapshotPresent": snap,
        "downstreamPresent": down,
        "regenerate": bool(regenerate),
    }


def _restore_snapshot(project_root: Path, app_name: str) -> tuple[bool, str]:
    """Delegate to snapshot-contracts.sh (the Models-restore SSOT)."""
    script = SCRIPT_DIR / "snapshot-contracts.sh"
    proc = subprocess.run(
        ["bash", str(script), "restore", "--app-name", app_name, "--project-dir", str(project_root)],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def apply(project_root: Path, spec: dict, state: dict, phase, *, regenerate: bool = False) -> dict:
    """Decide, and when frozen, restore the snapshot + record a validated event."""
    project_root = Path(project_root)
    result = decide(project_root, spec, state, phase, regenerate=regenerate)
    if not result["frozen"]:
        return result

    app_name = state.get("appName") or ""
    ok, detail = _restore_snapshot(project_root, app_name)
    result["restored"] = ok
    result["restoreDetail"] = detail
    if not ok:
        # Freeze was warranted but the snapshot could not be restored. Do NOT
        # silently fall through to regeneration — that is the exact drift we
        # are guarding against. Surface an error and let the caller halt.
        result["frozen"] = False
        result["action"] = "error"
        result["reason"] = f"freeze requested but snapshot restore failed: {detail}"
        return result

    from event_log import append_build_log  # in-tree direct import

    append_build_log(
        project_root,
        "contracts_frozen",
        phase=str(phase),
        detail=result["reason"],
        spec=spec,
    )
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Frozen-by-default contracts for /autobot:resume into Phase 1"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("decide", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        p.add_argument("--phase", default="1")
        p.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()

    from spec_loader import load_spec
    from state_store import load_state, state_file_from_args

    spec = load_spec()
    state_args = argparse.Namespace(project_dir=args.project_dir, state_file=None)
    state = load_state(state_file_from_args(state_args))
    proj = Path(args.project_dir).resolve()

    fn = decide if args.cmd == "decide" else apply
    result = fn(proj, spec, state, args.phase, regenerate=args.regenerate)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("action") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(_main())
