#!/bin/bash
# Append a structured event to .autobot/build-log.jsonl
# Usage:
#   bash build-log.sh --phase 1 --event start
#   bash build-log.sh --phase 1 --event start --detail "architect dispatch"
#   bash build-log.sh --phase 5 --event build_attempt --detail '{"attempt":1,"errors":8}'
#   bash build-log.sh --phase 4 --event agent_dispatch --agent ui-builder --detail "parallel start"
set -euo pipefail

PHASE=""
EVENT=""
DETAIL=""
AGENT=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)     PHASE="$2";       shift 2 ;;
    --event)     EVENT="$2";       shift 2 ;;
    --detail)    DETAIL="$2";      shift 2 ;;
    --agent)     AGENT="$2";       shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$EVENT" || -z "$PHASE" ]]; then
  echo "Usage: build-log.sh --phase <N> --event <name> [--detail <text>] [--agent <name>]" >&2
  exit 1
fi

LOG_DIR="${PROJECT_DIR}/.autobot"
LOG_FILE="${LOG_DIR}/build-log.jsonl"
mkdir -p "$LOG_DIR"

TS=$(date -u +%FT%TZ)

# Build JSON line using python3 for proper escaping
python3 -c "
import json, sys

entry = {'ts': sys.argv[1], 'event': sys.argv[2]}
if sys.argv[3]: entry['phase'] = int(sys.argv[3])
if sys.argv[4]: entry['agent'] = sys.argv[4]
if sys.argv[5]:
    # Try to parse detail as JSON, fall back to string
    try:
        entry['detail'] = json.loads(sys.argv[5])
    except (json.JSONDecodeError, ValueError):
        entry['detail'] = sys.argv[5]

print(json.dumps(entry, ensure_ascii=False))
" "$TS" "$EVENT" "$PHASE" "$AGENT" "$DETAIL" >> "$LOG_FILE"
