#!/bin/bash
# Load Autobot environment (.env) and past build learnings into session context
# SessionStart hook — outputs systemMessage JSON with env vars and learnings
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"

# ── Step 1: .env 파일 탐색 ──
ENV_FILE=""
if [ -f "${PROJECT_DIR}/.env" ]; then
  ENV_FILE="${PROJECT_DIR}/.env"
elif [ -f "${HOME}/.config/autobot/.env" ]; then
  ENV_FILE="${HOME}/.config/autobot/.env"
fi

# .env 값을 파싱하여 systemMessage에 포함 (실제 환경변수 주입 대신)
ENV_SUMMARY=""
if [ -n "$ENV_FILE" ]; then
  # 키 이름만 추출 (값은 보안상 마스킹)
  ENV_KEYS=$(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | cut -d= -f1 | tr '\n' ', ' | sed 's/,$//')
  ENV_SUMMARY="env_file=${ENV_FILE}, configured_keys=[${ENV_KEYS}]"

  # 실제 값은 build/deploy 시 에이전트가 직접 .env에서 source하도록 경로만 전달
  ENV_PATH_INFO="env_path=${ENV_FILE}"
else
  ENV_SUMMARY="env_file=none"
  ENV_PATH_INFO="env_path=none"
fi

# ── Step 2: 과거 학습 데이터 로드 ──
LEARNINGS_FILE="${PROJECT_DIR}/.autobot/learnings.json"
LEARNINGS_SUMMARY=""

if [ -f "$LEARNINGS_FILE" ]; then
  LEARNINGS_SUMMARY=$(python3 -c "
import json
d=json.load(open('$LEARNINGS_FILE'))
total=d.get('totalBuilds', 0)
rate=d.get('successRate', 0)
errors=d.get('patterns',{}).get('common_build_errors',[])
top_errors='; '.join([f\"{e['pattern']} -> {e['fix']}\" for e in errors[:3]])
print(f'total_builds={total}, success_rate={rate*100:.0f}%, top_errors=[{top_errors}]')
" 2>/dev/null || echo "parse_error")
else
  LEARNINGS_SUMMARY="no_history"
fi

# ── Step 3: build-state 확인 (resume 가능 여부) ──
BUILD_STATE=""
STATE_FILE="${PROJECT_DIR}/.autobot/build-state.json"
if [ -f "$STATE_FILE" ]; then
  BUILD_STATE=$(python3 -c "
import json
d=json.load(open('$STATE_FILE'))
app=d.get('appName','?')
phases=d.get('phases',{})
failed=[k for k,v in phases.items() if v.get('status')=='failed']
last_ok=max([int(k) for k,v in phases.items() if v.get('status')=='completed'], default=-1)
if failed:
    print(f'resumable=true, app={app}, failed_phase={failed[0]}, last_completed={last_ok}')
elif last_ok < 6:
    print(f'resumable=true, app={app}, next_phase={last_ok+1}, last_completed={last_ok}')
else:
    print(f'resumable=false, app={app}, all_completed=true')
" 2>/dev/null || echo "parse_error")
else
  BUILD_STATE="no_state"
fi

# ── Output systemMessage ──
cat << EOF
{
  "systemMessage": "[Autobot Session] ${ENV_SUMMARY}, ${ENV_PATH_INFO}, learnings=[${LEARNINGS_SUMMARY}], build_state=[${BUILD_STATE}]. Deploy agents should 'source <env_path>' to load ASC credentials when env_path is set."
}
EOF
