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

`build-state.json`과 세션 컨텍스트에서 수집:

| 항목 | 소스 | 예시 |
|------|------|------|
| Phase별 소요 시간 | `phases[N].completedAt - phases[N-1].completedAt` | 180초 |
| 재시도 횟수 | `phases[N].retryCount` | 2 |
| 에러 유형 | 세션 컨텍스트 (컴파일 에러, 타임아웃 등) | "Cannot find type" |
| 에이전트 성공/실패 | 세션 컨텍스트 | ui-builder 성공, data-engineer 1회 실패 |
| 배포 결과 | `.autobot/deploy-status.json` | upload_success: true |
| 모델/토큰 사용량 | 세션 컨텍스트 (가능한 경우) | opus: 45k tokens, sonnet: 120k tokens |

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

## Additional Resources

- **`references/learning-schema.md`** — learnings.json 전체 스키마, 예시, 업데이트 규칙
