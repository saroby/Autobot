---
name: autobot-build-report
description: Use when an Autobot build completes (Phase 7) or when the user requests a post-build report. Also use when diagnosing why a build failed, reviewing agent performance, or identifying plugin improvements after a build.
---

# Build Report Generator

빌드 프로세스 중 발견된 **플러그인 수준의 문제**를 수집하고 구조화된 보고서를 생성한다.
이 보고서의 목적은 앱 버그 리포트가 아니라 **Autobot 플러그인 자체의 개선점**을 기록하는 것이다.

## 보고서 vs 학습파일

| | build-report.md | learnings.json |
|---|---|---|
| 범위 | 단일 빌드 | 전체 빌드 누적 |
| 대상 독자 | 사람 (플러그인 개발자) | 기계 (Phase 0에서 읽음) |
| 목적 | 플러그인 문제 진단 + 수정 제안 | 반복 패턴 학습 + 자동 적용 |
| 생성 시점 | Phase 7 | Phase 7 |

## 데이터 수집

보고서에 넣을 정보는 다음 소스에서 수집한다:

### 1. 빌드 상태 파일
```bash
# 빌드 메타데이터, Phase별 상태, 에러 기록
cat .autobot/build-state.json
```

### 2. 빌드 세션 중 발생한 이벤트

세션 컨텍스트에서 직접 수집하는 항목들:

| 카테고리 | 수집 내용 | 예시 |
|----------|----------|------|
| **에이전트 실패** | 어떤 에이전트가 왜 실패했는지 | 타임아웃, 파일 소유권 위반 |
| **수동 개입** | 오케스트레이터가 자동 처리 못해서 수동으로 한 작업 | 에이전트 타입 전환, 코드 직접 수정 |
| **컴파일 에러** | Phase 5 이전에 발견된 코드 생성 문제 | optional chaining 오류, import 누락 |
| **Gate 실패** | Phase 전환 시 검증 실패 내역 | 산출물 누락, 체크섬 불일치 |
| **Fallback 발동** | 기본 경로 실패로 대체 경로 사용 | xcodegen → pbxproj 직접 생성 |
| **성능 이상** | 예상보다 오래 걸린 Phase | Phase 4 > 10분 |

### 3. 프로젝트 산출물 검사

빌드 로그는 **Phase 5(quality-engineer)에서 이미 수행한 xcodebuild의 출력을 재활용**한다.
Phase 7에서 xcodebuild를 다시 실행하지 않는다 — 불필요한 시간 소비이고 결과도 동일하다.

```bash
# 생성된 파일 구조 확인
ls -R <AppName>/Views/ <AppName>/Services/ <AppName>/ViewModels/ 2>/dev/null

# Phase 5의 빌드 결과는 세션 컨텍스트에서 직접 수집
# (quality-engineer가 보고한 최종 빌드 상태, 수정한 에러, 남은 경고)
```

> **원칙**: Phase 7은 데이터를 **수집하고 정리**하는 Phase이지, 새로운 빌드를 실행하는 Phase가 아니다.

## 보고서 생성

`references/report-template.md`의 템플릿을 따라 `.autobot/build-report.md`를 생성한다.

### 문제 작성 규칙

각 문제는 **수정 가능한 수준**으로 구체적이어야 한다. 보고서를 읽은 사람(또는 AI)이 추가 질문 없이 바로 수정에 착수할 수 있어야 한다.

**좋은 예:**
```markdown
### 1. autobot:architect — non-optional 값에 optional chaining 사용

- **증상**: `APIModels.swift`에서 `[GeminiPart]`에 `parts?.compactMap` 사용
- **에러**: `Cannot use optional chaining on non-optional value of type '[GeminiPart]'`
- **원인**: architect 에이전트가 Codable 모델 생성 시 optional/non-optional 구분을 실수
- **영향**: Gate 1→2 통과 후 Phase 5에서 수동 수정 필요 (+2분)
- **수정 대상**: `plugins/autobot/agents/architect.md`
- **수정 제안**: architect 프롬프트에 "Models/ 생성 후 `swiftc -typecheck`로 컴파일 검증" 지침 추가
```

**나쁜 예:**
```markdown
### 1. 코드에 버그 있음
- 컴파일 에러 발생
- 수정 필요
```

### 문제 분류 체계

| 카테고리 | 설명 | 수정 대상 (보통) |
|----------|------|-----------------|
| `agent-prompt` | 에이전트 프롬프트의 지침 부족/오류 | `agents/*.md` |
| `orchestrator-logic` | 오케스트레이터의 흐름 제어 문제 | `skills/orchestrator/` |
| `gate-validation` | Phase 검증이 잡지 못한 문제 | `references/phase-gates.md` |
| `tooling` | 스크립트/도구의 버그 | `scripts/` |
| `template` | 프로젝트 템플릿의 누락/오류 | `references/project-templates.md` |
| `style-guide` | UX 스타일 가이드 미반영 | `references/ios-ux-style.md` |
| `fallback-missing` | 실패 시 대체 경로 부재 | 해당 스킬/에이전트 |
| `ux-friction` | 사용자 경험 저하 (경고 부재 등) | 해당 Phase 로직 |

### 심각도 기준

| 레벨 | 기준 | 예시 |
|------|------|------|
| **critical** | 빌드 중단 또는 데이터 손실 | 에이전트 완전 실패, Models/ 덮어쓰기 |
| **major** | 수동 개입 필요 | 에이전트 재실행 필요, 컴파일 에러 |
| **minor** | 불편하지만 빌드는 완료 | 경고 메시지 부재, 느린 Phase |
| **info** | 개선 기회 | 더 나은 패턴 발견, 성능 최적화 가능 |

## 부분 빌드 처리

Phase 중간에서 빌드가 중단된 경우에도 보고서를 생성한다:

1. `build-state.json`의 `phases` 에서 마지막 `completed` Phase까지만 보고
2. 실패한 Phase의 에러 정보를 중심으로 문제 섹션 작성
3. 미실행 Phase는 빌드 통계에 "미실행"으로 표시
4. Circuit Breaker 발동 시 해당 Phase의 재시도 이력을 모두 기록

```
예: Phase 4에서 중단된 빌드
├── Phase 0~3: 정상 기록
├── Phase 4: 실패 원인 + 재시도 이력
├── Phase 5~6: "미실행"
└── 문제 섹션: Phase 4 실패를 유발한 에이전트/산출물 분석
```

## 보고서 출력

파일 경로: `[프로젝트]/.autobot/build-report.md`

생성 후 사용자에게 요약:
```
빌드 보고서가 생성되었습니다: .autobot/build-report.md
- 발견된 문제: N건 (critical: X, major: Y, minor: Z)
- 잘 동작한 부분: N건
- 수정 제안이 포함된 문제: N건
```

## Autobot 플러그인에 피드백 적용

보고서를 Autobot 플러그인 작업폴더에서 읽으면 각 문제의 `수정 대상`과 `수정 제안`을 따라 직접 수정할 수 있다.

```
사용 예시:
1. /autobot:build 로 앱 생성
2. build-report.md 자동 생성됨
3. Autobot 플러그인 폴더에서:
   "build-report.md를 읽고 문제를 수정해"
   → 보고서의 수정 제안을 따라 에이전트/스킬 파일 수정
```

## Additional Resources

- **`references/report-template.md`** — 보고서 마크다운 템플릿
