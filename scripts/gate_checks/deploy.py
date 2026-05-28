"""Deployment attempt recording (TestFlight handoff).

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from spec_loader import resolve_app_template  # noqa: E402

from ._helpers import (
    load_json,
    load_spec,
    _ok,
    _file_exists,
    _dir_exists,
    _dir_has_swift,
    _file_nonempty,
    _file_grep,
    _run_cmd,
    _markdown_heading_present,
    _agent_writes_dirs
)


def check_deployment_attempt_recorded(proj: Path, app: str, state: dict) -> list[dict]:
    deploy = proj / ".autobot" / "deploy-status.json"
    results = [_file_exists(deploy, "deploy_status_file")]
    if deploy.is_file():
        try:
            data = load_json(deploy)
            has_result = "archive_path" in data or "upload_success" in data
            results.append(_ok("deploy_has_result", has_result, "has archive_path or upload_success" if has_result else "missing result fields"))
        except (json.JSONDecodeError, OSError):
            results.append(_ok("deploy_has_result", False, "deploy-status.json parse error"))
    return results
