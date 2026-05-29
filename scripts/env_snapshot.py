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
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_PATH = ".autobot/env_snapshot.json"


def _run(cmd: list[str], *, timeout: int = 15) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def _pick_simulator() -> dict | None:
    if shutil.which("xcrun") is None:
        return None
    rc, out = _run(["xcrun", "simctl", "list", "devices", "available", "--json"], timeout=30)
    if rc != 0:
        return None
    try:
        data = json.loads(out or "{}")
    except json.JSONDecodeError:
        return None
    fallback: dict | None = None
    for runtime, devices in (data.get("devices") or {}).items():
        if "iOS" not in runtime:
            continue
        for device in devices:
            if not device.get("isAvailable", False):
                continue
            name = device.get("name", "")
            chosen = {"udid": device.get("udid"), "name": name, "runtime": runtime}
            if name == "iPhone 16 Pro":
                return chosen
            if fallback is None and name.startswith("iPhone"):
                fallback = chosen
    return fallback


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
        "simulator": _pick_simulator(),
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
    """Return a fresh snapshot. Only re-captures when the cached UDID is gone."""
    snapshot = load(project_root)
    if snapshot is None:
        return capture(project_root)
    udid = (snapshot.get("simulator") or {}).get("udid")
    if not udid or not _udid_still_available(udid):
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
