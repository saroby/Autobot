---
name: autobot-retrospective
user-invocable: false
description: "Write Phase 7 learnings or analyze repeated failures across Autobot builds."
---

# Build Retrospective & Self-Improvement

Phase 7에서 이번 빌드의 관측·패턴을 `.autobot/learnings.json`에 누적한다. [learning-schema.md](references/learning-schema.md)의 스키마·갱신 규칙을 사용한다.

## 수집과 학습

데이터 우선순위: `.autobot/build-log.jsonl` → `build-state.json` / `.autobot/deploy-status.json` → 로그에 없는 세션 관측.

| 지표 | 근거 |
|------|------|
| Phase 소요 시간 | `start` / `complete` 이벤트 간격 |
| 빌드 시도·에러 카테고리 | `build_attempt` 횟수, `build_fix.category` |
| 소유권 위반·복원 | `agent_violation`, `snapshot_restore` |
| 에이전트 성공/실패 | `agent_dispatch` / `agent_complete` 매칭 |
| 재시도·배포 | `phases[N].retryCount`, deploy-status |
| 비용 | 관측 가능한 토큰 추정·모델·총 시간 |

Phase 키 매핑: `0→preflight`, `1→architecture`, `2→ux_design`, `3→scaffold`, `4→parallel_coding`, `5→quality`, `6→deploy`, `7→retrospective`.

1. 기존 learnings를 읽고(없으면 스키마 초기화), 과거 빌드와 반복 오류·효과적인 architecture/dispatch·배포 실패를 비교한다.
2. `builds[]`에 현재 빌드의 Phase별 시간·재시도·에러와 `cost.{total_tokens_estimate,models_used,total_duration_sec}`을 추가한다. 기존 이력을 보존한다.
3. `patterns.common_build_errors`에 오류를 추가하거나 `frequency`를 증가시키고, 성공 패턴은 `patterns.effective_architectures`에 기록한다. `totalBuilds`와 `successRate`를 갱신한다.
4. 개선 후보: 같은 오류 3회 이상→에이전트 prevention; 성공한 architecture 반복→proven 패턴; 같은 배포 실패 2회 이상→Phase 0 prerequisite; Phase 10분 초과→병목 원인. 구체적 기준은 learning-schema를 따른다.
5. 다음 Phase 0에서 오류 예방·검증된 architecture·배포 실패 회피·dispatch 조정에 활용하도록 `.autobot/active-learnings.md`, `.autobot/phase-learnings/*.md`를 재생성한다:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/render-active-learnings.py" --project-dir "$PROJECT_DIR"
```

## Axiom Health-Check

수집한 metrics 뒤에 [autobot-axiom-bridge](../autobot-axiom-bridge/SKILL.md)의 **Mode 2**를 1회 실행한다. 단일 `axiom:health-check` dispatch를 사용하며 개별 auditor를 중복 호출하지 않는다. findings는 빌드를 막지 않는다.

- 미설치: Phase 7 `axiom_audit_skipped` 로그를 남기고 계속한다.
- 결과: `patterns.axiom_findings[rule].frequency`에 누적(common_build_errors와 같은 shape), `phases.7.metadata.axiom_health_check={ran,findings_path,summary_path}` 기록.
- Executive summary: build-report의 `## Axiom Health-Check`에 첨부한다.

## Closing (필수 순서)

회고 본문·learnings 갱신 후, self-check 직전에 성공/실패 모든 run에서 실행한다:

```bash
BUILD_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json'))['buildId'])")
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" grade-learnings \
  --build-id "$BUILD_ID"
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" write-run-summary
python3 "$CLAUDE_PLUGIN_ROOT/scripts/topology_insights.py" --out-dir .autobot >/dev/null 2>&1 || true
: "${OWNED_LOCK_TOKEN:?Phase 0/resume에서 획득한 build lock token이 필요합니다}"
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" build-lock release \
  --build-id "$BUILD_ID" --expected-token "$OWNED_LOCK_TOKEN"
```

- `grade-learnings`는 status/breaker/build-fix 관측으로 `effect_score`를 누적하고 hurt 누적 learning을 quarantine한다. JSON 출력(`{updated,summaries}`)을 `## Learning Impact`에 그대로 첨부하고, negative effect_score가 있으면 `## Quarantined Learnings`도 추가한다.
- `write-run-summary`는 `artifacts/<buildId>/run-summary.{json,md}`와 latest symlink를 생성한다.
- `.autobot/topology-insights.md`의 Phase 핫스팟 표·개선 후보를 `## Cross-Build Pipeline Insights`에 첨부한다. read-only 분석이며 pipeline을 자동 변경하지 않는다. 승격은 기존 `learning_impact publish-global` 운영자 승인 경로를 따른다.
- Lock은 현재 실행이 Phase 0/resume에서 보관한 **원래 generation token**으로만 해제한다. status에서 token을 다시 읽으면 takeover한 다른 세대를 해제할 수 있으므로 금지한다.

Phase 7 `completed` 마킹 전에 self-check한다(Phase 7에는 gate가 없다):

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/verify-phase7-axiom.py" "$PROJECT_DIR" || {
  echo "Phase 7 self-check failed — Axiom Mode 2 가 호출되지 않았거나 skip 이벤트가 누락"
  exit 1
}
```

통과 조건: `environment.axiom == false`이면 phase=7의 `axiom_audit_skipped` 이벤트가 있어야 한다. true이면 `phases.7.metadata.axiom_health_check.ran == true`와 기록한 findings 파일 존재를 확인한다.
