#!/usr/bin/env python3
"""Per-phase input hash for idempotent /autobot:resume.

The hash covers exactly what *this phase* depends on:

    1. user idea (state.idea / state.appName / state.displayName / state.bundleId)
    2. spec.phases.<N> + spec.gates.<gate>      (the contract for the phase)
    3. checksums of files this phase OWNS in spec.fileOwnership

That's it. The previous version walked the dependency chain to also hash
upstream-owned files; in practice the spec dependency graph is partial and
the chain logic was fragile. If an upstream change matters, the agent rerun
in that upstream phase will already invalidate every downstream file the
current phase reads — so the current phase's owned-file checksums change too.

Public API
----------
compute_phase_input_hash(project_root, spec, state, phase) -> (hash, manifest)
should_skip_phase(project_root, spec, state, phase, force=False) -> (skip, reason)
mark_inputs(state, phase, *, hash_value, manifest) -> None
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

IDEA_FIELDS = ("idea", "appName", "displayName", "bundleId")
SCANNED_EXTENSIONS = (".swift", ".json", ".md", ".plist", ".xcprivacy", ".entitlements")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _file_checksum(path: Path) -> str:
    if not path.is_file():
        return "missing"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "unreadable"


def _owned_files(spec: dict, phase: str, app_name: str, project_root: Path) -> dict[str, str]:
    ownership = (spec.get("fileOwnership") or {}).get("agents") or {}
    phase_agents = ((spec.get("phases") or {}).get(str(phase)) or {}).get("agents") or []
    # Phases without declared agents (Phase 3 scaffold etc.) are checksum-stable
    # via the project files quality-engineer would own — that's a reasonable
    # default and avoids special-casing.
    if not phase_agents:
        phase_agents = ["quality-engineer"] if str(phase) == "3" else []

    files: dict[str, str] = {}
    for agent in phase_agents:
        for raw in (ownership.get(agent, {}).get("writes") or []):
            path_str = raw.replace("{appName}", app_name) if app_name else raw
            candidate = project_root / path_str
            if path_str.endswith("/") and candidate.is_dir():
                for p in sorted(candidate.rglob("*")):
                    if p.is_file() and p.suffix in SCANNED_EXTENSIONS:
                        rel = str(p.relative_to(project_root))
                        files[rel] = _file_checksum(p)
            elif candidate.is_file():
                rel = str(candidate.relative_to(project_root))
                files[rel] = _file_checksum(candidate)
    return files


def compute_phase_input_hash(
    project_root: Path, spec: dict, state: dict, phase: str
) -> tuple[str, dict]:
    """Return (hash, manifest) for a phase."""
    app_name = state.get("appName") or ""
    manifest = {
        "idea": {k: state.get(k) for k in IDEA_FIELDS},
        "specSlice": {
            "phase": (spec.get("phases") or {}).get(str(phase)),
            "gate": (spec.get("gates") or {}).get(
                ((spec.get("phases") or {}).get(str(phase)) or {}).get("gate", "")
            ),
        },
        "ownedFiles": _owned_files(spec, phase, app_name, project_root),
    }
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False, default=str)
    return _sha(canonical), manifest


def should_skip_phase(
    project_root: Path,
    spec: dict,
    state: dict,
    phase: str,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    if force:
        return False, "force flag set"

    phase_block = ((state.get("phases") or {}).get(str(phase)) or {})
    status = phase_block.get("status")
    if status not in {"completed", "fallback"}:
        return False, f"phase status is {status!r}, not terminal-success"

    stored = phase_block.get("inputHash")
    if not stored:
        return False, "no stored inputHash — re-run to populate"

    fresh, _ = compute_phase_input_hash(project_root, spec, state, phase)
    if fresh != stored:
        return False, f"inputHash mismatch (stored={stored}, fresh={fresh})"

    return True, f"inputs unchanged (hash {fresh})"


def mark_inputs(state: dict, phase: str, *, hash_value: str, manifest: dict) -> None:
    block = state.setdefault("phases", {}).setdefault(str(phase), {})
    block["inputHash"] = hash_value
    block["inputManifest"] = {
        "ownedFileCount": len(manifest.get("ownedFiles") or {}),
        "idea": manifest.get("idea"),
    }


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("compute", "should-skip"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        p.add_argument("--phase", required=True)
        if name == "should-skip":
            p.add_argument("--force", action="store_true")
    args = parser.parse_args()

    from spec_loader import load_spec
    from state_store import load_state, state_file_from_args

    spec = load_spec()
    state_args = argparse.Namespace(project_dir=args.project_dir, state_file=None)
    state = load_state(state_file_from_args(state_args))
    proj = Path(args.project_dir).resolve()

    if args.cmd == "compute":
        h, manifest = compute_phase_input_hash(proj, spec, state, args.phase)
        print(json.dumps({"hash": h, "ownedFileCount": len(manifest["ownedFiles"])}, ensure_ascii=False, indent=2))
        return 0

    skip, reason = should_skip_phase(proj, spec, state, args.phase, force=args.force)
    print(json.dumps({"skip": skip, "reason": reason}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
