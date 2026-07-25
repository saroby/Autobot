#!/usr/bin/env python3
"""Safe, shared release dotenv parsing for shell producers and doctor.

CLI formats: ``nul`` (shell consumers, raw values) and ``lines`` (diagnostics
only — sensitive values are masked so a casual run never dumps an ASC web
session cookie into transcripts/logs).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Canonical env names are the fastlane `app_store_connect_api_key` action's
# industry-standard names, so a working fastlane environment runs autobot as-is.
ALLOWED_KEYS = {
    "APP_STORE_CONNECT_API_KEY_KEY_ID",
    "APP_STORE_CONNECT_API_KEY_ISSUER_ID",
    "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH",
    "FASTLANE_SESSION",
    "FASTLANE_USER",
    "APPLE_ID",
    "DEVELOPMENT_TEAM",
    "TESTER_EMAIL",
}

# FASTLANE_SESSION is a 2FA-backed Apple ID web session cookie (~30 days).
SENSITIVE_KEYS = {"FASTLANE_SESSION"}


def parse_dotenv(path: Path, *, home: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.lstrip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key not in ALLOWED_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        value = value.replace("${HOME}", home).replace("$HOME", home)
        if value.startswith("~"):
            value = home + value[1:]
        values[key] = value
    return values


def load_release_environment(
    project: Path,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    source = dict(os.environ if env is None else env)
    home = source.get("HOME") or str(Path.home())
    config_dir = Path(source.get("AUTOBOT_CONFIG_DIR") or Path(home) / ".autobot")
    values = {key: source[key] for key in ALLOWED_KEYS if source.get(key)}
    for path in (project / ".env", config_dir / ".env"):
        for key, value in parse_dotenv(path, home=home).items():
            values.setdefault(key, value)
    return values


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--format", choices=("nul", "lines"), default="lines")
    args = parser.parse_args()
    values = load_release_environment(Path(args.project_dir).resolve())
    if args.format == "nul":
        for key in sorted(values):
            sys.stdout.buffer.write(key.encode() + b"\0" + values[key].encode() + b"\0")
    else:
        for key in sorted(values):
            value = "***" if key in SENSITIVE_KEYS else values[key]
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
