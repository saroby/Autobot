#!/usr/bin/env python3
"""Build lock — at most one Autobot build per project directory at a time.

SKILL.md has long advertised `.autobot/build.lock` ("Phase 0 acquire, Phase 7
release, PID 유효성 자동 확인"), but no code implemented it — the string only
appeared in `fileOwnership.forbiddenInfra` and the sandbox diff-ignore set.
This module is that implementation.

Guarantees:
  - acquire() refuses to start when another *live* build (different buildId
    whose lease has not expired) already holds the lock — preventing two
    concurrent builds from corrupting one `.autobot/` via interleaved writes.
  - The lease outlives the short-lived CLI process that acquired it. A stale
    lease is reclaimed automatically, so a crashed build does not wedge the
    directory forever. Legacy PID-only lock files remain readable.
  - Re-acquiring for the SAME buildId still blocks unless the resume path uses
    an explicit takeover flag. A coincident duplicate resume cannot silently
    masquerade as the existing owner.
  - Live release requires the current generation token (or explicit force),
    so a superseded session cannot unlock its successor. Run summaries are
    reports, not ownership proof.

Lock file is JSON with pid/buildId/lockToken/acquiredAt/leaseExpiresAt. Writes are
serialized through a companion flock and atomically replaced, so concurrent
acquirers cannot both win and a partial lock is never observed.

CLI:
    build_lock.py acquire --build-id <id> [--project-dir .]
    build_lock.py renew --build-id <id> [--project-dir .]
    build_lock.py release [--build-id <id>] [--expected-token <token>] [--force]
    build_lock.py status [--project-dir .]
exit 0 → success / allow; exit 2 → blocked (a live build holds the lock).
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_store import try_load_state, utc_now, write_json  # noqa: E402

LOCK_REL = ".autobot/build.lock"
DEFAULT_LEASE_SECONDS = 12 * 60 * 60


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
    return try_load_state(path)


def _lease_seconds() -> int:
    raw = os.environ.get("AUTOBOT_BUILD_LOCK_LEASE_SECONDS", "")
    try:
        value = int(raw) if raw else DEFAULT_LEASE_SECONDS
    except ValueError:
        return DEFAULT_LEASE_SECONDS
    return value if value > 0 else DEFAULT_LEASE_SECONDS


def _parse_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _lock_alive(data: dict) -> bool:
    """Lease-based liveness, with PID fallback for pre-lease lock files."""
    lease_expiry = _parse_timestamp(data.get("leaseExpiresAt"))
    if lease_expiry is not None:
        return lease_expiry > datetime.now(timezone.utc)
    return _pid_alive(data.get("pid"))


def _lock_active(project_root: Path, data: dict) -> bool:
    return _lock_alive(data)


@contextmanager
def _lock_guard(path: Path):
    """Serialize lock-file inspect/update operations across processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    guard_path = path.with_name(f".{path.name}.guard")
    with guard_path.open("a+", encoding="utf-8") as guard:
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)


def _write_lock(path: Path, build_id: str, *, acquired_at: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "pid": os.getpid(),
        "buildId": build_id,
        "lockToken": uuid.uuid4().hex,
        "acquiredAt": acquired_at or utc_now(),
        "leaseExpiresAt": (now + timedelta(seconds=_lease_seconds()))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    # state_store.write_json owns the unique-temp + atomic-replace primitive.
    write_json(path, payload)


def acquire_with_token(
    project_root: Path,
    build_id: str,
    *,
    takeover_same_build: bool = False,
    expected_token: str | None = None,
) -> tuple[bool, str, str | None]:
    """Acquire and atomically return the generation token that was written."""
    path = _lock_path(project_root)
    with _lock_guard(path):
        existing = _read_lock(path) if path.exists() else None
        if existing is not None:
            holder_pid = existing.get("pid")
            holder_build = existing.get("buildId")
            if holder_build == build_id:
                if _lock_active(project_root, existing) and not takeover_same_build:
                    return False, (
                        f"build '{build_id}' already has a live lease pid={holder_pid}; "
                        "use explicit same-build takeover only when resuming that run"
                    ), None
                if _lock_active(project_root, existing) and expected_token != existing.get("lockToken"):
                    return False, (
                        f"same-build takeover token changed for '{build_id}'; "
                        "another resume acquired the lease first"
                    ), None
                _write_lock(path, build_id, acquired_at=existing.get("acquiredAt"))
                return True, f"explicit same-build takeover for '{build_id}'", _read_lock(path).get("lockToken")
            if _lock_active(project_root, existing):
                return False, (
                    f"another build is already running: buildId='{holder_build}' "
                    f"pid={holder_pid}. Wait for it to finish or stop it before "
                    f"starting '{build_id}'."
                ), None
            _write_lock(path, build_id)
            return True, f"reclaimed stale lock (was '{holder_build}' pid={holder_pid})", _read_lock(path).get("lockToken")
        _write_lock(path, build_id)
        return True, f"acquired for '{build_id}'", _read_lock(path).get("lockToken")


def acquire(
    project_root: Path,
    build_id: str,
    *,
    takeover_same_build: bool = False,
    expected_token: str | None = None,
) -> tuple[bool, str]:
    """Acquire the build lock for `build_id`. Returns (ok, reason)."""
    ok, reason, _ = acquire_with_token(
        project_root,
        build_id,
        takeover_same_build=takeover_same_build,
        expected_token=expected_token,
    )
    return ok, reason


def renew(project_root: Path, build_id: str) -> tuple[bool, str]:
    """Extend the lease for the SAME buildId (heartbeat).

    A lease extension is not an ownership transfer, so a buildId match is
    sufficient — no lockToken required. pid/lockToken/acquiredAt are preserved;
    only leaseExpiresAt moves forward.

    Known limitation: renew cannot distinguish a replaced runner for the same
    buildId (no stable orchestrator PID/token is carried) — single active runner
    per buildId is assumed.
    """
    path = _lock_path(project_root)
    with _lock_guard(path):
        existing = _read_lock(path) if path.exists() else None
        if existing is None:
            return False, "no lock to renew"
        if existing.get("buildId") != build_id:
            return False, (
                f"lock held by buildId='{existing.get('buildId')}', not '{build_id}'"
            )
        payload = dict(existing)
        payload["leaseExpiresAt"] = (
            (datetime.now(timezone.utc) + timedelta(seconds=_lease_seconds()))
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
        write_json(path, payload)
        return True, f"lease renewed for '{build_id}'"


def renew_from_state(project_root: Path) -> None:
    """Best-effort heartbeat for phase-boundary callers (start/advance).

    Reads buildId from build-state.json so callers never carry LOCK_TOKEN.
    Swallows every failure — a missed renewal must not block phase progress.
    """
    try:
        state = try_load_state(project_root / ".autobot" / "build-state.json")
        build_id = (state or {}).get("buildId")
        if build_id:
            renew(project_root, str(build_id))
    except Exception:  # noqa: BLE001 — heartbeat only, never fatal
        pass


def release(
    project_root: Path,
    build_id: str | None = None,
    *,
    force: bool = False,
    expected_token: str | None = None,
) -> tuple[bool, str]:
    """Release by generation token, explicit force, or stale lease.

    A buildId or run-summary alone is not ownership proof. Returns (ok, reason).
    """
    path = _lock_path(project_root)
    with _lock_guard(path):
        if not path.exists():
            return True, "no lock to release"
        existing = _read_lock(path)
        if existing is None:
            path.unlink(missing_ok=True)
            return True, "removed unreadable lock"
        holder_pid = existing.get("pid")
        holder_build = existing.get("buildId")
        if force or (
            build_id is not None
            and holder_build == build_id
            and expected_token
            and expected_token == existing.get("lockToken")
        ):
            path.unlink(missing_ok=True)
            return True, "released"
        if not _lock_active(project_root, existing):
            path.unlink(missing_ok=True)
            return True, f"released stale lock (buildId='{holder_build}' pid={holder_pid})"
        return False, (
            f"lock held by another live build (buildId='{holder_build}' pid={holder_pid}); "
            "not releasing. Use --force to override."
        )


def status(project_root: Path) -> dict:
    path = _lock_path(project_root)
    with _lock_guard(path):
        if not path.exists():
            return {"locked": False}
        data = _read_lock(path) or {}
        pid = data.get("pid")
        alive = _lock_active(project_root, data)
        return {
            "locked": True,
            "pid": pid,
            "buildId": data.get("buildId"),
            "lockToken": data.get("lockToken"),
            "acquiredAt": data.get("acquiredAt"),
            "leaseExpiresAt": data.get("leaseExpiresAt"),
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
    p_acq.add_argument("--takeover-same-build", action="store_true")
    p_acq.add_argument("--expected-token")
    p_acq.add_argument("--format", choices=("text", "json"), default="text")
    p_ren = sub.add_parser("renew")
    p_ren.add_argument("--project-dir", default=".")
    p_ren.add_argument("--build-id", required=True)
    p_rel = sub.add_parser("release")
    p_rel.add_argument("--project-dir", default=".")
    p_rel.add_argument("--build-id")
    p_rel.add_argument("--force", action="store_true")
    p_rel.add_argument("--expected-token")
    p_st = sub.add_parser("status")
    p_st.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "acquire":
        ok, reason, lock_token = acquire_with_token(
            proj,
            args.build_id,
            takeover_same_build=args.takeover_same_build,
            expected_token=args.expected_token,
        )
        if args.format == "json":
            print(json.dumps({"ok": ok, "reason": reason, "lockToken": lock_token}))
        else:
            print(("OK: " if ok else "BLOCKED: ") + reason)
        return 0 if ok else 2
    if args.cmd == "renew":
        ok, reason = renew(proj, args.build_id)
        print(("OK: " if ok else "BLOCKED: ") + reason)
        return 0 if ok else 2
    if args.cmd == "release":
        ok, reason = release(
            proj,
            args.build_id,
            force=args.force,
            expected_token=args.expected_token,
        )
        print(("OK: " if ok else "BLOCKED: ") + reason)
        return 0 if ok else 2
    print(json.dumps(status(proj), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
