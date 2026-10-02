### Step 5 — 브리프 합성

`.autobot/copy-analysis/brief.md` 를 architect 의 `architecture.md` 섹션 순서로 작성한다 (참조: `skills/autobot-orchestrator/references/architecture-template.md`). 최소 포함 섹션:

- `## Overview` (원본 재구현 대상의 *가치*, 이름/상표 제외)
- `## Market Context` (유사앱 근거 표)
- `## Features` (P0/P1 + role)
- `### Hook & Retention` (구체·비제네릭)
- `## Screens`
- `## Navigation Structure`
- `## Design Direction` (color/typography/layout/**signature layout**)

브리프는 architect 의 *입력*이지 최종 산출이 아니다 — gate 계약(build-state, feature-spec, Models/*.swift)을 위조하지 않는다. architect 가 이 브리프를 받아 정식 파이프라인으로 완성한다.
