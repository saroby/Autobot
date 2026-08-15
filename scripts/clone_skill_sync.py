#!/usr/bin/env python3
"""Detect and repair drift between the clone skill SSOT and an installed plugin.

The repository copy is authoritative while developing Autobot. Plugin caches are
versioned, so this tool refuses to copy a 0.13.9 skill into a 0.13.8 package: a
matching package must be installed first. That keeps a convenient local repair
from creating a mixed-version plugin whose prose promises scripts it does not
ship.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


DEFAULT_CACHE_ROOT = (
    Path.home() / ".codex" / "plugins" / "cache" / "saroby-marketplace" / "autobot"
)
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_contract(repo: Path) -> tuple[str, Path]:
    metadata = repo / ".claude-plugin" / "plugin.json"
    skill = repo / "skills" / "autobot-clone-app" / "SKILL.md"
    if not metadata.is_file():
        raise ValueError(f"missing plugin metadata: {metadata}")
    if not skill.is_file():
        raise ValueError(f"missing clone skill SSOT: {skill}")
    try:
        version = json.loads(metadata.read_text(encoding="utf-8"))["version"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid plugin version in {metadata}: {exc}") from exc
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"invalid plugin version in {metadata}")
    return version, skill


def installed_skill(cache_root: Path, version: str) -> Path:
    return cache_root / version / "skills" / "autobot-clone-app" / "SKILL.md"


def installed_versions(cache_root: Path) -> list[str]:
    if not cache_root.is_dir():
        return []
    return sorted(
        path.name
        for path in cache_root.iterdir()
        if (path / "skills" / "autobot-clone-app" / "SKILL.md").is_file()
    )


def referenced_scripts(skill: Path) -> list[str]:
    """Return the script contract named by the skill prose, deterministically."""
    text = skill.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"scripts/([A-Za-z0-9_.-]+)", text)))


def runtime_drift(repo: Path, installed_root: Path, skill: Path) -> list[str]:
    drift: list[str] = []
    for name in referenced_scripts(skill):
        source = repo / "scripts" / name
        target = installed_root / "scripts" / name
        if not source.is_file():
            drift.append(f"repo-missing:{name}")
        elif not target.is_file():
            drift.append(f"installed-missing:{name}")
        elif digest(source) != digest(target):
            drift.append(f"mismatch:{name}")
    return drift


def check(repo: Path, cache_root: Path) -> int:
    version, source = repo_contract(repo)
    target = installed_skill(cache_root, version)
    if not target.is_file():
        found = ", ".join(installed_versions(cache_root)) or "none"
        print(
            f"ERROR: Autobot {version} is the repository SSOT, but that plugin version is not "
            f"installed (installed: {found}). Install/reload {version} before running clone; "
            "do not mix a new skill with old scripts.",
            file=sys.stderr,
        )
        return 1
    runtime = runtime_drift(repo, cache_root / version, source)
    if runtime:
        preview = ", ".join(runtime[:5]) + (" ..." if len(runtime) > 5 else "")
        print(
            f"ERROR: clone runtime drift for Autobot {version}: {preview}. "
            "Install/reload the matching plugin package; copying prose alone would promise "
            "scripts that are absent or stale.",
            file=sys.stderr,
        )
        return 1
    source_hash, target_hash = digest(source), digest(target)
    if source_hash != target_hash:
        print(
            f"ERROR: clone skill drift for Autobot {version}: repo={source_hash[:12]} "
            f"installed={target_hash[:12]}. Run clone_skill_sync.py sync after reviewing "
            "the repository changes.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: clone skill {version} matches installed plugin ({source_hash[:12]})")
    return 0


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, source.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def sync(repo: Path, cache_root: Path) -> int:
    version, source = repo_contract(repo)
    target = installed_skill(cache_root, version)
    if not target.is_file():
        found = ", ".join(installed_versions(cache_root)) or "none"
        print(
            f"ERROR: refusing mixed-version sync: target plugin {version} is not installed "
            f"(installed: {found}). Install the matching package first.",
            file=sys.stderr,
        )
        return 1
    runtime = runtime_drift(repo, cache_root / version, source)
    if runtime:
        preview = ", ".join(runtime[:5]) + (" ..." if len(runtime) > 5 else "")
        print(
            f"ERROR: refusing prose-only sync because clone runtime differs: {preview}. "
            "Install/reload the matching plugin package first.",
            file=sys.stderr,
        )
        return 1
    if digest(source) == digest(target):
        print(f"OK: clone skill {version} already synchronized")
        return 0
    atomic_copy(source, target)
    print(f"OK: synchronized clone skill {version} -> {target}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("mode", choices=("check", "sync"))
    result.add_argument("--repo", type=Path, default=DEFAULT_REPO_ROOT)
    result.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return {"check": check, "sync": sync}[args.mode](
            args.repo.resolve(), args.cache_root.expanduser().resolve()
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
