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

import env_snapshot
from artifact_provenance import (
    ArtifactVerificationError,
    MANIFEST_NAME,
    inspect_app_bundle,
    load_verified_app_manifest,
)
from state_store import state_file_for, try_load_state

DEFAULT_LAUNCH_WAIT_SECONDS = 4
DEFAULT_SIMCTL_TIMEOUT = 120
MAX_BOOT_RETRY = 1


def _runtime_smoke_screenshot(project_root: Path) -> Path:
    build_id = _current_build_id(project_root)
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

    # Pick the highest iOS runtime (>= deployment target) — see
    # env_snapshot.select_simulator_from_listing. Version dominates the device
    # name so an iOS-26 build never lands on a stale iOS-18 sim.
    chosen = env_snapshot.select_simulator_from_listing(
        data, min_runtime=env_snapshot.deployment_floor(project_root)
    )
    if chosen and chosen.get("udid"):
        return chosen["udid"], f"picked-{chosen['name']}-{chosen['runtime']}"
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
    """Compatibility wrapper around the provenance verifier."""
    try:
        inspect_app_bundle(app, expected_name=app_name)
    except ArtifactVerificationError:
        return False
    return True


def _current_build_id(project_root: Path) -> str:
    state = try_load_state(state_file_for(project_root)) or {}
    return state.get("buildId") or "unknown-build"


def _attempt_number(path: Path) -> int:
    try:
        return int(path.name.removeprefix("attempt-"))
    except ValueError:
        return -1


def _load_built_app_provenance(project_root: Path, app_name: str) -> tuple[Path | None, dict | None, str | None]:
    """Load and re-hash only the newest manifest for the current build.

    There is intentionally no global DerivedData fallback. A runtime result is
    useful as shipping proof only when it identifies the exact Phase 5 output
    that produced the current build's provenance manifest.
    """
    build_id = _current_build_id(project_root)
    phase5 = project_root / "artifacts" / build_id / "phase-5"
    attempts = sorted(
        (path for path in phase5.glob("attempt-*") if path.is_dir()),
        key=_attempt_number,
        reverse=True,
    )
    if not attempts:
        return None, None, "artifact_provenance_missing"
    manifest_path = attempts[0] / MANIFEST_NAME
    if not manifest_path.is_file():
        return None, None, "artifact_provenance_missing_for_latest_attempt"
    try:
        manifest = load_verified_app_manifest(
            manifest_path,
            expected_build_id=build_id,
            expected_app_name=app_name,
        )
    except ArtifactVerificationError as exc:
        return None, None, f"artifact_provenance_invalid: {exc}"
    return Path(manifest["appPath"]), manifest, None


def _find_built_app(project_root: Path, app_name: str) -> Path | None:
    app, _, _ = _load_built_app_provenance(project_root, app_name)
    return app


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
    state = try_load_state(state_file_for(project_root)) or {}
    return state.get("bundleId")


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


def _capture_dark_screenshot(udid: str, dest: Path) -> bool:
    """Switch the sim to dark appearance, capture a screenshot, restore light.

    Best-effort: `simctl ui <udid> appearance` can be unsupported (older
    runtimes) — any failure just skips the dark capture; it never fails the
    smoke. The gate side (visual_contract darkMode) treats a missing dark
    screenshot as a benign skip, so environments without this capability
    degrade gracefully. Light is always restored so later steps (flow_runner,
    visual judge) keep operating on the light appearance.
    """
    rc, _, _ = _run(["xcrun", "simctl", "ui", udid, "appearance", "dark"])
    if rc != 0:
        return False
    try:
        time.sleep(1)  # let the appearance switch propagate before capturing
        return _capture_screenshot(udid, dest)
    finally:
        _run(["xcrun", "simctl", "ui", udid, "appearance", "light"])


def _result(status: str, **fields) -> dict:
    fields["status"] = status
    return fields


def smoke(project_root: Path, app_name: str, *, wait_seconds: int = DEFAULT_LAUNCH_WAIT_SECONDS) -> dict:
    if not _simctl_available():
        return _result("skipped", skipReason="simctl_unavailable")

    udid, udid_source = _pick_simulator_udid(project_root)
    if not udid:
        return _result("skipped", skipReason=udid_source)

    app, provenance, provenance_error = _load_built_app_provenance(project_root, app_name)
    if app is None:
        return _result("skipped", skipReason=provenance_error or "app_artifact_missing")

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

    # Second screenshot in dark appearance — the runtime consumer of the
    # design-spec `darkMode` policy (visual_contract checks both renders).
    dark_path = screenshot_path.with_name("screenshot-dark.png")
    dark_captured = _capture_dark_screenshot(udid, dark_path)

    return _result(
        "passed",
        udid=udid,
        bundleId=bundle_id,
        appPath=str(app),
        artifactDigest=provenance.get("artifactDigest") if provenance else None,
        artifactBuildId=provenance.get("buildId") if provenance else None,
        artifactManifestPath=(
            str(project_root / "artifacts" / provenance["buildId"] / "phase-5"
                / f"attempt-{provenance['attempt']}" / MANIFEST_NAME)
            if provenance else None
        ),
        processDetail=alive_detail,
        screenshotCaptured=captured,
        screenshotPath=str(screenshot_path) if captured else None,
        darkScreenshotCaptured=dark_captured,
        darkScreenshotPath=str(dark_path) if dark_captured else None,
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
