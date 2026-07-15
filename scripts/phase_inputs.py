#!/usr/bin/env python3
"""Shared phase dependency and file-manifest helpers.

Both resume hashing and agent context construction must agree on which
transitive upstream outputs a phase consumes. Keeping that traversal here
prevents either surface from silently weakening the dependency contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

SCANNED_EXTENSIONS = (
    ".swift", ".json", ".md", ".plist", ".xcprivacy", ".entitlements",
    ".yml", ".yaml", ".pbxproj",
)


def transitive_upstream(phases: dict, start: str) -> list[str]:
    seen: set[str] = set()
    stack = [str(value) for value in ((phases.get(str(start)) or {}).get("dependencies") or [])]
    while stack:
        phase = stack.pop()
        if phase in seen or phase not in phases:
            continue
        seen.add(phase)
        stack.extend(
            str(value)
            for value in ((phases.get(phase) or {}).get("dependencies") or [])
        )
    return sorted(seen, key=lambda value: (len(value), value))


def phase_output_files(
    spec: dict,
    phase: str,
    app_name: str,
    project_root: Path,
    *,
    include_upstream: bool = False,
) -> dict[str, str]:
    """Return deterministic path→checksum entries for a phase's outputs.

    When ``include_upstream`` is true, outputs from the complete dependency
    closure are returned and the phase's own outputs are excluded.
    """
    phases = spec.get("phases") or {}
    ownership = (spec.get("fileOwnership") or {}).get("agents") or {}
    phase_ids = transitive_upstream(phases, str(phase)) if include_upstream else [str(phase)]
    files: dict[str, str] = {}

    for phase_id in phase_ids:
        agents = list((phases.get(phase_id) or {}).get("agents") or [])
        if not agents and phase_id == "3" and not include_upstream:
            agents = ["quality-engineer"]
        for agent in agents:
            for raw in (ownership.get(agent, {}).get("writes") or []):
                relative = raw.replace("{appName}", app_name) if app_name else raw
                candidate = project_root / relative.rstrip("/")
                if relative.endswith("/") and candidate.is_dir():
                    for path in sorted(candidate.rglob("*")):
                        if path.is_file() and path.suffix in SCANNED_EXTENSIONS:
                            files[str(path.relative_to(project_root))] = file_checksum(path)
                elif candidate.is_file():
                    files[str(candidate.relative_to(project_root))] = file_checksum(candidate)
    return files


def file_checksum(path: Path, *, length: int = 16) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:length]
    except OSError:
        return "unreadable"
