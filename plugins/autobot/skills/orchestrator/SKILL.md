---
name: autobot-orchestrator
description: This skill should be used when orchestrating a full iOS app build from an idea, coordinating parallel agents, managing build phases, or when the user invokes "/autobot:build" or "/autobot:resume". Provides the master coordination logic for the Autobot build pipeline including phase validation gates, agent dispatch strategy, error recovery, and rollback mechanisms.
version: 0.2.0
---

# Autobot Orchestrator

Master coordination skill for building iOS 26+ apps from ideas. Manages the complete pipeline from idea analysis through TestFlight deployment with validation gates, error recovery, and state persistence.

## Core Pipeline

```
                    ┌──────────────────────────────────────────────────────┐
                    │              AUTOBOT BUILD PIPELINE                  │
                    └──────────────────────────────────────────────────────┘

 ┌─────────┐  Gate   ┌───────────┐  Gate   ┌──────────┐  Gate   ┌────────────────┐
 │ Phase 0  │──0→1──▶│  Phase 1   │──1→2──▶│ Phase 2   │──2→3──▶│    Phase 3      │
 │ Pre-     │        │ Architect  │        │ Scaffold  │        │  ┌──────────┐  │
 │ flight   │        │ (opus)     │        │ (self)    │        │  │ui-builder│  │
 │ (self)   │        │            │        │           │        │  └──────────┘  │
 └─────────┘        └───────────┘        └──────────┘        │  ┌──────────┐  │
                                                                │  │data-eng. │  │
                                                                │  └──────────┘  │
                                                                └───────┬────────┘
                                                                        │ Gate 3→4
                    ┌─────────┐  Gate   ┌───────────┐  Gate            ▼
                    │ Phase 6  │◀─soft──│  Phase 5   │◀─4→5──┌────────────────┐
                    │ Retro-   │        │ Deploy     │       │    Phase 4      │
                    │ spective │        │ (sonnet)   │       │ Quality Eng.    │
                    │ (self)   │        │            │       │ (sonnet)        │
                    └─────────┘        └───────────┘       └────────────────┘
```

### Phase 요약

| Phase | Name | Agent | Parallel | Gate | Max Retry |
|-------|------|-------|----------|------|-----------|
| 0 | Pre-flight & Setup | (self) | No | → 환경/이름 검증 | 1 |
| 1 | Architecture + Contracts | architect | No | → 산출물 존재/구조 검증 | 2 |
| 2 | Project Scaffold | (self) | No | → .xcodeproj 존재 검증 | 1 |
| 3 | Parallel Coding | ui-builder + data-engineer | **Yes** | → 파일 존재 + Models/ 무결성 | 2 |
| 4 | Integration & Build | quality-engineer | No | → xcodebuild 성공 | 2 |
| 5 | TestFlight Deploy | deployer | No | → soft (실패해도 진행) | 1 |
| 6 | Retrospective | (self) | No | — | — |

## Phase Validation Gates

**매 Phase 완료 직후, 다음 Phase에 진입하기 전에 산출물을 검증한다.**

Gate 통과 실패 시:
1. `retryCount < maxRetry` → 해당 Phase 재실행
2. `retryCount >= maxRetry` → `failed`로 마킹, Phase 6으로 건너뜀

상세 검증 항목은 **`references/phase-gates.md`** 참조.

### Models/ 무결성 보호

Phase 1 완료 시 Models/ 디렉토리의 체크섬을 `build-state.json`에 저장.
Gate 3→4에서 체크섬을 재계산하여 비교. 불일치 시 `git checkout -- Models/`로 자동 복원.

```bash
# 체크섬 계산
find Models/ -name "*.swift" -exec md5 {} \; | sort | md5
```

## Pre-flight Check (Phase 0)

Phase 0에서 빌드 시작 전에 환경을 검증:

```
✓ Xcode Command Line Tools 설치됨 (xcode-select -p)
✓ iOS Simulator 런타임 존재 (xcrun simctl list runtimes | grep iOS)
✓ python3 사용 가능 (pbxproj fallback용)
✓ git 사용 가능
✓ 디스크 여유 공간 > 1GB
✓ (선택) xcodegen 설치 여부 → 있으면 사용, 없으면 fallback
✓ (선택) fastlane 설치 여부 → 없으면 Phase 5에서 자동 설치 시도
✓ (선택) ASC 인증 정보 → 없으면 **즉시 사용자에게 경고 출력**
```

**ASC 미설정 시 즉시 경고 (Phase 0에서 출력):**
```
⚠️ App Store Connect 인증 정보가 설정되지 않았습니다.
   Phase 5(TestFlight 배포)가 건너뛰어집니다.
   빌드는 로컬에서만 완료됩니다.
   설정 방법: .env 파일에 ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH 추가
```

하나라도 필수 항목이 실패하면 빌드를 시작하지 않고 해결 방법을 안내.

## Agent Dispatch Strategy

### Parallel Execution (Phase 3)

worktree 격리로 파일시스템 충돌 방지:

```
Agent(
  prompt="[ui-builder task with full context]",
  isolation="worktree"
)
Agent(
  prompt="[data-engineer task with full context]",
  isolation="worktree"
)
```

### Worktree Fallback

세션 중 `git init`된 저장소 등에서 worktree 생성이 실패할 수 있다.
에러 `Cannot create agent worktree` 발생 시 **자동 fallback**:

```
1. isolation 파라미터 없이 general-purpose 에이전트로 재시도
2. ui-builder → Views/, ViewModels/, App/ 에만 쓰고
   data-engineer → Services/, Utilities/ 에만 쓰므로 충돌 없음
3. fallback 사실을 build-state.json에 기록:
   "phase3": { "worktreeFallback": true }
```

**주의:** fallback 시에도 두 에이전트를 **병렬로** 디스패치한다. 파일 소유권 규칙이 충돌을 방지한다.

### Agent Context Passing

에이전트는 파일을 통해 컨텍스트를 받는다:

| 파일 | 생성자 | 소비자 | 용도 |
|------|--------|--------|------|
| `.autobot/build-state.json` | Phase 0 | 전체 | 빌드 메타데이터, 상태 추적 |
| `.autobot/architecture.md` | architect | ui-builder, data-engineer, quality-engineer | 설계 명세 |
| `Models/*.swift` | architect | ui-builder, data-engineer | 타입 계약 (읽기 전용) |
| `Models/ServiceProtocols.swift` | architect | ui-builder, data-engineer | 통합 계약 (읽기 전용) |
| `App/ServiceStubs.swift` | ui-builder | quality-engineer | 임시 stub (Phase 4에서 삭제) |
| `Services/*Repository.swift` | data-engineer | quality-engineer | 프로토콜 구현체 |
| `.autobot/learnings.json` | retrospective | Phase 0 | 과거 학습 |
| `.autobot/deploy-status.json` | deployer | retrospective | 배포 결과 |

### File Ownership 규칙

| Agent | Writes To | MUST NOT Touch |
|-------|-----------|----------------|
| architect | `.autobot/architecture.md`, `Models/` | — |
| ui-builder | `Views/`, `ViewModels/`, `App/` | `Models/`, `Services/` |
| data-engineer | `Services/`, `Utilities/` | `Models/`, `Views/`, `ViewModels/`, `App/` |
| quality-engineer | 모든 파일 (통합 + 수정) | — |
| deployer | `build/`, 설정 파일 | 소스 코드 |

## Error Recovery

### 재시도 전략

| 에러 유형 | 재시도 방법 | 최대 횟수 |
|----------|-----------|----------|
| 에이전트 산출물 누락 | 같은 에이전트 재실행 | 2 |
| 컴파일 에러 | quality-engineer 반복 수정 | 5 (Phase 내) |
| Phase 자체 실패 | `/autobot:resume`으로 Phase 재실행 | 2 |
| 배포 실패 | deployer 재실행 (멱등) | 1 |

### 롤백 전략

Phase 실패 시 git을 사용한 롤백:

```bash
# Phase 3 실패 → Phase 2 직후 상태로 복원
git stash  # 현재 변경 보존
git log --oneline  # Phase 2 완료 커밋 확인
# quality-engineer가 수동 복구 시도

# Models/ 오염 시 → 타입 계약만 복원
git checkout -- Models/
```

### Circuit Breaker

같은 Phase가 3회 연속 실패하면 (`build-state.json`의 retryCount 확인):
1. 빌드를 중단
2. 실패 패턴을 `.autobot/learnings.json`에 기록
3. 사용자에게 구체적 해결 방법 안내 (troubleshooting 참조)
4. 아이디어를 단순화하여 재빌드 권고

## Build State Management

### State File: `.autobot/build-state.json`

```json
{
  "buildId": "build-20260316-socialfitness",
  "appName": "SocialFitness",
  "displayName": "소셜 피트니스",
  "bundleId": "com.saroby.socialfitness",
  "projectPath": "/Users/saroby/SocialFitness",
  "idea": "소셜 피트니스 트래킹 앱",
  "startedAt": "2026-03-16T12:00:00Z",
  "modelsChecksum": "a1b2c3d4e5f6...",
  "environment": {
    "xcodegen": true,
    "fastlane": false,
    "ascConfigured": true,
    "axiom": true
  },
  "phases": {
    "0": { "status": "completed", "completedAt": "..." },
    "1": { "status": "completed", "completedAt": "...", "modelsChecksum": "..." },
    "2": { "status": "completed", "completedAt": "..." },
    "3": { "status": "failed", "error": "...", "failedAt": "...", "retryCount": 1 },
    "4": { "status": "pending" },
    "5": { "status": "pending" },
    "6": { "status": "pending" }
  }
}
```

### Status 전이

```
pending → in_progress → completed
                      → failed → (retry) → in_progress
                                → skipped (circuit breaker)
```

## Context Window Management

에이전트가 컨텍스트 윈도우를 초과하지 않도록:

1. **architect**: 기능을 7개 이하, 화면을 10개 이하로 제한
2. **ui-builder/data-engineer**: 파일 단위로 작업 (한 번에 하나씩 Write)
3. **quality-engineer**: xcodebuild 출력을 `tail -50`으로 제한
4. **에이전트 프롬프트에 전체 architecture.md를 임베드하지 않음** — 파일 경로만 전달하고 에이전트가 직접 Read

## Plugin Detection Strategy

설치된 플러그인을 감지하되, 없어도 동작:

| 플러그인 | 감지 방법 | 활용 | Fallback |
|---------|----------|------|----------|
| Axiom | Skill 도구 호출 시도 | iOS 전문 스킬 | 내장 iOS 지식 |
| Serena | mcp__plugin_serena_serena__* 도구 존재 | 시맨틱 편집 | Edit 도구 |
| context7 | mcp__context7__* 도구 존재 | 최신 API 문서 | 학습 데이터 |

## Phase 6: Retrospective & Build Report

Phase 6에서는 두 가지 산출물을 생성한다:

1. **`build-report.md`** — `autobot-build-report` 스킬을 사용하여 생성. 플러그인 수준의 문제를 구조화된 보고서로 기록.
2. **`learnings.json`** — `autobot-retrospective` 스킬을 사용하여 누적 학습 데이터 업데이트.

build-report 먼저 생성하고, 그 내용을 참고하여 learnings.json을 업데이트한다.

## Additional Resources

| Reference | 내용 |
|-----------|------|
| **`references/phase-gates.md`** | Phase별 검증 항목, 통과 조건, 실패 시 동작 |
| **`references/architecture-template.md`** | architecture.md 정형화된 템플릿 |
| **`references/planning-patterns.md`** | 아이디어 분석, 기능 추출, 복잡도 추정 |
| **`references/agent-dispatch.md`** | 병렬 에이전트 프롬프트 템플릿, worktree 패턴 |
| **`references/troubleshooting.md`** | 증상별 진단 + 해결법 |
