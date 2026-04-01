---
name: autobot-orchestrator
description: Use when orchestrating a full iOS app build from an idea, coordinating parallel agents, managing build phases, or when the user invokes "/autobot:build" or "/autobot:resume". Also use when a build stalls, needs error recovery, or requires phase-level retry coordination.
---

# Autobot Orchestrator

Master coordination skill for building iOS 26+ apps from ideas. Manages the complete pipeline from idea analysis through TestFlight deployment with validation gates, error recovery, and state persistence.

## SSOT Rules

`plugins/autobot/spec/pipeline.json`이 Autobot 파이프라인의 단일 실행 규격이다.

- Phase 번호, 이름, 상태 전이, retry, gate 정의는 실행 스펙을 기준으로 한다
- build/resume의 상태 전이, Gate 실행/기록, Phase lifecycle 로그는 `scripts/pipeline.sh` 경로만 사용한다
- 이 문서와 `build.md`, `resume.md`는 실행 스펙의 설명/운영 가이드다
- README는 개요와 사용법만 다룬다
- 문서 간 충돌이 있으면 실행 스펙이 우선한다

## Safety Policy

Autobot은 위험도를 기준으로 동작한다:

- `autonomous`: 로컬 파일 생성/수정, 코드 생성, 빌드, 테스트, archive, resume
- `warn`: Stitch 미설치, ASC 미설정, fastlane 미설치처럼 진행은 가능하지만 결과가 달라지는 상황
- `require_confirmation`: 원격 저장소 생성/푸시, 되돌리기 어려운 외부 시스템 변경

기본 build/resume 파이프라인은 `autonomous`와 `warn`만 사용한다. 원격 저장소 생성/푸시는 기본 범위에서 제외한다.

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

<!-- AUTOBOT_PHASE_SUMMARY:START -->
| Phase | Name | Agent | Parallel | Gate | Max Retry |
|-------|------|-------|----------|------|-----------|
| 0 | Pre-flight & 환경 준비 | (self) | No | → 환경/이름 검증 | 1 |
| 1 | 아키텍처 + 계약 | architect | No | → 산출물 존재/구조 검증 | 2 |
| 2 | UX Design (필수) | ux-designer | No | → Stitch 성공 필수, 미설치 시 fallback | 1 |
| 3 | Xcode 프로젝트 | (self) | No | → .xcodeproj 존재 검증 | 1 |
| 4 | 병렬 코드 생성 | ui-builder + data-engineer + (backend-engineer) | **Yes** | → 파일 존재 + Models/ 무결성 | 2 |
| 5 | 통합 + 빌드 검증 | quality-engineer (`autobot-integration-build` 스킬) | No | → xcodebuild 성공 | 2 |
| 6 | TestFlight 배포 | deployer | No | → 배포 결과 기록 (soft) | 1 |
| 7 | 회고 | (self) | No | — | — |
<!-- AUTOBOT_PHASE_SUMMARY:END -->

## Phase Validation Gates

**매 Phase 완료 직후, 다음 Phase에 진입하기 전에 산출물을 검증한다.**

Gate 통과 실패 시:
1. `retryCount < maxRetry` → 해당 Phase 재실행
2. `retryCount >= maxRetry` → `failed`로 마킹, Phase 7으로 건너뜀

상세 검증 항목은 **`references/phase-gates.md`** 참조.

### `<AppName>/Models/` 무결성 보호

Phase 1 완료 시 `<AppName>/Models/` 디렉토리의 체크섬을 `build-state.json`에 저장하고, `.autobot/contracts/phase-1-models/`에 타입 계약 snapshot을 보관한다.
Gate 4→5에서 체크섬을 재계산하여 비교한다. 불일치 시 git이 아니라 저장된 snapshot으로 자동 복원한다.

```bash
# 체크섬/스냅샷 관리
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" save --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" verify --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore --app-name "<AppName>"
```

## Phase Learning Map

Phase별 학습 파일은 숫자 이름이 아니라 명시적 key를 사용한다:

- Phase 1 → `.autobot/phase-learnings/architecture.md`
- Phase 4 → `.autobot/phase-learnings/parallel_coding.md`
- Phase 5 → `.autobot/phase-learnings/quality.md`
- Phase 6 → `.autobot/phase-learnings/deploy.md`

Phase 0, 2, 3, 7은 `.autobot/active-learnings.md`를 사용한다.

## Pre-flight Check (Phase 0)

Phase 0에서 빌드 시작 전에 환경을 검증:

```
✓ Xcode Command Line Tools 설치됨 (xcode-select -p)
✓ iOS Simulator 런타임 존재 (xcrun simctl list runtimes | grep iOS)
✓ python3 사용 가능 (pbxproj fallback용)
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
   설정 방법: .env 파일에 ASC_API_KEY_ID, ASC_API_ISSUER_ID, ASC_API_KEY_PATH 추가
```

하나라도 필수 항목이 실패하면 빌드를 시작하지 않고 해결 방법을 안내.

## Phase 2: UX Design with Stitch (필수)

Stitch MCP를 사용한 UX 디자인 생성이 기본 경로. 디스패치 조건만 이 스킬에서 판단하고, 상세 워크플로우는 **`autobot-ux-design` 스킬** 참조.

```
if environment.stitch == true:
    → ux-designer 에이전트 디스패치 (autobot-ux-design 스킬 실행)
    → 실패 시 1회 재시도 후, 재실패 시 fallback 전환
else:
    → phases["2"].status = "fallback"
    → ⚠️ "Stitch MCP 미설치. UI는 architecture.md 기반으로 생성됩니다."
    → Phase 3로 진행
```

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
| `<AppName>/App/ServiceStubs.swift` | ui-builder | quality-engineer | 임시 stub (Phase 5에서 App 교체, 파일은 Preview용 보존) |
| `<AppName>/Models/APIContracts.swift` | architect | data-engineer, backend-engineer | API 계약 (SSOT) |
| `<AppName>/Services/*Repository.swift` | data-engineer | quality-engineer | 프로토콜 구현체 |
| `backend/` | backend-engineer | quality-engineer | Docker 백엔드 |
| `.autobot/learnings.json` | retrospective | Phase 0 | 과거 학습 |
| `.autobot/deploy-status.json` | deployer | retrospective | 배포 결과 |

### File Ownership 규칙

> 모든 소스 경로는 `<AppName>/` 서브디렉토리(Xcode 소스 그룹) 기준. `backend/`, `.autobot/`은 프로젝트 루트.
> **전체 테이블과 프롬프트 템플릿은 `references/agent-dispatch.md` 참조.**

핵심 원칙: 각 에이전트는 지정된 디렉토리에만 쓰고, `<AppName>/Models/`는 architect만 생성한다 (다른 에이전트 수정 금지).

### Agent Output Contract

각 에이전트는 아래 네 가지를 항상 만족해야 한다:

- 입력 파일을 직접 읽고 추론한 결과만 사용한다
- 지정된 출력 디렉토리에만 쓴다
- 금지된 디렉토리에 쓰지 않는다
- 완료 시 Gate가 검증할 수 있는 파일 산출물을 남긴다

에이전트가 실패를 보고할 때는 최소한 다음을 포함한다:

- 읽은 입력 파일
- 생성 또는 수정한 파일
- 남은 blocker
- 재시도 시 필요한 추가 맥락

## Backend Mode Quick Reference

`backend_required == true`일 때 영향받는 모든 Phase를 한 곳에서 참조:

| Phase | 추가 작업 | 상세 위치 |
|-------|----------|----------|
| 0 (Pre-flight) | docker 설치 확인, ASC 인증 경고 | 위 Pre-flight 섹션 |
| 1 (Architecture) | Backend Requirements, API Contract, iOS Configuration 섹션 필수 | `references/architecture-template.md` |
| 1→2 Gate | docker --version 검증, APIContracts.swift 존재 확인 | `references/phase-gates.md` Gate 1→2 |
| 3 (Scaffold) | Debug.xcconfig, Release.xcconfig 생성, .gitignore에 backend/.env 추가 | `ios-scaffold` 스킬 |
| 4 (Parallel) | backend-engineer 에이전트 추가 디스패치 (3-agent parallel) | `references/agent-dispatch.md` |
| 4→5 Gate | backend/ 디렉토리, Dockerfile, docker-compose.yml 존재 확인 | `references/phase-gates.md` Gate 4→5 |
| 5 (Quality) | docker compose build + up + health check + down | quality-engineer 에이전트 |
| build-state.json | `backend_required: true`, `backend: { tech_stack, oauth_providers, ... }` | 위 Build State 섹션 |

> backend_required 판정은 Phase 1(architect)에서 수행한다. 판정 로직은 `references/planning-patterns.md`의 "Architecture Decision Tree" 참조.

## Build Infrastructure

Autobot은 빌드 과정의 신뢰성과 관찰 가능성을 높이기 위한 인프라 스크립트를 제공한다.

### Event Log (`build-log.jsonl`)

빌드 과정의 모든 중요 이벤트를 `.autobot/build-log.jsonl`에 append-only로 기록한다. Retrospective(Phase 7)와 디버깅의 1차 데이터 소스.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 1 --event agent_dispatch --agent architect --detail "opus model"
```

이벤트 유형:

| event | 발생 시점 | detail 예시 |
|-------|----------|------------|
| `start` | Phase 시작 | Phase 이름 |
| `env_check` | Phase 0 환경 감지 | `"xcodegen=true, stitch=true"` |
| `agent_dispatch` | 에이전트 디스패치 | 에이전트 이름, 모델 |
| `agent_complete` | 에이전트 완료 | 생성된 파일 수 |
| `agent_violation` | 에이전트 소유권 위반 | 위반 파일 경로 |
| `gate_pass` | Gate 통과 | Gate 이름 |
| `gate_fail` | Gate 실패 | 실패 항목 |
| `build_attempt` | xcodebuild 시도 | `{"attempt":1,"errors":8}` |
| `build_fix` | 빌드 에러 수정 | 수정 카테고리, 파일 |
| `snapshot_save` | 스냅샷 저장 | Phase 번호, 경로 |
| `snapshot_restore` | 스냅샷 복원 | Phase 번호, 사유 |
| `lock_acquired` | 빌드 잠금 획득 | PID |
| `complete` | Phase 완료 | — |

### Pipeline Engine (`pipeline.sh`)

build/resume는 raw 상태 변경 API를 직접 조합하지 않고 `pipeline.sh`를 통해 검증, 상태 기록, lifecycle 로그를 함께 수행한다.

```bash
# JSON 스키마 검증
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" schema

# Phase 시작
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 4 --detail "Parallel coding"

# Phase 완료 / fallback / 실패
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 4
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 2 --status fallback --detail "Stitch unavailable"
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" fail-phase --phase 5 --error "xcodebuild failed" --increment-retry

# Gate 실행 + 결과 기록
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "4->5"
```

`validate-state.sh`는 낮은 수준의 호환용 검증/쓰기 래퍼로 남겨두고, build/resume의 주 경로에서는 직접 사용하지 않는다.

상태 전이 규칙:

```
pending     → in_progress
in_progress → completed | fallback | failed
failed      → in_progress (retry, retryCount < maxRetry)
completed   → (terminal)
fallback    → (terminal)
skipped     → (terminal)
```

### Agent Sandbox (`agent-sandbox.sh`)

에이전트 실행 전후의 파일시스템 diff를 계산하여 파일 소유권 위반을 감지한다.

```bash
# 에이전트 실행 전
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before \
  --agent ui-builder --app-name "<AppName>"

# (에이전트 실행)

# 에이전트 실행 후 — 소유권 위반 자동 감지
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after \
  --agent ui-builder --app-name "<AppName>"
```

### Phase-level Snapshot (`snapshot-contracts.sh` 확장)

Models/ 스냅샷에 더해, Phase 4 완료 시점의 전체 산출물을 스냅샷으로 보관한다. Phase 5 반복 실패 시 Phase 4의 깨끗한 상태로 복원 가능.

```bash
# Gate 4→5 통과 시
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" save-phase \
  --phase 4 --app-name "<AppName>"

# Phase 5 실패 → Phase 4 복원
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase \
  --phase 4 --app-name "<AppName>"
```

지원하는 Phase: 1 (Models), 2 (Designs), 3 (Config), 4 (Views/Services/App/Backend)

### Build Lock (동시 실행 방지)

같은 디렉토리에서 두 빌드가 동시에 실행되는 것을 방지한다. Phase 0에서 잠금을 획득하고, Phase 7 또는 빌드 종료 시 해제한다.

```bash
LOCK_FILE=".autobot/build.lock"
# Phase 0 시작 시 — 잠금 획득 (build.md 참조)
# Phase 7 완료 또는 빌드 종료 시 — 잠금 해제
rm -f "$LOCK_FILE"
```

## Error Recovery

### 재시도 전략

| 에러 유형 | 재시도 방법 | 최대 횟수 |
|----------|-----------|----------|
| 에이전트 산출물 누락 | 같은 에이전트 재실행 | 2 |
| 컴파일 에러 | quality-engineer 반복 수정 | 5 (Phase 내) |
| Phase 자체 실패 | `/autobot:resume`으로 Phase 재실행 | 2 |
| 배포 실패 | deployer 재실행 (멱등) | 1 |

### 롤백 전략

복구 기준점은 git이 아니라 build artifact snapshot이다.

```bash
# Models/ 오염 시 → 타입 계약 snapshot으로 복원
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore --app-name "<AppName>"
```

git은 선택적 보조 도구로만 사용한다. 설계상 복구 가능성은 VCS 상태에 의존하지 않는다.

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
  "bundleId": "com.axi.socialfitness",
  "projectPath": "/Users/saroby/SocialFitness",
  "idea": "소셜 피트니스 트래킹 앱",
  "startedAt": "2026-03-16T12:00:00Z",
  "modelsChecksum": "a1b2c3d4e5f6...",
  "contracts": {
    "modelsSnapshotPath": ".autobot/contracts/phase-1-models",
    "modelsChecksumFile": ".autobot/contracts/models.sha256"
  },
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
                      → fallback
                      → failed → (retry) → in_progress
                                → skipped (circuit breaker)
```

상태 의미:

- `pending`: 아직 시작하지 않음
- `in_progress`: 현재 실행 중
- `completed`: Gate 통과까지 완료
- `fallback`: 대체 경로로 성공적으로 진행
- `failed`: 재시도 전 또는 재시도 한도 초과로 중단
- `skipped`: 정책상 실행하지 않음 또는 circuit breaker로 중단

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
| **`autobot-integration-build` 스킬** | Phase 5 전용: 빌드 에러 진단 트리, Wiring 패턴, 에러 카탈로그 |
