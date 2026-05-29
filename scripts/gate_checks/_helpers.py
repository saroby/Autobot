"""Shared helpers used by every gate_checks domain module.

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"

from spec_loader import resolve_app_template  # noqa: E402

def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_spec() -> dict[str, Any]:
    try:
        return load_json(SPEC_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FATAL: cannot load pipeline spec: {exc}") from exc


def _ok(
    check: str, passed: bool, message: str, *,
    skipped: bool = False, degraded: bool = False,
) -> dict[str, Any]:
    r: dict[str, Any] = {"check": check, "passed": passed, "message": message}
    if skipped:
        r["skipped"] = True
    if degraded:
        r["degraded"] = True
    return r


def _file_exists(path: Path, label: str) -> dict[str, Any]:
    return _ok(label, path.is_file(), f"{path}")


def _dir_exists(path: Path, label: str) -> dict[str, Any]:
    return _ok(label, path.is_dir(), f"{path}/")


def _dir_has_swift(
    directory: Path, label: str, *, min_count: int = 1, recursive: bool = False,
) -> dict[str, Any]:
    """Count .swift files in *directory*.

    Set *recursive*=True when subdirectories like ``Views/Components/`` are
    legitimate organization (rather than a sandbox violation). Recursive callers
    still report the top-level dir name in the message so output stays readable.
    """
    if not directory.is_dir():
        matches: list[Path] = []
    elif recursive:
        matches = sorted(directory.rglob("*.swift"))
    else:
        matches = sorted(directory.glob("*.swift"))
    return _ok(label, len(matches) >= min_count, f"{len(matches)} .swift in {directory.name}/")


def _file_nonempty(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        return _ok(label, False, f"MISSING: {path}")
    return _ok(label, path.stat().st_size > 0, f"{path.name} ({path.stat().st_size} bytes)")


def _file_grep(
    path: Path, pattern: str, label: str, *, expect: bool = True,
) -> dict[str, Any]:
    if not path.is_file():
        return _ok(label, False, f"MISSING: {path.name}")
    content = path.read_text(encoding="utf-8", errors="replace")
    found = bool(re.search(pattern, content, re.IGNORECASE))
    passed = found if expect else not found
    verb = "matched" if found else "no match"
    return _ok(label, passed, f"{verb} /{pattern}/ in {path.name}")


def _run_cmd(cmd: list[str], *, timeout: int = 10) -> tuple[bool, str]:
    """Run a shell command and return (success, output)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except FileNotFoundError:
        return False, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout}s"


def _markdown_heading_present(content: str, title_pattern: str) -> bool:
    return bool(re.search(rf"(?im)^#+\s+{title_pattern}\s*$", content))


def _agent_writes_dirs(spec: dict, agent: str, app: str) -> list[str]:
    """Return the directories (paths ending '/') that the agent owns per spec."""
    cfg = spec.get("fileOwnership", {}).get("agents", {}).get(agent, {})
    return [resolve_app_template(p, app) for p in cfg.get("writes", []) if p.endswith("/")]
