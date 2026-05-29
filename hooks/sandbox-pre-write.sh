#!/bin/bash
# PreToolUse hook — block Write/Edit/NotebookEdit file-mutation calls that fall
# outside the active agent's `spec/pipeline.json.fileOwnership` rules.
#
# Scope: structured file editors only. `Bash` writes (mv/cp/sed -i/redirection)
# are NOT seen here — they are caught post-hoc by sandbox_runner.py at Gate 4→5.
# The forbidden floor (Models/ + .autobot control files) is enforced for every
# agent, including broadAccess, via sandbox_guard.py → evaluate_violations.
#
# Trigger contract (Claude Code hook spec):
#   stdin → JSON: { "tool_name": "Write|Edit|...", "tool_input": { ... } }
#   exit 0 → allow
#   exit 2 → block (stderr is shown to the user)
#
# This script is intentionally opt-in: it is only registered when a build is
# actively running (`.autobot/.guard-active` exists). Outside a build the hook
# returns immediately so it never interferes with regular plugin development.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER="${PROJECT_DIR}/.autobot/.guard-active"

# Hook is a no-op when no build is running.
if [[ ! -f "$MARKER" ]]; then
  exit 0
fi

# Read the entire PreToolUse payload from stdin.
PAYLOAD="$(cat -)"

# Extract tool name and the target path. We grep for the common shapes used by
# Write / Edit / NotebookEdit / Bash so we don't need to depend on jq.
TOOL_NAME="$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    print(d.get('tool_name', ''))
except Exception:
    print('')
")"

# Only inspect mutating tools.
case "$TOOL_NAME" in
  Write|Edit|NotebookEdit) ;;
  *) exit 0 ;;
esac

TARGET="$(printf '%s' "$PAYLOAD" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    inp = d.get('tool_input', {}) or {}
    # Write: file_path  / Edit: file_path  / NotebookEdit: notebook_path
    print(inp.get('file_path') or inp.get('notebook_path') or '')
except Exception:
    print('')
")"

if [[ -z "$TARGET" ]]; then
  exit 0
fi

# Resolve against the project dir if the path is relative.
case "$TARGET" in
  /*) ABS_TARGET="$TARGET" ;;
  *)  ABS_TARGET="${PROJECT_DIR}/${TARGET}" ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${SCRIPT_DIR}/../scripts/sandbox_guard.py"

if [[ ! -f "$GUARD" ]]; then
  # If the guard tool went missing don't block — fail-open with a single
  # diagnostic to stderr so the user notices the misconfiguration.
  echo "WARN: sandbox_guard.py not found at ${GUARD} — allowing write" >&2
  exit 0
fi

if RESULT="$(python3 "$GUARD" check --project-dir "$PROJECT_DIR" --target "$ABS_TARGET" 2>&1)"; then
  exit 0
fi

# `check` exited non-zero → block the tool call.
echo "${RESULT}" >&2
echo "HINT: clear the marker with 'python3 scripts/sandbox_guard.py clear-active' if you need to bypass." >&2
exit 2
