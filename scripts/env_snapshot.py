#!/usr/bin/env python3
"""Cache the chosen iOS simulator UDID so every phase that boots a sim reuses
the same device. That's the only piece of `xcrun simctl list` worth caching —
everything else (Xcode version, SDK, fastlane presence) is a single cheap
shell call and trying to "cache" it just creates staleness bugs.

Schema (`.autobot/env_snapshot.json`):
    {
      "capturedAt": "2026-05-26T12:00:00Z",
      "simulator": {"udid": "...", "name": "iPhone 16 Pro", "runtime": "iOS 26.0"}
    }

If the cached UDID no longer appears in `simctl list devices`, capture()
re-picks. That's the only invalidation rule we need.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_PATH = ".autobot/env_snapshot.json"
DEFAULT_DEVICE_NAME = "iPhone 16 Pro"


def _run(cmd: list[str], *, timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def _parse_runtime_version(runtime: str) -> tuple[int, ...]:
    """Parse an iOS runtime id/label into a comparable version tuple.

    Accepts both the simctl identifier
    (``com.apple.CoreSimulator.SimRuntime.iOS-26-2``) and the human label
    (``iOS 26.0``). Returns ``()`` when no iOS version is present so non-iOS or
    unparseable runtimes sort lowest.
    """
    m = re.search(r"iOS[ -]?(\d+(?:[.\-]\d+)*)", runtime)
    if not m:
        return ()
    return tuple(int(part) for part in re.split(r"[.\-]", m.group(1)))


def select_simulator_from_listing(
    data: dict,
    *,
    min_runtime: tuple[int, ...] | None = None,
    preferred_name: str = DEFAULT_DEVICE_NAME,
) -> dict | None:
    """Choose a simulator from a parsed ``simctl list devices --json`` payload.

    Selection priority, highest first:
      1. iPhones are preferred over other device classes.
      2. The HIGHEST iOS runtime wins. Runtime version dominates the device
         name because an app built for iOS 26 cannot install on an iOS 18 sim
         even when the name matches. ``simctl`` lists runtimes in an arbitrary
         order, so the old "first device that matches the name" logic silently
         landed on whatever runtime happened to come first (an iOS-18 sim on
         hosts that keep old runtimes around) — this function exists to prevent
         that.
      3. ``preferred_name`` breaks ties within the chosen runtime.

    ``min_runtime`` (e.g. the app's deployment target as a version tuple)
    filters out runtimes too old to install the build. Returns ``None`` when
    nothing qualifies.
    """
    best: dict | None = None
    best_key: tuple | None = None
    for runtime, devices in (data.get("devices") or {}).items():
        if "iOS" not in runtime:
            continue
        version = _parse_runtime_version(runtime)
        if min_runtime is not None and version < min_runtime:
            continue
        for device in devices or []:
            if not device.get("isAvailable", False):
                continue
            name = device.get("name", "")
            is_iphone = 1 if name.startswith("iPhone") else 0
            is_preferred = 1 if name == preferred_name else 0
            key = (is_iphone, version, is_preferred)
            if best_key is None or key > best_key:
                best_key = key
                best = {"udid": device.get("udid"), "name": name, "runtime": runtime}
    return best


def _global_config_target() -> tuple[int, ...] | None:
    """deploymentTarget from the global setup config (``~/.autobot/config.json``)
    — the source the scaffold itself defaults from. Used when the per-build
    state has not recorded a target."""
    cfg = Path(os.path.expanduser("~/.autobot/config.json"))
    if not cfg.is_file():
        return None
    try:
        target = json.loads(cfg.read_text(encoding="utf-8")).get("deploymentTarget")
    except (json.JSONDecodeError, OSError):
        return None
    if not target:
        return None
    return _parse_runtime_version(f"iOS {target}") or None


def deployment_floor(project_root: Path | None) -> tuple[int, ...] | None:
    """The build's deployment target (e.g. ``26.0``) as a version tuple, so
    simulator selection never lands on a runtime too old to install the app.

    Resolution order: the per-build ``build-state.json`` (SSOT for this build),
    then the global setup config. Returns ``None`` when neither records one.
    """
    if project_root is not None:
        state = project_root / ".autobot" / "build-state.json"
        if state.is_file():
            try:
                target = json.loads(state.read_text(encoding="utf-8")).get("deploymentTarget")
            except (json.JSONDecodeError, OSError):
                target = None
            if target:
                return _parse_runtime_version(f"iOS {target}") or None
    return _global_config_target()


def _pick_simulator(min_runtime: tuple[int, ...] | None = None) -> dict | None:
    if shutil.which("xcrun") is None:
        return None
    rc, out = _run(["xcrun", "simctl", "list", "devices", "available", "--json"], timeout=30)
    if rc != 0:
        return None
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return None
    return select_simulator_from_listing(data, min_runtime=min_runtime)


def _detect_axe() -> tuple[bool, str | None]:
    """Phase-0 preflight: is the AXe UI-automation CLI installed?

    AXe (https://github.com/cameroncooke/AXe) is what flow_runner uses to drive
    functional flows. When it is absent, functional_flows_pass degrades rather
    than hard-fails, so recording availability here lets the operator see *why*
    the gate degraded without re-shelling out at gate time.
    """
    if shutil.which("axe") is None:
        return False, None
    rc, out = _run(["axe", "--version"], timeout=10)
    if rc != 0:
        return True, None
    return True, (out.strip() or None)


def _udid_still_available(udid: str) -> bool:
    if shutil.which("xcrun") is None:
        return False
    rc, out = _run(["xcrun", "simctl", "list", "devices", "available"])
    return rc == 0 and udid in out


def load(project_root: Path) -> dict | None:
    path = project_root / SNAPSHOT_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def capture(project_root: Path) -> dict:
    axe_present, axe_version = _detect_axe()
    snapshot = {
        "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "simulator": _pick_simulator(min_runtime=deployment_floor(project_root)),
        "environment": {
            "axe": axe_present,
            "axeVersion": axe_version,
        },
    }
    path = project_root / SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def ensure(project_root: Path) -> dict:
    """Return a fresh snapshot. Re-captures when the cached UDID is gone, or when
    the cached runtime is too old for the deployment target."""
    snapshot = load(project_root)
    if snapshot is None:
        return capture(project_root)
    sim = snapshot.get("simulator") or {}
    udid = sim.get("udid")
    if not udid or not _udid_still_available(udid):
        return capture(project_root)
    # Re-pick when the cached runtime predates the deployment target. Without
    # this a stale snapshot (e.g. an iOS-18 sim cached for an iOS-26 app, from
    # the old version-blind picker) would survive forever, since its UDID is
    # still "available" — quietly defeating the runtime smoke + axe flow.
    floor = deployment_floor(project_root)
    if floor is not None and _parse_runtime_version(sim.get("runtime", "")) < floor:
        return capture(project_root)
    return snapshot


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("capture", "load", "ensure"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    fn = {"capture": capture, "load": load, "ensure": ensure}[args.cmd]
    result = fn(proj)
    print(json.dumps(result, ensure_ascii=False, indent=2) if result is not None else "null")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
