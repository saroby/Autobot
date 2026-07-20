#!/usr/bin/env python3
"""Structured readiness checks for local build and App Store shipping."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from release_environment import load_release_environment


@dataclass(frozen=True)
class Probe:
    name: str
    status: str
    reason: str
    evidence: str
    remediation: str


def _command(name: str, argv: list[str], *, required: bool = True) -> Probe:
    path = shutil.which(argv[0])
    if not path:
        return Probe(name, "fail" if required else "warn", f"{argv[0]} not found", "", f"Install {argv[0]} and ensure it is on PATH.")
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Probe(name, "fail" if required else "warn", str(exc), path, f"Repair {argv[0]} and retry.")
    lines = (result.stdout or result.stderr).strip().splitlines()
    evidence = lines[0] if lines else path
    if result.returncode != 0:
        return Probe(name, "fail" if required else "warn", f"exit {result.returncode}", evidence, f"Run {' '.join(argv)} manually and resolve the error.")
    return Probe(name, "pass", "available", evidence, "")


def release_environment(project: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    return load_release_environment(project, env)


def credential_probe(project: Path, *, env: dict[str, str] | None = None) -> Probe:
    values = release_environment(project, env)
    required = ("ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_KEY_PATH")
    missing = [name for name in required if not values.get(name)]
    if missing:
        return Probe("asc_credentials", "fail", f"missing {', '.join(missing)}", "", "Run /autobot:setup or set the three ASC_API_* values in .env.")
    key_path = Path(values["ASC_API_KEY_PATH"]).expanduser()
    if not key_path.is_file() or not os.access(key_path, os.R_OK):
        return Probe("asc_credentials", "fail", "ASC_API_KEY_PATH is not a readable file", str(key_path), "Point ASC_API_KEY_PATH at the readable App Store Connect .p8 key.")
    try:
        key = key_path.read_text(encoding="utf-8")
    except OSError as exc:
        return Probe("asc_credentials", "fail", str(exc), str(key_path), "Fix key file permissions.")
    if "BEGIN PRIVATE KEY" not in key:
        return Probe("asc_credentials", "fail", "key file is not a PEM private key", str(key_path), "Download the original App Store Connect API .p8 key and update ASC_API_KEY_PATH.")
    return Probe("asc_credentials", "pass", "configured", f"keyId={values['ASC_API_KEY_ID']}, issuer={values['ASC_API_ISSUER_ID']}, path={key_path}", "")


def simulator_probe(*, required: bool) -> Probe:
    path = shutil.which("xcrun")
    if not path:
        return Probe("simulator", "fail" if required else "warn", "xcrun not found", "", "Install Xcode command line tools.")
    try:
        result = subprocess.run(["xcrun", "simctl", "list", "devices", "available", "-j"], text=True, capture_output=True, timeout=20, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        count = sum(len(devices) for devices in (data.get("devices") or {}).values())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        count = 0
    if count == 0:
        return Probe("simulator", "fail" if required else "warn", "no available simulator", "0 devices", "Install an iOS Simulator runtime in Xcode Settings > Platforms.")
    return Probe("simulator", "pass", "available", f"{count} devices", "")


def codesign_probe() -> Probe:
    # codesign has no version subcommand; presence on PATH is all we can probe.
    path = shutil.which("codesign")
    if not path:
        return Probe("codesign", "fail", "codesign not found", "", "Install Xcode command line tools.")
    return Probe("codesign", "pass", "available", path, "")


def disk_probe(project: Path, *, required: bool) -> Probe:
    gib = shutil.disk_usage(project).free / (1024 ** 3)
    if gib < 1:
        status, reason = ("fail" if required else "warn"), "less than 1 GiB free"
    elif gib < 5:
        status, reason = "warn", "low disk space"
    else:
        status, reason = "pass", "sufficient"
    return Probe("disk", status, reason, f"{gib:.1f} GiB free", "Free at least 5 GiB for DerivedData/archive artifacts." if status != "pass" else "")


def summarize(profile: str, probes: list[Probe]) -> dict:
    statuses = {probe.status for probe in probes}
    status = "blocked" if "fail" in statuses else "degraded" if "warn" in statuses else "ready"
    return {"schemaVersion": 1, "profile": profile, "status": status, "checks": [asdict(probe) for probe in probes]}


def run_doctor(project: Path, profile: str) -> dict:
    ship = profile == "ship"
    checks = [
        lambda: _command("xcode", ["xcodebuild", "-version"]),
        lambda: _command("ios_sdk", ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"]),
        lambda: simulator_probe(required=True),
        lambda: _command("axe", ["axe", "--version"], required=False),
        lambda: _command("xcodegen", ["xcodegen", "--version"], required=False),
        lambda: disk_probe(project, required=ship),
    ]
    if ship:
        checks.extend([
            lambda: _command("fastlane", ["fastlane", "--version"]),
            lambda: credential_probe(project),
            codesign_probe,
        ])
    with ThreadPoolExecutor(max_workers=len(checks)) as executor:
        probes = list(executor.map(lambda check: check(), checks))
    return summarize(profile, probes)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--profile", choices=("local", "ship"), default="local")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args()
    result = run_doctor(Path(args.project_dir).resolve(), args.profile)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Autobot doctor [{result['profile']}]: {result['status']}")
        for check in result["checks"]:
            print(f"- {check['status'].upper():4} {check['name']}: {check['reason']} ({check['evidence']})")
            if check["remediation"]:
                print(f"       Fix: {check['remediation']}")
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(_main())
