#!/bin/bash
# Load past Autobot build learnings into session context
set -euo pipefail

LEARNINGS_FILE="${CLAUDE_PROJECT_DIR:-.}/.autobot/learnings.json"

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
