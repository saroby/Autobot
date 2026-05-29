#!/usr/bin/env python3
"""Build lock — at most one Autobot build per project directory at a time.

SKILL.md has long advertised `.autobot/build.lock` ("Phase 0 acquire, Phase 7
release, PID 유효성 자동 확인"), but no code implemented it — the string only
appeared in `fileOwnership.forbiddenInfra` and the sandbox diff-ignore set.
This module is that implementation.

Guarantees:
  - acquire() refuses to start when another *live* build (different buildId
    whose holder PID is still alive) already holds the lock — preventing two
    concurrent builds from corrupting one `.autobot/` via interleaved writes.
  - A stale lock (holder PID is dead) is reclaimed automatically, so a crashed
    build never wedges the directory. This is the real correctness guarantee:
    even if release() is never called, the next build reclaims the lock.
  - Re-acquiring for the SAME buildId (resume from another process) or from the
    SAME process (re-init, the test suite) is idempotent.
  - release() removes the lock on clean shutdown; an unreadable or stale lock is
    cleared too.

Lock file is single-line JSON: {"pid": int, "buildId": str, "acquiredAt": iso}.
Written atomically (tmp + os.replace) so a partial lock is never observed.

CLI:
    build_lock.py acquire --build-id <id> [--project-dir .]
    build_lock.py release [--build-id <id>] [--force] [--project-dir .]
    build_lock.py status [--project-dir .]
exit 0 → success / allow; exit 2 → blocked (a live build holds the lock).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_store import utc_now  # noqa: E402

LOCK_REL = ".autobot/build.lock"


def _lock_path(project_root: Path) -> Path:
    return project_root / LOCK_REL


def _pid_alive(pid) -> bool:
    """True if `pid` names a live process. PermissionError means the process
    exists but is owned by another user → still alive."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_lock(path: Path, build_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": os.getpid(), "buildId": build_id, "acquiredAt": utc_now()}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def acquire(project_root: Path, build_id: str) -> tuple[bool, str]:
    """Acquire the build lock for `build_id`. Returns (ok, reason)."""
    path = _lock_path(project_root)
    existing = _read_lock(path) if path.exists() else None
    if existing is not None:
        holder_pid = existing.get("pid")
        holder_build = existing.get("buildId")
        if holder_pid == os.getpid():
            _write_lock(path, build_id)
            return True, "reacquired (same process)"
        if holder_build == build_id:
            _write_lock(path, build_id)
            return True, f"reacquired (same build '{build_id}')"
        if _pid_alive(holder_pid):
            return False, (
                f"another build is already running: buildId='{holder_build}' "
                f"pid={holder_pid}. Wait for it to finish or stop it before "
                f"starting '{build_id}'."
            )
        _write_lock(path, build_id)
        return True, f"reclaimed stale lock (dead pid {holder_pid}, was '{holder_build}')"
    _write_lock(path, build_id)
    return True, f"acquired for '{build_id}'"


def release(project_root: Path, build_id: str | None = None, *, force: bool = False) -> tuple[bool, str]:
    """Release the build lock. Removes it when held by this process, this
    buildId, when forced, or when stale. Refuses to remove a lock held by a
    different *live* build unless --force. Returns (ok, reason)."""
    path = _lock_path(project_root)
    if not path.exists():
        return True, "no lock to release"
    existing = _read_lock(path)
    if existing is None:
        path.unlink(missing_ok=True)
        return True, "removed unreadable lock"
    holder_pid = existing.get("pid")
    holder_build = existing.get("buildId")
    if force or holder_pid == os.getpid() or (build_id is not None and holder_build == build_id):
        path.unlink(missing_ok=True)
        return True, "released"
    if not _pid_alive(holder_pid):
        path.unlink(missing_ok=True)
        return True, f"released stale lock (dead pid {holder_pid})"
    return False, (
        f"lock held by another live build (buildId='{holder_build}' pid={holder_pid}); "
        "not releasing. Use --force to override."
    )


def status(project_root: Path) -> dict:
    path = _lock_path(project_root)
    if not path.exists():
        return {"locked": False}
    data = _read_lock(path) or {}
    pid = data.get("pid")
    alive = _pid_alive(pid)
    return {
        "locked": True,
        "pid": pid,
        "buildId": data.get("buildId"),
        "acquiredAt": data.get("acquiredAt"),
        "holderAlive": alive,
        "stale": not alive,
    }


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_acq = sub.add_parser("acquire")
    p_acq.add_argument("--project-dir", default=".")
    p_acq.add_argument("--build-id", required=True)
    p_rel = sub.add_parser("release")
    p_rel.add_argument("--project-dir", default=".")
    p_rel.add_argument("--build-id")
    p_rel.add_argument("--force", action="store_true")
    p_st = sub.add_parser("status")
    p_st.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "acquire":
        ok, reason = acquire(proj, args.build_id)
        print(("OK: " if ok else "BLOCKED: ") + reason)
        return 0 if ok else 2
    if args.cmd == "release":
        ok, reason = release(proj, args.build_id, force=args.force)
        print(("OK: " if ok else "BLOCKED: ") + reason)
        return 0 if ok else 2
    print(json.dumps(status(proj), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
