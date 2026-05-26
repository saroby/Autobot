#!/usr/bin/env bash
# Detect the current AI runtime and the opposite peer reviewer.
#
# Contract:
#   host=codex  -> peer=claude
#   host=claude -> peer=codex
#   host=unknown -> peer=unknown
#
# This script only detects and reports. Invocation policy lives in
# skills/autobot-peer-review-bridge/SKILL.md so the runtime engine stays small.

set -euo pipefail

HOST="auto"
FORMAT="env"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --format) FORMAT="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

detect_host() {
  if [[ "$HOST" != "auto" ]]; then
    printf '%s\n' "$HOST"
    return
  fi

  if [[ -n "${CODEX_THREAD_ID:-}" || -n "${CODEX_CI:-}" || -n "${CODEX_SANDBOX:-}" ]]; then
    printf 'codex\n'
    return
  fi

  if [[ -n "${CLAUDECODE:-}" || -n "${CLAUDE_CODE_ENTRYPOINT:-}" || -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    printf 'claude\n'
    return
  fi

  printf 'unknown\n'
}

command_available() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1
}

RUNTIME_HOST="$(detect_host)"
case "$RUNTIME_HOST" in
  codex)
    PEER_AI="claude"
    if command_available claude; then
      PEER_AVAILABLE="true"
      PEER_COMMAND="$(command -v claude)"
    else
      PEER_AVAILABLE="false"
      PEER_COMMAND=""
    fi
    ;;
  claude)
    PEER_AI="codex"
    if command_available codex; then
      PEER_AVAILABLE="true"
      PEER_COMMAND="$(command -v codex)"
    else
      PEER_AVAILABLE="false"
      PEER_COMMAND=""
    fi
    ;;
  *)
    PEER_AI="unknown"
    PEER_AVAILABLE="false"
    PEER_COMMAND=""
    ;;
esac

case "$FORMAT" in
  env)
    printf 'runtimeHost=%s\n' "$RUNTIME_HOST"
    printf 'peerAi=%s\n' "$PEER_AI"
    printf 'peerReviewAvailable=%s\n' "$PEER_AVAILABLE"
    if [[ -n "$PEER_COMMAND" ]]; then
      printf 'peerCommand=%s\n' "$PEER_COMMAND"
    fi
    ;;
  json)
    python3 - "$RUNTIME_HOST" "$PEER_AI" "$PEER_AVAILABLE" "$PEER_COMMAND" <<'PY'
import json
import sys

runtime_host, peer_ai, available, command = sys.argv[1:5]
print(json.dumps({
    "runtimeHost": runtime_host,
    "peerAi": peer_ai,
    "peerReviewAvailable": available == "true",
    "peerCommand": command,
}, ensure_ascii=False))
PY
    ;;
  *)
    echo "Unknown --format: $FORMAT" >&2
    exit 2
    ;;
esac
