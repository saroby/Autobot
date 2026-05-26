#!/usr/bin/env python3
"""Phase 7 self-check: verify Axiom health-check was attempted (or properly skipped).

Phase 7 has no gate, so this script is the contract enforcer. The retrospective
skill must invoke it before flipping phases.7 status to completed.

Pass conditions (any one):
  - environment.axiom == false AND ≥1 axiom_audit_skipped event for phase 7
  - environment.axiom == true  AND phases.7.metadata.axiom_health_check.ran == true
                              AND findingsPath (if set) exists on disk

Exit 0 on pass, 1 on fail with a human-readable reason on stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    project_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    state_path = project_dir / ".autobot" / "build-state.json"
    log_path = project_dir / ".autobot" / "build-log.jsonl"

    if not state_path.is_file():
        print(f"FATAL: build-state.json not found at {state_path}", file=sys.stderr)
        return 1

    state = json.loads(state_path.read_text())
    env = state.get("environment", {})
    axiom_installed = env.get("axiom") is True

    p7_meta = state.get("phases", {}).get("7", {}).get("metadata", {})
    health = p7_meta.get("axiom_health_check") or {}

    if not axiom_installed:
        # Require at least one axiom_audit_skipped event for phase 7 so the skip
        # is auditable rather than silent forgetfulness.
        if not log_path.is_file():
            print("FAIL: environment.axiom=false but build-log.jsonl missing", file=sys.stderr)
            return 1
        skip_seen = False
        for line in log_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("event") == "axiom_audit_skipped" and str(evt.get("phase")) == "7":
                skip_seen = True
                break
        if not skip_seen:
            print("FAIL: environment.axiom=false but no axiom_audit_skipped event "
                  "recorded for phase 7 — retrospective must log the skip explicitly",
                  file=sys.stderr)
            return 1
        print("OK: axiom not installed; skip event recorded for phase 7")
        return 0

    # Axiom installed: health-check must have run.
    if not health.get("ran"):
        print("FAIL: environment.axiom=true but phases.7.metadata.axiom_health_check.ran "
              "is not true — autobot-axiom-bridge Mode 2 must run during retrospective",
              file=sys.stderr)
        return 1

    findings_path_str = health.get("findings_path") or health.get("findingsPath")
    if findings_path_str:
        findings_path = project_dir / findings_path_str
        if not findings_path.exists():
            print(f"FAIL: axiom_health_check.findings_path={findings_path_str} "
                  "does not exist on disk", file=sys.stderr)
            return 1

    print(f"OK: axiom health-check ran; findings at {findings_path_str or '<inline>'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
