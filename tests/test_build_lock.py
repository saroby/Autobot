"""Tests for scripts/build_lock.py — the (previously unimplemented) build lock.

Covers acquire/release/status, stale-lock reclaim via PID liveness, concurrent
build rejection, and idempotent same-build / same-process re-acquire.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import build_lock  # noqa: E402

# A PID that is effectively never live, and one that is always live but not ours.
DEAD_PID = 2147483647          # 2**31 - 1 — no such process
FOREIGN_ALIVE_PID = 1          # launchd/init — alive, owned by another user


class TestBuildLock(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _lock(self) -> Path:
        return self.proj / ".autobot" / "build.lock"

    def _seed_lock(self, *, pid: int, build_id: str) -> None:
        self._lock().write_text(json.dumps({"pid": pid, "buildId": build_id}))

    # ── acquire ──

    def test_acquire_writes_lock_with_pid_and_build(self):
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok, reason)
        data = json.loads(self._lock().read_text())
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["buildId"], "build-A")
        self.assertIn("acquiredAt", data)

    def test_acquire_blocks_when_live_foreign_build_holds_lock(self):
        self._seed_lock(pid=FOREIGN_ALIVE_PID, build_id="other-build")
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertFalse(ok)
        self.assertIn("already running", reason)
        # The foreign lock must be left intact.
        self.assertEqual(json.loads(self._lock().read_text())["buildId"], "other-build")

    def test_acquire_reclaims_stale_lock(self):
        self._seed_lock(pid=DEAD_PID, build_id="crashed-build")
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok)
        self.assertIn("reclaimed stale", reason)
        self.assertEqual(json.loads(self._lock().read_text())["buildId"], "build-A")

    def test_acquire_same_build_different_process_reacquires(self):
        self._seed_lock(pid=FOREIGN_ALIVE_PID, build_id="build-A")
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok, reason)
        self.assertIn("same build", reason)
        self.assertEqual(json.loads(self._lock().read_text())["pid"], os.getpid())

    def test_acquire_same_process_reacquires(self):
        build_lock.acquire(self.proj, "build-A")
        ok, reason = build_lock.acquire(self.proj, "build-B")  # same process
        self.assertTrue(ok, reason)
        self.assertIn("same process", reason)

    # ── release ──

    def test_release_removes_own_lock(self):
        build_lock.acquire(self.proj, "build-A")
        ok, reason = build_lock.release(self.proj, "build-A")
        self.assertTrue(ok, reason)
        self.assertFalse(self._lock().exists())

    def test_release_no_lock_is_ok(self):
        ok, reason = build_lock.release(self.proj, "build-A")
        self.assertTrue(ok)
        self.assertIn("no lock", reason)

    def test_release_refuses_foreign_live_lock_without_force(self):
        self._seed_lock(pid=FOREIGN_ALIVE_PID, build_id="other-build")
        ok, reason = build_lock.release(self.proj, "build-A")
        self.assertFalse(ok)
        self.assertTrue(self._lock().exists(), "must not remove a live foreign lock")

    def test_release_force_removes_foreign_live_lock(self):
        self._seed_lock(pid=FOREIGN_ALIVE_PID, build_id="other-build")
        ok, _ = build_lock.release(self.proj, "build-A", force=True)
        self.assertTrue(ok)
        self.assertFalse(self._lock().exists())

    def test_release_removes_stale_lock(self):
        self._seed_lock(pid=DEAD_PID, build_id="crashed-build")
        ok, reason = build_lock.release(self.proj)
        self.assertTrue(ok)
        self.assertIn("stale", reason)
        self.assertFalse(self._lock().exists())

    # ── status ──

    def test_status_unlocked(self):
        self.assertEqual(build_lock.status(self.proj), {"locked": False})

    def test_status_reports_stale(self):
        self._seed_lock(pid=DEAD_PID, build_id="crashed-build")
        st = build_lock.status(self.proj)
        self.assertTrue(st["locked"])
        self.assertTrue(st["stale"])
        self.assertFalse(st["holderAlive"])


if __name__ == "__main__":
    unittest.main()
