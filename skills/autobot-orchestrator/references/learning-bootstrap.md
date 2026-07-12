# Learning Bootstrap Protocol

모든 Autobot 에이전트가 실행 직후 따르는 학습 로드/기록 프로토콜의 단일 출처. 새 빌드를 시작하기 전에 과거 빌드의 학습 데이터를 적용하고, 적용 사실을 build-log 에 남기는 절차는 모든 에이전트가 동일하다. **다른 점은 phase 번호, phase-learning 파일명, agent 이름뿐**이므로 그 세 값만 채워 이 문서의 절차를 따른다.

## Load order

1. **Phase-specific 파일** — `.autobot/phase-learnings/<file>.md`. 존재하면 이번 빌드의 **1순위 입력**으로 사용한다.
2. **Active learnings fallback** — `.autobot/active-learnings.md`. phase-specific 파일을 적용한 뒤 **공유 컨텍스트로만** 참고한다.

두 파일이 모두 없으면 깨끗한 첫 빌드이므로 그대로 진행한다. 이 경우에도 적용 기록(아래 섹션)은 수행하되 `--detail '{"sources":[]}'` 로, `--rule` 없이 기록한다 — 빈 `sources` 는 "적용할 학습이 없었다"는 정당한 감사 기록이고, Gate 의 `learningsConsumed` 요구를 그대로 충족한다.

## Phase → phase-learning 파일

| Phase | Agent | 파일 |
|-------|-------|------|
| 1 | architect | `phase-learnings/architecture.md` |
| 2 | ux-designer | (전용 파일 없음 — `active-learnings.md`만 사용) |
| 4 | ui-builder / data-engineer / backend-engineer | `phase-learnings/parallel_coding.md` |
| 5 | quality-engineer | `phase-learnings/quality.md` |
| 6 | deployer | `phase-learnings/deploy.md` |

Phase 0/3/7은 self phase 이므로 별도 phase-learning 파일이 없다. (전체 표는 `commands/resume.md` 의 Phase Learning Map 과 같다.)

## 적용 대상 섹션

다음 헤더를 스캔해서, **이 에이전트의 책임에 해당하는 항목만** 적용한다:

- `## Proven Patterns` — 과거 빌드에서 효과가 확인된 반복 가능한 접근.
- `## Prevention Rules` — 재발 방지를 위한 교정.
- `## Pending Improvements` — 아직 적용되지 않은 개선 후보 중 이 에이전트와 관련된 것.
- `## Relevant Failure Memory` — 이번 작업에 근거가 되는 과거 실패 사례.

에이전트별 메인 프롬프트가 더 좁은 필터를 명시할 수 있다 (예: quality-engineer 는 `## Relevant Prevention Rules` 를 빌드-픽스 의사결정의 1순위로 본다). 그 경우 메인 프롬프트가 우선한다.

## 적용 기록

**항상** build-log.jsonl 에 `learning_applied` 이벤트를 기록한다 — 학습 파일을 적용했든(sources 에 나열), 첫 빌드라 파일이 없든(`"sources":[]`) 동일하다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase <N> --event learning_applied --agent <agent-name> \
  --detail '{"sources":[<실제로 읽은 파일들>]}' \
  --rule "<실제로 적용한 prevention/architecture 규칙 1>" \
  --rule "<실제로 적용한 규칙 2>"
```

규칙:
- `sources` 배열에는 **실제로 존재했고 적용한 파일만** 포함한다 (없던 파일은 빼고 보낸다).
- 두 파일 모두 부재하면(첫 빌드) `--detail '{"sources":[]}'` 로 기록하고 `--rule` 은 넘기지 않는다. **가짜 규칙 텍스트(예: "clean first build")를 만들어 넣지 마라** — rule 없는 기록은 effect-score 채점에서 새 item 을 만들지 않으므로 조작해도 이득이 없고, 글로벌 저장소만 오염시킨다.
- runtime.py 의 `append-log` 가 `phases.<N>.learningsConsumed[]` 에 `agent-name` 을 누적해 두므로 Gate 가 "이 에이전트가 학습을 소비했는지" 를 검증할 수 있다.
- **`--rule` (반복 가능, 강력 권장)**: 실제로 적용한 개별 규칙의 **본문 텍스트**를 그대로 넘긴다 (렌더된 `## Prevention Rules` / `## Proven Patterns` 항목의 문구). 가능하면 prevention 규칙 문구를 그대로 복사한다. 그래야 회고의 effect-score 채점이 **agent 단위가 아니라 규칙 단위**로 동작해, 반복해서 빌드를 망친 규칙 하나만 quarantine 되어 이후 프롬프트에서 빠진다 (`--rule` 없이 agent 이름만 기록하면 그 agent 가 적용한 모든 규칙이 한 덩어리로 묶여 개별 quarantine 이 불가능하다).

## 적용 예시

architect 가 Phase 1 진입 직후:

```bash
# phase-learnings/architecture.md 와 active-learnings.md 모두 존재한다고 가정
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 1 --event learning_applied --agent architect \
  --detail '{"sources":["phase-learnings/architecture.md","active-learnings.md"]}' \
  --rule "Scene .modelContainer(for:)에 migrationPlan 인자 전달 금지 — 컨테이너를 @main에서 명시 조립" \
  --rule "모든 feature.anchor 는 해당 화면의 탭 anchor 로 고정"
```

quality-engineer 가 Phase 5 에서 phase-learnings 만 있고 active 가 없다면:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 5 --event learning_applied --agent quality-engineer \
  --detail '{"sources":["phase-learnings/quality.md"]}' \
  --rule "SwiftData 테스트 헬퍼는 ModelContainer 를 반환/보관하고 context 만 노출하지 않는다"
```

ui-builder 가 첫 빌드(두 파일 모두 부재)라면:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 4 --event learning_applied --agent ui-builder \
  --detail '{"sources":[]}'
```

세 경우 모두 이 문서의 절차를 그대로 따르되, **phase 번호·파일 경로·agent 이름·실제 적용한 규칙** 만 바뀐다 (`--rule` 값은 위 예시 문구가 아니라 이번 빌드에서 실제로 읽고 적용한 규칙의 본문이어야 한다).
