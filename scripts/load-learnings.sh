#!/bin/bash
# Emit a minimal Autobot session summary.
# SessionStart hook — keep prompt footprint small and defer detailed reads to build/resume time.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PLUGIN_ROOT:-.}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"

# ── Step 1: .env 파일 탐색 ──
ENV_FILE=""
if [ -f "${PROJECT_DIR}/.env" ]; then
  ENV_FILE="${PROJECT_DIR}/.env"
elif [ -f "${HOME}/.config/autobot/.env" ]; then
  ENV_FILE="${HOME}/.config/autobot/.env"
fi

env_has_key() {
  local key="$1"

  if [ -n "${!key:-}" ]; then
    return 0
  fi

  if [ -n "$ENV_FILE" ] && grep -Eq "^[[:space:]]*${key}=" "$ENV_FILE"; then
    return 0
  fi

  return 1
}

HAS_ENV="false"
if [ -n "$ENV_FILE" ]; then
  HAS_ENV="true"
fi

ASC_CONFIGURED="false"
if env_has_key "ASC_API_KEY_ID" && env_has_key "ASC_API_ISSUER_ID" && env_has_key "ASC_API_KEY_PATH"; then
  ASC_CONFIGURED="true"
elif env_has_key "APPLE_ID" && env_has_key "APP_SPECIFIC_PASSWORD"; then
  ASC_CONFIGURED="true"
fi

# ── Step 2: 과거 학습 데이터 로드 ──
LEARNINGS_FILE="${PROJECT_DIR}/.autobot/learnings.json"
HAS_LEARNINGS="false"
ACTIVE_LEARNINGS="false"
ACTIVE_LEARNINGS_SUMMARY="unavailable"
if [ -f "$LEARNINGS_FILE" ]; then
  HAS_LEARNINGS="true"
fi

RENDER_SCRIPT="${PLUGIN_ROOT}/scripts/render-active-learnings.py"
if [ "$HAS_LEARNINGS" = "true" ] && [ -f "$RENDER_SCRIPT" ]; then
  ACTIVE_OUTPUT=$(python3 "$RENDER_SCRIPT" --project-dir "$PROJECT_DIR" 2>/dev/null || echo "available=invalid")
  case "$ACTIVE_OUTPUT" in
    available=true*)
      ACTIVE_LEARNINGS="true"
      ACTIVE_LEARNINGS_SUMMARY="${ACTIVE_OUTPUT#available=true }"
      ;;
    available=invalid*)
      ACTIVE_LEARNINGS="true"
      ACTIVE_LEARNINGS_SUMMARY="invalid_learnings_json"
      ;;
  esac
elif [ "$HAS_LEARNINGS" = "false" ] && [ -f "${PROJECT_DIR}/.autobot/active-learnings.md" ]; then
  rm -f "${PROJECT_DIR}/.autobot/active-learnings.md"
fi

# ── Step 3: build-state 확인 (resume 가능 여부) ──
STATE_FILE="${PROJECT_DIR}/.autobot/build-state.json"
HAS_BUILD_STATE="false"
if [ -f "$STATE_FILE" ]; then
  HAS_BUILD_STATE="true"
fi

# ── Output systemMessage ──
cat << EOF
{
  "systemMessage": "[Autobot] has_env=${HAS_ENV}, asc_configured=${ASC_CONFIGURED}, has_learnings=${HAS_LEARNINGS}, active_learnings=${ACTIVE_LEARNINGS}, learnings_summary=${ACTIVE_LEARNINGS_SUMMARY}, has_build_state=${HAS_BUILD_STATE}. Phase learning files use explicit names: architecture.md, parallel_coding.md, quality.md, deploy.md. Read the mapped phase file first when present, then .autobot/active-learnings.md for shared context."
}
EOF
