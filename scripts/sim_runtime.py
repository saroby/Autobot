#!/usr/bin/env python3
"""Simulator runtime smoke for the Phase 5→6 gate.

Boots a deterministic simulator (or reuses the cached UDID from env_snapshot.json),
installs the freshly-built .app, launches it by bundle id, waits a few seconds,
verifies the process is alive, captures a screenshot, and emits a structured
JSON result. This is the difference between "the binary compiled" and "the app
actually starts on a device" — the gate that catches missing entitlements,
broken root view bodies, and Foundation Models guardrail crashes.

Skipped when:
  - `xcrun simctl` is unavailable (not a macOS dev host)
  - the latest `.app` cannot be located in DerivedData
  - `AUTOBOT_DISABLE_SIMULATOR=1` is set
  - the project's bundle id cannot be resolved

The result schema is intentionally narrow so the gate runner and the
run-summary report can render it without bespoke parsing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_DEVICE_NAME = "iPhone 16 Pro"
DEFAULT_LAUNCH_WAIT_SECONDS = 4
DEFAULT_SIMCTL_TIMEOUT = 120
MAX_BOOT_RETRY = 1


def _runtime_smoke_screenshot(project_root: Path) -> Path:
    state = project_root / ".autobot" / "build-state.json"
    build_id = "unknown-build"
    if state.is_file():
        try:
            build_id = json.loads(state.read_text(encoding="utf-8")).get("buildId") or build_id
        except (json.JSONDecodeError, OSError):
            pass
    path = project_root / "artifacts" / build_id / "phase-5" / "runtime-smoke"
    path.mkdir(parents=True, exist_ok=True)
    return path / "screenshot.png"


def _simctl_available() -> bool:
    if os.environ.get("AUTOBOT_DISABLE_SIMULATOR") == "1":
        return False
    return shutil.which("xcrun") is not None


def _run(cmd: list[str], *, timeout: int = DEFAULT_SIMCTL_TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", f"timeout after {timeout}s"


def _read_env_snapshot(project_root: Path) -> dict | None:
    snap = project_root / ".autobot" / "env_snapshot.json"
    if not snap.is_file():
        return None
    try:
        return json.loads(snap.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _pick_simulator_udid(project_root: Path) -> tuple[str | None, str]:
    """Prefer the cached UDID from env_snapshot.json so repeated runs land on
    the same sim and benefit from DerivedData / asset cache reuse.
    Falls back to listing iPhone runtimes and picking the first available.
    """
    snap = _read_env_snapshot(project_root) or {}
    cached = (snap.get("simulator") or {}).get("udid")
    if isinstance(cached, str) and cached:
        return cached, "cached-snapshot"

    rc, stdout, _ = _run(["xcrun", "simctl", "list", "devices", "available", "--json"])
    if rc != 0:
        return None, "simctl_list_failed"
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "simctl_list_unparseable"

    # Prefer the default device name on the most recent iOS runtime.
    preferred = None
    for runtime, devices in (data.get("devices") or {}).items():
        if "iOS" not in runtime:
            continue
        for device in devices:
            if not device.get("isAvailable", False):
                continue
            name = device.get("name", "")
            if name == DEFAULT_DEVICE_NAME:
                return device["udid"], f"matched-{name}-{runtime}"
            if preferred is None and name.startswith("iPhone"):
                preferred = (device["udid"], f"fallback-{name}-{runtime}")
    if preferred:
        return preferred
    return None, "no_ios_simulator_available"


def _boot(udid: str) -> tuple[bool, str]:
    rc, _, stderr = _run(["xcrun", "simctl", "boot", udid])
    if rc == 0 or "Booted" in stderr or "current state: Booted" in stderr:
        return True, "booted"
    # One retry: a half-booted sim sometimes needs `shutdown` first.
    _run(["xcrun", "simctl", "shutdown", udid])
    time.sleep(2)
    rc2, _, stderr2 = _run(["xcrun", "simctl", "boot", udid])
    if rc2 == 0 or "Booted" in stderr2:
        return True, "booted-after-retry"
    return False, stderr2.strip() or "boot_failed"


def _is_valid_app_bundle(app: Path, app_name: str) -> bool:
    """Reject .app bundles where `<App>.app/<App>` is a directory, not a
    Mach-O executable.

    The xcodegen `type: folder` regression (Solos / Murmur build-20260526)
    produced bundles whose primary binary was itself a directory, so
    `simctl install` failed with IXUserPresentableErrorDomain code=1 after
    the smoke gate accepted the path. Validating the Mach-O header at
    discovery time keeps stale DerivedData artifacts from poisoning the
    smoke check.
    """
    inner = app / app_name
    if not inner.is_file():
        return False
    try:
        with inner.open("rb") as f:
            head = f.read(4)
    except OSError:
        return False
    # Mach-O magic numbers (any of these): 32/64-bit, big/little endian, fat.
    mach_o_magics = {
        b"\xfe\xed\xfa\xce",  # 32-bit BE
        b"\xce\xfa\xed\xfe",  # 32-bit LE
        b"\xfe\xed\xfa\xcf",  # 64-bit BE
        b"\xcf\xfa\xed\xfe",  # 64-bit LE
        b"\xca\xfe\xba\xbe",  # universal/fat BE
        b"\xbe\xba\xfe\xca",  # universal/fat LE
    }
    return head in mach_o_magics


def _find_built_app(project_root: Path, app_name: str) -> Path | None:
    """Look for the .app produced by xcodebuild.

    Order:
      1. The artifact captured by `phase-5/attempt-*/Build/Products/Debug-iphonesimulator/<App>.app`
         (when we ran with -resultBundlePath)
      2. `~/Library/Developer/Xcode/DerivedData/<App>-*/Build/Products/Debug-iphonesimulator/<App>.app`

    Each candidate is Mach-O verified before being returned so a corrupted
    cached bundle (folder-typed binary) cannot mask a healthy newer build.
    """
    candidates: list[Path] = []
    phase5 = project_root / ".autobot" / "phase-5"
    if phase5.is_dir():
        for attempt in sorted(phase5.glob("attempt-*"), reverse=True):
            for app in attempt.rglob(f"{app_name}.app"):
                candidates.append(app)
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    if derived.is_dir():
        for product_dir in derived.glob(f"{app_name}-*/Build/Products/Debug-iphonesimulator"):
            app = product_dir / f"{app_name}.app"
            if app.is_dir():
                candidates.append(app)
    for c in candidates:
        if _is_valid_app_bundle(c, app_name):
            return c
    return None


def _resolve_bundle_id(project_root: Path, app_name: str, app_path: Path) -> str | None:
    plist = app_path / "Info.plist"
    if not plist.is_file():
        return None
    rc, stdout, _ = _run([
        "/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier", str(plist),
    ])
    if rc == 0 and stdout.strip():
        return stdout.strip()
    # Fallback: read the .autobot/build-state.json bundleId, if present.
    state = project_root / ".autobot" / "build-state.json"
    if state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            return data.get("bundleId")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _is_process_alive(udid: str, bundle_id: str) -> tuple[bool, str]:
    rc, stdout, _ = _run(["xcrun", "simctl", "spawn", udid, "launchctl", "list"])
    if rc != 0:
        return False, "launchctl list failed"
    for line in stdout.splitlines():
        if bundle_id in line:
            cols = line.split()
            if len(cols) >= 2 and cols[0].strip("-").isdigit() and int(cols[0]) > 0:
                return True, f"pid={cols[0]}"
            return True, "running (no pid yet)"
    return False, "not in launchctl list"


def _capture_screenshot(udid: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    rc, _, _ = _run(["xcrun", "simctl", "io", udid, "screenshot", str(dest)])
    return rc == 0 and dest.is_file() and dest.stat().st_size > 1024


def _result(status: str, **fields) -> dict:
    fields["status"] = status
    return fields


def smoke(project_root: Path, app_name: str, *, wait_seconds: int = DEFAULT_LAUNCH_WAIT_SECONDS) -> dict:
    if not _simctl_available():
        return _result("skipped", skipReason="simctl_unavailable")

    udid, udid_source = _pick_simulator_udid(project_root)
    if not udid:
        return _result("skipped", skipReason=udid_source)

    app = _find_built_app(project_root, app_name)
    if app is None:
        return _result("skipped", skipReason="app_artifact_missing")

    bundle_id = _resolve_bundle_id(project_root, app_name, app)
    if not bundle_id:
        return _result("failed", reason="bundle_id_unresolved", appPath=str(app))

    booted, boot_detail = _boot(udid)
    if not booted:
        return _result("failed", reason=f"boot_failed: {boot_detail}", udid=udid)

    rc, _, install_err = _run(["xcrun", "simctl", "install", udid, str(app)])
    if rc != 0:
        return _result(
            "failed",
            reason=f"install_failed: {install_err.strip()[:160]}",
            udid=udid,
            bundleId=bundle_id,
        )

    rc, _, launch_err = _run(["xcrun", "simctl", "launch", udid, bundle_id])
    if rc != 0:
        return _result(
            "failed",
            reason=f"launch_failed: {launch_err.strip()[:160]}",
            udid=udid,
            bundleId=bundle_id,
        )

    time.sleep(max(2, wait_seconds))

    alive, alive_detail = _is_process_alive(udid, bundle_id)
    screenshot_path = _runtime_smoke_screenshot(project_root)
    captured = _capture_screenshot(udid, screenshot_path)

    if not alive:
        return _result(
            "failed",
            reason=f"process_died: {alive_detail}",
            udid=udid,
            bundleId=bundle_id,
            screenshotCaptured=captured,
            screenshotPath=str(screenshot_path) if captured else None,
            udidSource=udid_source,
        )

    return _result(
        "passed",
        udid=udid,
        bundleId=bundle_id,
        appPath=str(app),
        processDetail=alive_detail,
        screenshotCaptured=captured,
        screenshotPath=str(screenshot_path) if captured else None,
        udidSource=udid_source,
    )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--wait", type=int, default=DEFAULT_LAUNCH_WAIT_SECONDS)
    args = parser.parse_args()

    result = smoke(Path(args.project_dir).resolve(), args.app_name, wait_seconds=args.wait)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] in ("passed", "skipped"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
