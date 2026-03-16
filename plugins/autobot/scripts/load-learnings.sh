#!/bin/bash
# Load Autobot environment (.env) and past build learnings into session context
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

# ── Step 1: .env 파일에서 환경변수 로드 ──
# 프로젝트 .env → 글로벌 ~/.config/autobot/.env 순서로 탐색
ENV_FILE=""
if [ -f "${PROJECT_DIR}/.env" ]; then
  ENV_FILE="${PROJECT_DIR}/.env"
elif [ -f "${HOME}/.config/autobot/.env" ]; then
  ENV_FILE="${HOME}/.config/autobot/.env"
fi

if [ -n "$ENV_FILE" ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # .env에서 주석/빈줄 제거 후 CLAUDE_ENV_FILE에 주입
  grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$' | while IFS= read -r line; do
    echo "export $line" >> "$CLAUDE_ENV_FILE"
  done
  echo "[Autobot] 환경변수 로드됨: ${ENV_FILE}"
fi

# ── Step 2: 과거 학습 데이터 로드 ──
LEARNINGS_FILE="${PROJECT_DIR}/.autobot/learnings.json"

if [ -f "$LEARNINGS_FILE" ]; then
  TOTAL=$(python3 -c "import json; d=json.load(open('$LEARNINGS_FILE')); print(d.get('totalBuilds', 0))" 2>/dev/null || echo "0")
  RATE=$(python3 -c "import json; d=json.load(open('$LEARNINGS_FILE')); print(f\"{d.get('successRate', 0)*100:.0f}%\")" 2>/dev/null || echo "N/A")
  ERRORS=$(python3 -c "
import json
d=json.load(open('$LEARNINGS_FILE'))
errors=d.get('patterns',{}).get('common_build_errors',[])
for e in errors[:5]:
    print(f\"  - {e['pattern']}: {e['fix']}\")
" 2>/dev/null || echo "  (none)")

  cat << EOF
[Autobot] 과거 빌드 학습 데이터 로드됨:
- 총 빌드: ${TOTAL}회
- 성공률: ${RATE}
- 주요 에러 패턴:
${ERRORS}

/autobot:build 사용 시 이 데이터를 참조하여 빌드 품질을 개선합니다.
EOF
else
  echo "[Autobot] 과거 빌드 학습 데이터 없음. 첫 빌드 시 생성됩니다."
fi
