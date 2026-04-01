#!/bin/bash
# Record filesystem state before/after agent execution to verify file ownership rules.
# Usage:
#   bash agent-sandbox.sh before --agent ui-builder --app-name "AppName" [--project-dir .]
#   (run agent)
#   bash agent-sandbox.sh after  --agent ui-builder --app-name "AppName" [--project-dir .]
set -euo pipefail

MODE=""
AGENT=""
APP_NAME=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    before|after) MODE="$1"; shift ;;
    --agent)      AGENT="$2";    shift 2 ;;
    --app-name)   APP_NAME="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$MODE" || -z "$AGENT" || -z "$APP_NAME" ]]; then
  echo "Usage: agent-sandbox.sh <before|after> --agent <name> --app-name <AppName> [--project-dir <dir>]" >&2
  exit 1
fi

SANDBOX_DIR="${PROJECT_DIR}/.autobot/sandbox"
SNAPSHOT_FILE="${SANDBOX_DIR}/${AGENT}.before.json"

write_snapshot() {
  local output_file="$1"

  python3 - "$PROJECT_DIR" "$APP_NAME" "$output_file" <<'PY'
import hashlib
import json
import os
import sys

project_dir, app_name, output_file = sys.argv[1:4]
roots = [
    os.path.join(project_dir, app_name),
    os.path.join(project_dir, "backend"),
    os.path.join(project_dir, ".autobot"),
]

snapshot = {}
for root in roots:
    if not os.path.isdir(root):
        continue
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "sandbox"]
        for file_name in files:
            path = os.path.join(current_root, file_name)
            rel_path = os.path.relpath(path, project_dir)
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            snapshot[rel_path] = digest

with open(output_file, "w", encoding="utf-8") as handle:
    json.dump(snapshot, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
PY
}

case "$MODE" in
  before)
    mkdir -p "$SANDBOX_DIR"
    write_snapshot "$SNAPSHOT_FILE"
    echo "snapshot_saved: ${SNAPSHOT_FILE}"
    ;;

  after)
    if [[ ! -f "$SNAPSHOT_FILE" ]]; then
      echo "ERROR: No 'before' snapshot found for agent '${AGENT}'. Refusing to skip sandbox verification." >&2
      exit 2
    fi

    AFTER_FILE="${SANDBOX_DIR}/${AGENT}.after.json"
    write_snapshot "$AFTER_FILE"

    python3 - "$AGENT" "$APP_NAME" "$SNAPSHOT_FILE" "$AFTER_FILE" <<'PY'
import json
import sys

agent, app_name, before_path, after_path = sys.argv[1:5]

with open(before_path, encoding="utf-8") as handle:
    before = json.load(handle)
with open(after_path, encoding="utf-8") as handle:
    after = json.load(handle)

created = sorted(path for path in after if path not in before)
deleted = sorted(path for path in before if path not in after)
modified = sorted(path for path in after if path in before and after[path] != before[path])
touched = created + modified + deleted

ownership = {
    "ui-builder": [
        f"{app_name}/Views/",
        f"{app_name}/ViewModels/",
        f"{app_name}/App/",
        f"{app_name}/Assets.xcassets/",
        f"{app_name}/Utilities/Theme.swift",
    ],
    "data-engineer": [f"{app_name}/Services/", f"{app_name}/Utilities/"],
    "backend-engineer": ["backend/"],
    "ux-designer": [".autobot/designs/", ".autobot/design-spec.md"],
    "quality-engineer": [],
}

# Models/ is always forbidden for all agents.
# Pipeline control files are forbidden for non-orchestrator agents.
forbidden_always = [f"{app_name}/Models/"]
forbidden_infra = [
    ".autobot/build-state.json",
    ".autobot/architecture.md",
    ".autobot/contracts/",
    ".autobot/build-log.jsonl",
    ".autobot/build.lock",
    ".autobot/learnings.json",
    ".autobot/active-learnings.md",
    ".autobot/phase-learnings/",
]

# Per-agent forbidden: prevents ownership overlap conflicts.
forbidden_per_agent = {
    "data-engineer": [f"{app_name}/Utilities/Theme.swift"],
    "ui-builder": [f"{app_name}/Services/"],
}

violations = []
allowed_dirs = ownership.get(agent, [])
agent_forbidden = forbidden_per_agent.get(agent, [])

for path in touched:
    # Check always-forbidden (Models/)
    if any(path.startswith(f) or f"/{f}" in path for f in forbidden_always):
        violations.append(f"FORBIDDEN: {agent} touched Models/ → {path}")
        continue

    # Check infrastructure files (all agents)
    if any(path.startswith(f) for f in forbidden_infra):
        violations.append(f"INFRA: {agent} touched pipeline control file → {path}")
        continue

    # Check per-agent forbidden
    if any(path.startswith(f) or path == f for f in agent_forbidden):
        violations.append(f"OVERLAP: {agent} touched another agent's file → {path}")
        continue

    # Check allowlist (skip for quality-engineer which has broad access)
    if agent != "quality-engineer" and allowed_dirs:
        if not any(path.startswith(allowed) or path == allowed for allowed in allowed_dirs):
            violations.append(f"OWNERSHIP: {agent} touched outside allowed dirs → {path}")

# quality-engineer: broad access but still can't touch Models/ or infra
# (already checked above for all agents)

if violations:
    for violation in violations:
        print(f"VIOLATION: {violation}")
    print(
        f"SUMMARY: {agent} — {len(created)} created, {len(modified)} modified, "
        f"{len(deleted)} deleted, {len(violations)} violations"
    )
    sys.exit(1)

print(
    f"OK: {agent} — {len(created)} created, {len(modified)} modified, "
    f"{len(deleted)} deleted, 0 violations"
)
PY

    # Cleanup
    rm -f "$SNAPSHOT_FILE" "$AFTER_FILE"
    ;;
esac
