#!/bin/bash
# Append a validated event to .autobot/build-log.jsonl
# All validation (event-name + required fields) lives in spec/pipeline.json
# under "logEvents" — runtime.py:append_build_log enforces it.
#
# Usage:
#   bash build-log.sh --phase 1 --event start
#   bash build-log.sh --phase 1 --event start --detail "architect dispatch"
#   bash build-log.sh --phase 5 --event build_attempt --detail '{"attempt":1,"errors":8,"succeeded":false}'
#   bash build-log.sh --phase 4 --event agent_dispatch --agent ui-builder --detail "parallel start"
set -euo pipefail

PHASE=""
EVENT=""
DETAIL=""
AGENT=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)       PHASE="$2";       shift 2 ;;
    --event)       EVENT="$2";       shift 2 ;;
    --detail)      DETAIL="$2";      shift 2 ;;
    --agent)       AGENT="$2";       shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$EVENT" ]]; then
  echo "Usage: build-log.sh --event <name> [--phase <N>] [--detail <text|json>] [--agent <name>]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

ARGS=(--project-dir "$PROJECT_DIR" --event "$EVENT")
[[ -n "$PHASE"  ]] && ARGS+=(--phase  "$PHASE")
[[ -n "$AGENT"  ]] && ARGS+=(--agent  "$AGENT")
[[ -n "$DETAIL" ]] && ARGS+=(--detail "$DETAIL")

exec python3 "$RUNTIME" append-log "${ARGS[@]}"
