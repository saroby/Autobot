---
name: autobot-orchestrator
description: Use when orchestrating a full iOS app build from an idea, coordinating parallel agents, managing build phases, or when the user invokes "/autobot:build" or "/autobot:resume".
---

# Autobot Orchestrator

Master coordination skill for building iOS 26+ apps from ideas. Manages the complete pipeline from idea analysis through TestFlight deployment with validation gates, error recovery, and state persistence.

## Core Pipeline

```
                    ┌──────────────────────────────────────────────────────┐
                    │              AUTOBOT BUILD PIPELINE                  │
                    └──────────────────────────────────────────────────────┘

 ┌─────────┐ Gate  ┌───────────┐ Gate  ┌──────────────┐ Gate  ┌──────────┐ Gate  ┌───────────────┐
 │ Phase 0  │─0→1─▶│  Phase 1   │─1→2─▶│  Phase 2   │─2→3─▶│ Phase 3   │─3→4─▶│   Phase 4     │
 │ Pre-     │      │ Architect  │      │ UX Design    │      │ Scaffold  │      │ ┌──────────┐  │
 │ flight   │      │ (opus)     │      │ (Stitch MCP) │      │ (self)    │      │ │ui-builder│  │
 │ (self)   │      │            │      │ ★ 필수       │      │           │      │ └──────────┘  │
 └─────────┘      └───────────┘      └──────────────┘      └──────────┘      │ ┌──────────┐  │
                                                                               │ │data-eng. │  │
                                                                               │ └──────────┘  │
                                                                               └───────┬───────┘
                                                                                       │ Gate 4→5
                    ┌─────────┐  Gate   ┌───────────┐  Gate                           ▼
                    │ Phase 7  │◀─soft──│  Phase 6   │◀─5→6──┌────────────────┐
                    │ Retro-   │        │ Deploy     │       │    Phase 5      │
                    │ spective │        │ (sonnet)   │       │ Quality Eng.    │
                    │ (self)   │        │            │       │ (sonnet)        │
                    └─────────┘        └───────────┘       └────────────────┘
```

### Phase 요약

| Phase | Name | Agent | Parallel | Gate | Max Retry |
|-------|------|-------|----------|------|-----------|
| 0 | Pre-flight & Setup | (self) | No | → 환경/이름 검증 | 1 |
| 1 | Architecture + Contracts | architect | No | → 산출물 존재/구조 검증 | 2 |
| 2 | UX Design (필수) | ux-designer | No | → Stitch 성공 필수, 미설치 시 fallback | 1 |
| 3 | Project Scaffold | (self) | No | → .xcodeproj 존재 검증 | 1 |
| 4 | Parallel Coding | ui-builder + data-engineer + (backend-engineer) | **Yes** | → 파일 존재 + Models/ 무결성 | 2 |
| 5 | Integration & Build | quality-engineer | No | → xcodebuild 성공 | 2 |
| 6 | TestFlight Deploy | deployer | No | → soft (실패해도 진행) | 1 |
| 7 | Retrospective | (self) | No | — | — |

## Phase Validation Gates

**매 Phase 완료 직후, 다음 Phase에 진입하기 전에 산출물을 검증한다.**

Gate 통과 실패 시:
1. `retryCount < maxRetry` → 해당 Phase 재실행
2. `retryCount >= maxRetry` → `failed`로 마킹, Phase 7으로 건너뜀

상세 검증 항목은 **`references/phase-gates.md`** 참조.

### `<AppName>/Models/` 무결성 보호

Phase 1 완료 시 `<AppName>/Models/` 디렉토리의 체크섬을 `build-state.json`에 저장.
Gate 4→5에서 체크섬을 재계산하여 비교. 불일치 시 `git checkout -- <AppName>/Models/`로 자동 복원.

```bash
# 체크섬 계산
find <AppName>/Models/ -name "*.swift" -exec md5 {} \; | sort | md5
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
✓ (선택) fastlane 설치 여부 → 없으면 Phase 6에서 자동 설치 시도
✓ (선택) docker 설치 여부 → 백엔드 필요 시 Gate 1→2에서 필수 확인
✓ (선택) ASC 인증 정보 → 없으면 **즉시 사용자에게 경고 출력**
```

**ASC 미설정 시 즉시 경고 (Phase 0에서 출력):**
```
⚠️ App Store Connect 인증 정보가 설정되지 않았습니다.
   Phase 6(TestFlight 배포)가 건너뛰어집니다.
   빌드는 로컬에서만 완료됩니다.
   설정 방법: .env 파일에 ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH 추가
```

하나라도 필수 항목이 실패하면 빌드를 시작하지 않고 해결 방법을 안내.

## Phase 2: UX Design with Stitch (필수)

Stitch MCP를 사용한 UX 디자인 생성은 **기본(primary) 경로**다. Stitch가 설치되지 않은 환경에서만 fallback 모드로 전환한다.

```
if environment.stitch == true:
    Agent(
      subagent_type="ux-designer",
      prompt="[ux-designer task with architecture.md path, app name, screen list]"
    )
    → .autobot/designs/*.png + .autobot/design-spec.md 생성
    → build-state.json에 stitch.projectId 기록
    → 실패 시 1회 재시도 후, 재실패 시 fallback 모드로 전환
else:
    ⚠️ 사용자에게 Stitch MCP 미설치 경고 출력:
    "⚠️ Stitch MCP가 설치되지 않아 UX 디자인 생성 없이 진행합니다.
     UI는 architecture.md 기반으로 생성됩니다 (fallback 모드).
     Stitch 설치: npx @_davideast/stitch-mcp init"
    phases["2"].status = "fallback"
    → Phase 3로 진행
```

**Primary 경로 (Stitch 사용):** ux-designer가 Stitch로 화면별 디자인을 생성하고, ui-builder가 design-spec.md + 목업 이미지를 참조하여 SwiftUI를 구현한다. 이것이 **권장되는 표준 경로**다.

**Fallback 경로 (Stitch 미설치):** ui-builder가 architecture.md만으로 UI를 구현한다. 디자인 일관성이 낮아질 수 있다.

상세 워크플로우는 **`autobot-ux-design` 스킬** 참조.

## Agent Dispatch Strategy

### Parallel Execution (Phase 4)

파일 소유권 규칙으로 충돌 방지 — 각 에이전트는 지정된 디렉토리에만 쓴다:

```
Agent(
  subagent_type="ui-builder",
  prompt="[ui-builder task with full context]"
)
Agent(
  subagent_type="data-engineer",
  prompt="[data-engineer task with full context]"
)

# 조건부: backend_required == true일 때만 디스패치
if build-state.json.backend_required == true:
  Agent(
    subagent_type="backend-engineer",
    prompt="[backend-engineer task with full context]"
  )
```

**충돌 방지:** ui-builder → `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/App/` / data-engineer → `<AppName>/Services/`, `<AppName>/Utilities/` / backend-engineer → `backend/` — 디렉토리가 완전히 분리되어 있으므로 충돌 불가.

### Agent Context Passing

에이전트는 파일을 통해 컨텍스트를 받는다:

| 파일 | 생성자 | 소비자 | 용도 |
|------|--------|--------|------|
| `.autobot/build-state.json` | Phase 0 | 전체 | 빌드 메타데이터, 상태 추적 |
| `.autobot/architecture.md` | architect | ux-designer, ui-builder, data-engineer, quality-engineer | 설계 명세 |
| `.autobot/design-spec.md` | ux-designer | ui-builder | UX 디자인 명세 (primary 디자인 입력) |
| `.autobot/designs/*.png` | ux-designer | ui-builder | 화면별 UI 목업 스크린샷 (primary 시각 참조) |
| `<AppName>/Models/*.swift` | architect | ui-builder, data-engineer | 타입 계약 (읽기 전용) |
| `<AppName>/Models/ServiceProtocols.swift` | architect | ui-builder, data-engineer | 통합 계약 (읽기 전용) |
| `<AppName>/App/ServiceStubs.swift` | ui-builder | quality-engineer | 임시 stub (Phase 5에서 삭제) |
| `<AppName>/Models/APIContracts.swift` | architect | data-engineer, backend-engineer | API 계약 (SSOT) |
| `<AppName>/Services/*Repository.swift` | data-engineer | quality-engineer | 프로토콜 구현체 |
| `backend/` | backend-engineer | quality-engineer | Docker 백엔드 |
| `.autobot/learnings.json` | retrospective | Phase 0 | 과거 학습 |
| `.autobot/deploy-status.json` | deployer | retrospective | 배포 결과 |

### File Ownership 규칙

> 모든 소스 경로는 `<AppName>/` 서브디렉토리(Xcode 소스 그룹) 기준. `backend/`, `.autobot/`은 프로젝트 루트.

| Agent | Writes To | MUST NOT Touch |
|-------|-----------|----------------|
| architect | `.autobot/architecture.md`, `<AppName>/Models/` | — |
| ux-designer | `.autobot/designs/`, `.autobot/design-spec.md` | `<AppName>/`, `.autobot/architecture.md` |
| ui-builder | `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/App/` | `<AppName>/Models/`, `<AppName>/Services/` |
| data-engineer | `<AppName>/Services/`, `<AppName>/Utilities/` | `<AppName>/Models/`, `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/App/` |
| backend-engineer | `backend/` | `<AppName>/`, root `.gitignore` |
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
# Phase 4 실패 → Phase 3 직후 상태로 복원
git stash  # 현재 변경 보존
git log --oneline  # Phase 3 완료 커밋 확인
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
    "axiom": true,
    "stitch": true
  },
  "stitch": {
    "projectId": "stitch-project-12345",
    "screenCount": 5,
    "designsPath": ".autobot/designs/"
  },
  "phases": {
    "0": { "status": "completed", "completedAt": "..." },
    "1": { "status": "completed", "completedAt": "...", "modelsChecksum": "..." },
    "2": { "status": "completed", "completedAt": "..." },
    "3": { "status": "completed", "completedAt": "..." },
    "4": { "status": "failed", "error": "...", "failedAt": "...", "retryCount": 1 },
    "5": { "status": "pending" },
    "6": { "status": "pending" },
    "7": { "status": "pending" }
  },
  "backend_required": false,
  "backend": null
}
```

`backend_required == true`일 때의 예시:

```json
{
  "backend_required": true,
  "backend": {
    "tech_stack": "python-fastapi",
    "oauth_providers": ["apple", "google"],
    "llm_proxy": true,
    "docker_verified": false
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
| Stitch | `npx @_davideast/stitch-mcp doctor` 성공 | Phase 2 UX 디자인 생성 (필수 경로) | architecture.md만으로 UI 구현 (fallback) |

## Phase 7: Retrospective & Build Report

Phase 7에서는 두 가지 산출물을 생성한다:

1. **`build-report.md`** — `autobot-build-report` 스킬을 사용하여 생성. 플러그인 수준의 문제를 구조화된 보고서로 기록.
2. **`learnings.json`** — `autobot-retrospective` 스킬을 사용하여 누적 학습 데이터 업데이트.

build-report 먼저 생성하고, 그 내용을 참고하여 learnings.json을 업데이트한다.

## Additional Resources

| Reference | 내용 |
|-----------|------|
| **`references/phase-gates.md`** | Phase별 검증 항목, 통과 조건, 실패 시 동작 |
| **`references/architecture-template.md`** | architecture.md 정형화된 템플릿 |
| **`references/planning-patterns.md`** | 아이디어 분석, 기능 추출, 복잡도 추정 |
| **`references/agent-dispatch.md`** | 병렬 에이전트 프롬프트 템플릿, Agent Team 패턴 |
| **`references/troubleshooting.md`** | 증상별 진단 + 해결법 |
