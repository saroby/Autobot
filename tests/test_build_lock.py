"""Tests for scripts/build_lock.py — the (previously unimplemented) build lock.

Covers acquire/release/status, stale-lock reclaim, concurrent rejection, and
explicit same-build takeover for resume.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import IsolatedProjectCase, import_runtime_modules, run_pipeline

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

    def _seed_lock(self, *, pid: int, build_id: str, token: str = "seed-token") -> None:
        self._lock().write_text(json.dumps({
            "pid": pid,
            "buildId": build_id,
            "lockToken": token,
        }))

    # ── acquire ──

    def test_acquire_writes_lock_with_pid_and_build(self):
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok, reason)
        data = json.loads(self._lock().read_text())
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["buildId"], "build-A")
        self.assertIn("acquiredAt", data)
        self.assertIn("leaseExpiresAt", data)

    def test_cli_acquire_remains_live_after_acquiring_process_exits(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(build_lock.__file__)),
                "acquire",
                "--project-dir",
                str(self.proj),
                "--build-id",
                "build-A",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        lock_status = build_lock.status(self.proj)
        self.assertTrue(lock_status["holderAlive"], lock_status)
        self.assertFalse(lock_status["stale"], lock_status)

        contender = subprocess.run(
            [
                sys.executable,
                str(Path(build_lock.__file__)),
                "acquire",
                "--project-dir",
                str(self.proj),
                "--build-id",
                "build-B",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(contender.returncode, 2, contender.stdout)
        self.assertIn("another build is already running", contender.stdout)

        released = subprocess.run(
            [
                sys.executable,
                str(Path(build_lock.__file__)),
                "release",
                "--project-dir",
                str(self.proj),
                "--build-id",
                "build-A",
                "--expected-token",
                str(lock_status["lockToken"]),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(build_lock.status(self.proj), {"locked": False})

    def test_cli_json_acquire_returns_owned_generation_atomically(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(build_lock.__file__)),
                "acquire",
                "--project-dir", str(self.proj),
                "--build-id", "build-A",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["lockToken"], build_lock.status(self.proj)["lockToken"])

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

    def test_acquire_reclaims_expired_lease_even_if_recorded_pid_is_live(self):
        self._lock().write_text(
            json.dumps(
                {
                    "pid": FOREIGN_ALIVE_PID,
                    "buildId": "crashed-build",
                    "acquiredAt": "2000-01-01T00:00:00Z",
                    "leaseExpiresAt": "2000-01-01T01:00:00Z",
                }
            )
        )
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok, reason)
        self.assertIn("reclaimed stale", reason)
        self.assertEqual(json.loads(self._lock().read_text())["buildId"], "build-A")

    def test_acquire_same_build_different_process_requires_explicit_takeover(self):
        self._seed_lock(pid=FOREIGN_ALIVE_PID, build_id="build-A")
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertFalse(ok, reason)
        ok, reason = build_lock.acquire(
            self.proj,
            "build-A",
            takeover_same_build=True,
            expected_token="seed-token",
        )
        self.assertTrue(ok, reason)
        self.assertIn("takeover", reason)
        self.assertEqual(json.loads(self._lock().read_text())["pid"], os.getpid())

    def test_same_build_takeover_rejects_stale_compare_and_swap_token(self):
        ok, reason = build_lock.acquire(self.proj, "build-A")
        self.assertTrue(ok, reason)
        stale_token = build_lock.status(self.proj)["lockToken"]
        ok, reason = build_lock.acquire(
            self.proj,
            "build-A",
            takeover_same_build=True,
            expected_token=stale_token,
        )
        self.assertTrue(ok, reason)
        ok, reason = build_lock.acquire(
            self.proj,
            "build-A",
            takeover_same_build=True,
            expected_token=stale_token,
        )
        self.assertFalse(ok)
        self.assertIn("token changed", reason)

    def test_acquire_same_process_different_build_is_blocked(self):
        build_lock.acquire(self.proj, "build-A")
        ok, reason = build_lock.acquire(self.proj, "build-B")
        self.assertFalse(ok, reason)
        self.assertIn("already running", reason)

    def test_two_processes_cannot_acquire_the_same_unlocked_project(self):
        start = self.proj / "start"
        code = (
            "import pathlib,sys,time; import build_lock; "
            "root=pathlib.Path(sys.argv[1]); start=pathlib.Path(sys.argv[2]); "
            "\nwhile not start.exists(): time.sleep(0.001)\n"
            "ok,_=build_lock.acquire(root, sys.argv[3]); raise SystemExit(0 if ok else 2)"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(build_lock.__file__).parent)
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(self.proj), str(start), build_id],
                env=env,
            )
            for build_id in ("build-A", "build-B")
        ]
        start.touch()
        returncodes = sorted(process.wait(timeout=10) for process in processes)
        self.assertEqual(returncodes, [0, 2])

    # ── renew ──

    def test_renew_extends_lease_and_preserves_token(self):
        build_lock.acquire(self.proj, "build-A")
        before = json.loads(self._lock().read_text())
        # Backdate the lease so the extension is observable.
        before["leaseExpiresAt"] = "2000-01-01T00:00:00Z"
        self._lock().write_text(json.dumps(before))

        ok, reason = build_lock.renew(self.proj, "build-A")
        self.assertTrue(ok, reason)
        after = json.loads(self._lock().read_text())
        self.assertEqual(after["lockToken"], before["lockToken"])
        self.assertEqual(after["acquiredAt"], before["acquiredAt"])
        self.assertGreater(after["leaseExpiresAt"], before["leaseExpiresAt"])

        ok, reason = build_lock.renew(self.proj, "build-B")
        self.assertFalse(ok)
        self.assertIn("buildId", reason)

    # ── release ──

    def test_release_removes_own_lock(self):
        build_lock.acquire(self.proj, "build-A")
        token = build_lock.status(self.proj)["lockToken"]
        ok, reason = build_lock.release(
            self.proj, "build-A", expected_token=token
        )
        self.assertTrue(ok, reason)
        self.assertFalse(self._lock().exists())

    def test_superseded_owner_cannot_release_new_generation(self):
        build_lock.acquire(self.proj, "build-A")
        old_token = build_lock.status(self.proj)["lockToken"]
        build_lock.acquire(
            self.proj,
            "build-A",
            takeover_same_build=True,
            expected_token=old_token,
        )
        ok, _ = build_lock.release(
            self.proj, "build-A", expected_token=old_token
        )
        self.assertFalse(ok)
        self.assertTrue(self._lock().exists())

    def test_terminal_summary_cannot_supersede_live_generation(self):
        build_lock.acquire(self.proj, "build-A")
        old_token = build_lock.status(self.proj)["lockToken"]
        build_lock.acquire(
            self.proj,
            "build-A",
            takeover_same_build=True,
            expected_token=old_token,
        )
        new_token = build_lock.status(self.proj)["lockToken"]
        summary = self.proj / "artifacts" / "build-A" / "run-summary.json"
        summary.parent.mkdir(parents=True)
        summary.write_text("{}")
        ok, reason = build_lock.acquire(self.proj, "build-B")
        self.assertFalse(ok, reason)
        self.assertEqual(build_lock.status(self.proj)["lockToken"], new_token)

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


class TestLeaseHeartbeat(IsolatedProjectCase):
    """start-phase must renew the lock lease so long builds keep protection."""

    def test_start_phase_renews_lease(self):
        lock_path = self.project_dir / ".autobot" / "build.lock"
        data = json.loads(lock_path.read_text())
        data["leaseExpiresAt"] = "2000-01-01T00:00:00Z"
        lock_path.write_text(json.dumps(data))

        result = run_pipeline("start-phase", "--phase", "1", project_dir=self.project_dir)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

        renewed = json.loads(lock_path.read_text())
        self.assertGreater(renewed["leaseExpiresAt"], "2000-01-01T00:00:00Z")
        self.assertEqual(renewed["lockToken"], data["lockToken"])


class TestInitStateLockLeak(unittest.TestCase):
    """init-state must not exit holding the lock when schema validation fails."""

    def test_failed_schema_validation_does_not_leak_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            bad = run_pipeline(
                "init-build", "--build-id", "build-X",
                "--app-name", "badName", "--display-name", "Bad",
                project_dir=proj,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(
                (proj / ".autobot" / "build.lock").exists(),
                "failed init must not leave the build lock behind",
            )
            # The corrected retry with the SAME build-id and no --force must work.
            good = run_pipeline(
                "init-build", "--build-id", "build-X",
                "--app-name", "GoodName", "--display-name", "Good",
                project_dir=proj,
            )
            self.assertEqual(good.returncode, 0, msg=good.stdout + good.stderr)


if __name__ == "__main__":
    unittest.main()
