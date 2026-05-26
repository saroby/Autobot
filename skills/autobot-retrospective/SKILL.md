---
name: autobot-retrospective
description: Use after an Autobot build completes (success or failure), when checking past build history, when analyzing build performance trends, or when investigating why the same error keeps recurring across builds.
---

# Build Retrospective & Self-Improvement

빌드마다 학습 데이터를 축적하여 다음 빌드의 품질과 속도를 개선하는 피드백 루프.

## Phase 이름 매핑

`build-state.json`의 숫자 키를 `learnings.json`의 문자열 키로 변환할 때 이 테이블을 사용한다:

| build-state.json | learnings.json | 설명 |
|-------------------|---------------|------|
| `"0"` | `preflight` | 환경 검증 |
| `"1"` | `architecture` | 아키텍처 + 타입 계약 |
| `"2"` | `ux_design` | UX 디자인 (Stitch) |
| `"3"` | `scaffold` | Xcode 프로젝트 생성 |
| `"4"` | `parallel_coding` | 병렬 코드 생성 |
| `"5"` | `quality` | 통합 + 빌드 검증 |
| `"6"` | `deploy` | TestFlight 배포 |
| `"7"` | `retrospective` | 회고 + 보고서 |

## Retrospective Process

### 1. Collect Build Metrics

**1차 데이터 소스**: `.autobot/build-log.jsonl` (구조화된 이벤트 로그)
**2차 데이터 소스**: `build-state.json`, `.autobot/deploy-status.json`
**3차 보조**: 세션 컨텍스트 (로그에 없는 정보만)

```bash
# 이벤트 로그에서 빌드 시도 횟수 추출
grep '"build_attempt"' .autobot/build-log.jsonl | wc -l

# 에이전트 소유권 위반 횟수 추출
grep '"agent_violation"' .autobot/build-log.jsonl | wc -l

# Phase별 소요 시간 계산 (start ~ complete 이벤트 간 간격)
python3 -c "
import json
events = [json.loads(l) for l in open('.autobot/build-log.jsonl')]
starts = {e['phase']: e['ts'] for e in events if e['event'] == 'start'}
ends = {e['phase']: e['ts'] for e in events if e['event'] == 'complete'}
for p in sorted(starts):
    if p in ends:
        print(f'Phase {p}: {starts[p]} → {ends[p]}')
" 2>/dev/null || echo "build-log.jsonl not available"
```

| 항목 | 소스 | 예시 |
|------|------|------|
| Phase별 소요 시간 | `build-log.jsonl` (start/complete 이벤트 간격) | 180초 |
| 빌드 시도 횟수 | `build-log.jsonl` (build_attempt 이벤트 수) | 3 |
| 에러 유형/카테고리 | `build-log.jsonl` (build_fix 이벤트의 category) | "import", "type" |
| 에이전트 소유권 위반 | `build-log.jsonl` (agent_violation 이벤트) | 0 |
| 스냅샷 복원 횟수 | `build-log.jsonl` (snapshot_restore 이벤트 수) | 1 |
| 재시도 횟수 | `build-state.json` (`phases[N].retryCount`) | 2 |
| 에이전트 성공/실패 | `build-log.jsonl` (agent_complete/agent_dispatch 매칭) | ui-builder 성공 |
| 배포 결과 | `.autobot/deploy-status.json` | upload_success: true |
| 모델/토큰 사용량 | 세션 컨텍스트 (가능한 경우) | opus: 45k tokens |

### 2. Analyze Patterns

`.autobot/learnings.json`의 과거 빌드와 비교:
- 반복 에러 패턴 (같은 fix가 여러 번 적용됨)
- 성공한 아키텍처 패턴
- 효과적인 에이전트 디스패치 전략
- 배포 실패 원인과 해결법

### 3. Update Learnings File

**갱신 절차:**
1. `.autobot/learnings.json`을 Read (없으면 빈 스키마로 초기화)
2. `builds[]`에 현재 빌드 엔트리 추가 — Phase별 소요시간, 재시도, 에러, 비용 추적 포함
3. `patterns.common_build_errors`에 새 에러 패턴 추가 (이미 있으면 `frequency` 증가)
4. `patterns.effective_architectures`에 성공한 아키텍처 패턴 추가
5. `totalBuilds` 증가, `successRate` 재계산
6. `.autobot/learnings.json`에 Write

**빌드 엔트리에 포함할 비용 추적 필드:**

```json
{
  "id": "build-001",
  "cost": {
    "total_tokens_estimate": 165000,
    "models_used": ["opus", "sonnet"],
    "total_duration_sec": 540
  }
}
```

### 4. Generate Improvement Recommendations

| 조건 | 액션 |
|------|------|
| 같은 에러 3회 이상 | 해당 에이전트 프롬프트에 prevention 지침 추가 |
| 특정 앱 유형이 더 빠르게 빌드 | 아키텍처 패턴을 "proven"으로 마킹 |
| 배포 같은 사유로 2회 이상 실패 | Phase 0 prerequisite check에 추가 |
| Phase 소요 시간 > 10분 | 병목 Phase 분석하고 원인 기록 |

## Learning Application

Phase 0에서 `.autobot/learnings.json`을 읽고:
1. 알려진 에러 방지 패턴 적용 (에이전트 프롬프트에 주입)
2. 유사한 앱 유형에 검증된 아키텍처 패턴 사용
3. 실패 이력이 있는 배포 방법 건너뜀
4. 과거 성능 데이터 기반으로 에이전트 전략 조정

`learnings.json` 업데이트 후 다음 세션에서 바로 사용할 수 있도록 `.autobot/active-learnings.md`와 `.autobot/phase-learnings/*.md` 압축본도 재생성한다. 이 파일들은 SessionStart 훅과 build/resume Phase 0의 1차 입력이다.

## Axiom Health-Check 통합 (선택, soft-skip)

Phase 7 의 **데이터 수집 단계 중간**에 Axiom 의 전체 health-check 를 1회 실행해 회고 데이터의 폭을 넓힌다. Phase 5 Critical Audit 와 달리 **절대 빌드를 막지 않는다** — Phase 7 은 학습용이지 게이트가 아니다.

호출 규칙·프롬프트·결과 기록 위치는 `autobot-axiom-bridge` 스킬의 **Mode 2 (Phase-7 Health-Check)** 에 SSOT 로 있다:

```bash
Read $CLAUDE_PLUGIN_ROOT/skills/autobot-axiom-bridge/SKILL.md
```

이 스킬에서 추가로 기억할 것:

1. Axiom 부재 → 한 줄 로그(`axiom_audit_skipped`)만 남기고 회고 진행.
2. `axiom:health-check` 에이전트 단일 dispatch (개별 auditor 호출 X — 중복 비용).
3. 결과를 `learnings.json` → `patterns.axiom_findings[rule].frequency` 에 누적. 키 스키마는 `patterns.common_build_errors` 와 동일하게 유지해 Phase 0 의 learning bootstrap 이 별도 코드 없이 흡수한다.
4. `phases.7.metadata.axiom_health_check` 에 `{ran, findings_path, summary_path}` 기록.
5. executive summary 는 `build-report.md` 의 `## Axiom Health-Check` 섹션으로 첨부.

### Phase 7 closing steps (필수, 순서대로)

회고 본문 작성과 `learnings.json` 갱신이 끝났다면 — **Phase 7 self-check 직전** — 아래 두 호출을 차례로 실행한다. 이 단계가 빠지면 다음 빌드의 `Phase 0` 이 효과 없는 learning 을 그대로 다시 적용하고, 운영자는 무슨 일이 있었는지 알 수 없게 된다.

```bash
# (a) Learning effect 채점: phase 별 status / breaker / build-fix attempts 를 보고
#     learnings.json 의 effect_score 누적. hurt 누적 시 자동 quarantine.
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" grade-learnings \
  --build-id "$(python3 -c "import json; print(json.load(open('.autobot/build-state.json'))['buildId'])")"

# (b) Run summary 생성: artifacts/<buildId>/run-summary.{json,md} + latest 심볼릭.
#     성공/실패 모든 run 에서 호출. /autobot:resume 안내가 footer 에 자동 들어간다.
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" write-run-summary
```

`grade-learnings` 의 출력 (`{"updated": N, "summaries": [...]}`) 을 build-report.md 의 `## Learning Impact` 섹션에 그대로 첨부한다. quarantined 가 발생했다면 `## Quarantined Learnings` 섹션도 추가한다 (`pipeline.sh grade-learnings` 출력의 negative effect_score 항목들).

### Phase 7 self-check (필수)

회고 종료 직전 — Phase 7 status 를 `completed` 로 마킹하기 전에 — 아래 검증 스크립트를 실행해 Axiom 호출 (또는 명시적 skip) 이 기록됐는지 확인한다. Phase 7 은 게이트가 없으므로 이 self-check 가 유일한 강제 지점이다.

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/verify-phase7-axiom.py" "$PROJECT_DIR" || {
  echo "Phase 7 self-check failed — Axiom Mode 2 가 호출되지 않았거나 skip 이벤트가 누락"
  exit 1
}
```

통과 조건:
- `environment.axiom == false` → build-log.jsonl 에 `phase=7` 의 `axiom_audit_skipped` 이벤트 ≥ 1개
- `environment.axiom == true` → `phases.7.metadata.axiom_health_check.ran == true` 이고 `findings_path` (있으면) 실제 파일 존재

## Additional Resources

- **`references/learning-schema.md`** — learnings.json 전체 스키마, 예시, 업데이트 규칙
- **`$CLAUDE_PLUGIN_ROOT/skills/autobot-axiom-bridge/SKILL.md`** — Axiom 호출 규칙 SSOT (Mode 1 = Phase 5 critical, Mode 2 = Phase 7 health-check)
