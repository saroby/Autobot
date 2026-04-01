---
name: build
description: "앱 아이디어를 입력하면 질문 없이 엔터프라이즈급 iOS 26+ 앱을 빌드하고 TestFlight에 업로드합니다."
argument-hint: "<앱 아이디어 설명>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
  - WebSearch
  - WebFetch
---

# Autobot Build Orchestrator

사용자의 앱 아이디어를 받아 엔터프라이즈급 iOS 26+ 앱을 완성하여 TestFlight에 배포한다.

**`plugins/autobot/spec/pipeline.json`이 Phase, 상태 전이, Retry, Gate의 단일 기준(SSOT)이다.**
이 문서는 실행 요약만 제공하며, 충돌 시 실행 스펙이 우선한다.
상태 전이, Gate 실행/기록, Phase lifecycle 로그는 **반드시 `scripts/pipeline.sh`를 통해서만** 기록한다.

## CRITICAL RULES

1. **기본은 자율 실행** — 로컬 생성/수정/빌드/테스트는 질문 없이 진행한다
2. **병렬 에이전트를 최대한 활용한다** — 독립적 작업은 반드시 동시에 실행한다
3. **매 Phase 완료/실패마다 `.autobot/build-state.json`을 갱신한다** — 중단 시 `/autobot:resume`으로 재개 가능
4. **CWD 규칙**: Phase 0에서 생성한 프로젝트 디렉토리가 CWD. 모든 에이전트와 스크립트는 이 디렉토리 기준으로 상대 경로를 사용한다. `cd`로 이탈하지 않는다.

## Safety Policy

위험도에 따라 동작을 구분한다:

- `autonomous`: 로컬 파일 생성/수정, 코드 생성, 테스트, 아카이브, Phase 재시도
- `warn`: Stitch 미설치, ASC 미설정, fastlane 미설치처럼 진행은 가능하지만 결과가 달라지는 상황
- `require_confirmation`: 원격 저장소 생성/푸시, 외부 서비스에 되돌리기 어려운 변경을 만드는 작업

기본 파이프라인은 `autonomous`와 `warn`만 사용한다. 원격 저장소 생성/푸시는 build/resume의 기본 범위에서 제외한다.

## Phase 0: Pre-flight 검증 및 환경 준비

### 빌드 잠금 획득 (동시 실행 방지)

다른 빌드가 같은 디렉토리에서 실행 중이면 중단한다:

```bash
LOCK_FILE=".autobot/build.lock"
mkdir -p .autobot
if [ -f "$LOCK_FILE" ]; then
  LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "ERROR: 다른 빌드가 실행 중입니다 (PID: $LOCK_PID). 종료 후 다시 시도하세요."
    exit 1
  else
    echo "WARN: 이전 빌드의 잔여 잠금 파일 제거"
    rm -f "$LOCK_FILE"
  fi
fi
echo $$ > "$LOCK_FILE"
```

### 필수 환경 검증

```bash
xcode-select -p                          # Xcode CLI Tools
xcrun simctl list runtimes | grep -q iOS  # iOS Simulator 런타임
python3 --version                         # Python 3 (pbxproj fallback)
```

하나라도 실패하면 해결 방법을 안내하고 빌드를 중단한다.

### 선택 환경 + 과거 학습

```bash
command -v xcodegen   # → 있으면 사용, 없으면 pbxproj fallback
command -v fastlane   # → 없으면 Phase 6에서 auto-install
```

1. 현재 Phase에 대응하는 `.autobot/phase-learnings/` 파일을 읽기 (있으면) — 현재 Phase에 필요한 학습만 우선 적용
   - Phase 1 → `architecture.md`
   - Phase 4 → `parallel_coding.md`
   - Phase 5 → `quality.md`
   - Phase 6 → `deploy.md`
2. `.autobot/active-learnings.md` 읽기 (있으면) — 공통 교훈의 압축본을 즉시 적용
   - 파일이 없고 `.autobot/learnings.json`만 있으면 필요한 부분만 직접 요약하여 사용
   - phase 파일의 규칙이 공통 파일보다 우선한다
   - `## Prevention Rules`는 architect/ui-builder/data-engineer/quality-engineer/deployer 프롬프트에 주입
   - `## Proven Patterns`는 화면 구조/아키텍처 기본값 선택에 사용
   - `## Deployment Tips`는 Phase 0/6 사전 점검에 반영
3. 플러그인 감지 실행:
   ```bash
   if <mcp__stitch__list_projects 도구가 사용 가능>; then
     bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-plugins.sh" --stitch-tool-available true
   else
     bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-plugins.sh" --stitch-tool-available false
   fi
   ```
   출력된 environment 정보를 `build-state.json`의 `environment` 객체에 반영한다.
   - **Stitch MCP는 필수 경로** — 미설치 시 경고를 출력하고 fallback 모드로 진행

### environment 감지 및 build-state.json 기록 (필수)

Phase 0에서 **반드시** 아래 감지를 수행하고 결과를 `build-state.json`의 `environment` 객체에 기록한다. 이 값들이 이후 Phase의 조건부 로직을 결정한다.

| 항목 | 감지 방법 | 키 |
|------|----------|-----|
| xcodegen | `command -v xcodegen` | `environment.xcodegen` |
| fastlane | `command -v fastlane` | `environment.fastlane` |
| ASC 인증 | `.env`에 `ASC_API_KEY_ID` + `ASC_API_ISSUER_ID` + `ASC_API_KEY_PATH` 존재 | `environment.ascConfigured` |
| Axiom | Skill 도구로 `axiom:axiom-using-axiom` 호출 가능 여부 | `environment.axiom` |
| Stitch MCP | `mcp__stitch__list_projects` 도구 존재 확인 (도구 목록에서 탐색) | `environment.stitch` |

**Stitch 감지 — 반드시 도구 존재로 확인:**
- `mcp__stitch__list_projects` 도구가 사용 가능한 도구 목록에 있으면 → `environment.stitch = true`
- 없으면 → `environment.stitch = false`
- `npx @_davideast/stitch-mcp doctor`는 보조 확인용. **도구 존재 확인이 1차 기준**이다.

`environment.stitch == true`이면 Phase 2가 정상(primary) 경로로 실행된다. `false`이면 Phase 2를 `fallback`으로 마킹하고, 사용자에게 Stitch 미설치 경고를 출력한다.

감지 결과는 수동 편집하지 말고 runtime 엔진으로 기록한다:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" record-environment \
  --xcodegen true \
  --fastlane false \
  --ascConfigured false \
  --axiom true \
  --stitch true
```

**Stitch MCP 미설치 시 즉시 경고:**
```
⚠️ Stitch MCP가 설치되지 않아 UX 디자인 생성 없이 진행합니다.
   UI는 architecture.md 기반으로 생성됩니다 (fallback 모드).
   디자인 일관성을 위해 Stitch 설치를 권장합니다: npx @_davideast/stitch-mcp init
```

**ASC 인증 미설정 시 즉시 경고:**
```
⚠️ App Store Connect 인증 정보가 설정되지 않았습니다.
   Phase 6(TestFlight 배포)가 건너뛰어집니다.
   빌드는 로컬에서만 완료됩니다.
   설정 방법: .env 파일에 ASC_API_KEY_ID, ASC_API_ISSUER_ID, ASC_API_KEY_PATH 추가
```

### 앱 이름 결정

아이디어에서 두 가지 형태를 만든다:

- **identifier name**: ASCII PascalCase (`/^[A-Z][a-zA-Z0-9]*$/`, 2-30자). 한글 → 영어 의역.
- **display name**: 한글/공백/이모지 허용. CFBundleDisplayName에 사용.

identifier name이 Swift 예약어이거나 패턴 미충족 시 재생성.

### 작업 디렉토리 + 상태 파일 초기화

프로젝트 디렉토리 생성 (identifier name 사용), `.autobot/build-state.json` 생성.
Phase 1 이후 타입 계약 복구를 위해 `.autobot/contracts/phase-1-models/` 스냅샷을 유지한다.

상태 파일 스키마는 orchestrator 스킬의 **Build State Management** 섹션 참조. `build-state.json` 초기화 시 **반드시 `environment` 객체를 포함**한다.
수동 JSON 작성 대신 runtime 엔진으로 초기화한다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" init-build \
  --build-id "build-YYYYMMDD-<appname>" \
  --app-name "<AppName>" \
  --display-name "<DisplayName>"
```

**초기화 후 즉시 스키마 검증:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" schema
```

**Phase 0 시작:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 0 --detail "Pre-flight check"
```

초기 build-state.json 구조:

```json
{
  "buildId": "build-YYYYMMDD-appname",
  "appName": "AppName",
  "displayName": "앱 이름",
  "contracts": {
    "modelsSnapshotPath": ".autobot/contracts/phase-1-models",
    "modelsChecksumFile": ".autobot/contracts/models.sha256"
  },
  "environment": {
    "xcodegen": true,
    "fastlane": false,
    "ascConfigured": false,
    "axiom": true,
    "stitch": true
  },
  "phases": { ... }
}
```

`environment.ascConfigured == false`이면 Phase 6에서 업로드를 건너뛴다. `environment.stitch == true`이면 Phase 2를 실행한다.

**상태 전이 검증 후 기록:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 0
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "0->1"
```

**→ Gate 0→1 검증 후 진행**

### 학습 반영 규칙

Phase 0에서 `.autobot/phase-learnings/architecture.md`, `.autobot/phase-learnings/parallel_coding.md`, `.autobot/phase-learnings/quality.md`, `.autobot/phase-learnings/deploy.md`를 확인하고, 해당 Phase 진입 시 그 파일을 먼저 사용한다.

그 다음 `.autobot/active-learnings.md`가 있으면 다음을 즉시 수행한다:

1. phase 전용 파일의 규칙을 각 에이전트 프롬프트 앞부분에 "Known failure prevention" 섹션으로 먼저 전달
2. phase 파일에 없는 공통 `## Prevention Rules`를 보강 규칙으로 전달
3. architecture/parallel_coding에서 phase 파일의 `## Relevant Proven Patterns`를 우선 사용
4. deploy에서 phase 파일의 `## Relevant Deployment Tips`를 우선 사용
5. `## Pending Improvements` 중 미구현 항목이 현재 Phase와 직접 관련되면 같은 실수를 반복하지 않도록 추가 지침으로 반영
6. `## Recent Failure Memory`가 현재와 유사한 앱/Phase이면 해당 실패를 피하는 체크를 Gate 전에 추가

## Phase 1: Architecture + Type Contract

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 1 --detail "Architecture + Type Contract"
```

architect 에이전트를 Agent 도구로 디스패치. TaskCreate로 진행 추적.

**중요**: architect에게 소스 디렉토리 경로(`<AppName>/<AppName>/`)를 전달해야 한다. 모든 소스 파일은 Xcode 소스 그룹인 `<AppName>/` 서브디렉토리에 생성된다.

결과물:
1. `.autobot/architecture.md` — 설계 문서
2. `<AppName>/Models/*.swift` — 컴파일 가능한 @Model 파일 (타입 계약)
3. `<AppName>/Models/ServiceProtocols.swift` — 통합 계약

**→ Gate 1→2**: architecture.md + `<AppName>/Models/` 존재 + 체크섬 저장 + contract snapshot 저장. 실패 시 architect 재실행 (최대 2회).

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 1
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "1->2"
```

### Gate 1→2: backend_required 교차 검증 (필수)

architect가 `backend_required`를 올바르게 설정했는지 **오케스트레이터가 독립적으로 검증**한다:

1. `architecture.md`의 `## Backend Requirements` 섹션을 읽는다
2. 다음 **어느 하나라도** 해당하면 `backend_required`는 `true`여야 한다:
   - `ServiceProtocols.swift`에 외부 AI/LLM API 호출 메서드가 있다 (예: `generate`, `chat`, `analyze`, `summarize` + `async throws`)
   - `architecture.md`에 외부 AI 서비스 이름이 언급된다 (OpenAI, Gemini, Anthropic, DALL-E, Replicate 등)
   - `architecture.md`의 Features에 이미지 생성, 텍스트 생성, AI 분석 등 외부 API가 필요한 기능이 있다
   - `<AppName>/Models/*.swift` 파일 중 외부 API 엔드포인트 URL(예: `generativelanguage.googleapis.com`, `api.openai.com`)이나 API 키 저장 패턴(예: `apiKey`, `API_KEY`, `UserDefaults`)이 포함되어 있다
3. 검증 결과 `backend_required`가 `false`인데 위 조건에 해당하면:
   - `build-state.json`의 `backend_required`를 `true`로 **오버라이드**
   - architect를 **재실행**하여 `## Backend Requirements`, `## API Contract`, `APIContracts.swift` 생성
   - 재실행 프롬프트: "architecture.md에 외부 AI API 호출이 감지되었으나 backend_required가 false입니다. Backend Requirements, API Contract, iOS Configuration 섹션과 APIContracts.swift를 추가하세요. 외부 AI API를 iOS에서 직접 호출하는 설계는 금지됩니다."

> **이 검증이 필요한 이유**: architect가 "사용자가 API 키를 직접 입력" 같은 논리로
> `backend_required = false`를 잘못 판단할 수 있다. 외부 AI API는 반드시
> 백엔드 프록시를 경유해야 한다 (보안, 비용 통제, UX, App Store 리뷰).

## Phase 2: UX Design (Stitch MCP — 필수)

Stitch MCP를 사용한 UX 디자인 생성은 **기본(primary) 경로**다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 2 --detail "UX Design"
```

### Primary 경로 (environment.stitch == true)

ux-designer 에이전트를 Agent 도구로 디스패치.

에이전트에게 전달할 컨텍스트:
- `.autobot/architecture.md` 경로
- 앱 display name과 identifier name
- 화면 목록 (architecture.md의 `## Screens` 섹션)

결과물:
1. `.autobot/designs/*.png` — 화면별 UI 목업 스크린샷
2. `.autobot/design-spec.md` — 디자인 명세 (토큰, 패턴, 구현 가이드)

Phase 완료 시 `build-state.json`에 stitch 정보 기록:
```json
{
  "stitch": {
    "projectId": "<stitch-project-id>",
    "screenCount": 5,
    "designsPath": ".autobot/designs/"
  }
}
```

성공 시:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 2
```

실패 시 1회 재시도. 재실패 시 fallback 모드로 전환.

### Fallback 경로 (environment.stitch == false 또는 Stitch 실패)

Stitch MCP가 설치되지 않았거나 재시도 후에도 실패한 경우:
- `phases["2"].status = "fallback"` 으로 마킹:
  ```bash
  bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 2 --status fallback --detail "Stitch unavailable or failed"
  ```
- ui-builder는 architecture.md만으로 UI를 구현 (디자인 일관성 저하 가능)

**→ Gate 2→3**: Stitch 성공 시 `design-spec.md` + `designs/*.png` 존재 필수. Stitch 미설치 시 `fallback` 상태로 통과.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "2->3"
```

## Phase 3: Xcode 프로젝트 생성

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 3 --detail "Project Scaffold"
```

ios-scaffold 스킬 참조하여 직접 수행. **반드시 `--project-dir .`를 전달**하여 Phase 0에서 생성한 프로젝트 디렉토리를 재사용한다:

```bash
# 기본
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "<AppName>" \
  --bundle-id "<BundleId>" \
  --project-dir "." \
  --deployment-target "26.0"

# backend_required == true일 때 --backend 플래그 추가:
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "<AppName>" \
  --bundle-id "<BundleId>" \
  --project-dir "." \
  --deployment-target "26.0" \
  --backend
```

이렇게 하면 현재 디렉토리(`.`)가 프로젝트 루트, `./<AppName>/`이 소스 디렉토리가 된다.

1. Xcode 프로젝트 생성 (xcodegen 우선, fallback: pbxproj)
2. PrivacyInfo.xcprivacy, .entitlements, .gitignore 생성
3. architecture.md의 Permissions/Dependencies 반영
4. (`--backend`) xcconfig + .gitignore backend/.env 추가

**→ Gate 3→4**: .xcodeproj + 필수 파일 존재 확인.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 3
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "3->4"
```

## Phase 4: 병렬 개발

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 4 --detail "Parallel coding"
```

**에이전트 실행 전 파일시스템 스냅샷 기록:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent ui-builder --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent data-engineer --app-name "<AppName>"
# (backend_required == true일 때)
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent backend-engineer --app-name "<AppName>"
```

**반드시 하나의 메시지에서 Agent 도구를 동시에 호출한다.**

| Agent | subagent_type | Writes To | Reads |
|-------|---------------|-----------|-------|
| ui-builder | `ui-builder` | `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/App/` | `<AppName>/Models/`, design-spec.md (primary), architecture.md (fallback) |
| data-engineer | `data-engineer` | `<AppName>/Services/`, `<AppName>/Utilities/` | `<AppName>/Models/`, architecture.md |
| backend-engineer | `backend-engineer` | `backend/` | `<AppName>/Models/APIContracts.swift`, architecture.md |

backend-engineer는 `build-state.json.backend_required == true`일 때만 디스패치.

**에이전트 완료 후 파일 소유권 검증:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent ui-builder --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent data-engineer --app-name "<AppName>"
# (backend_required == true일 때)
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent backend-engineer --app-name "<AppName>"
```

소유권 위반이 감지되면 이벤트 로그에 기록하고, 위반 파일을 삭제한 후 해당 에이전트만 재실행한다:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 4 --event agent_violation --agent "<agent>" --detail "<violation details>"
```

**→ Gate 4→5**: 파일 존재 + `<AppName>/Models/` 체크섬 무결성 확인. 불일치 시 `.autobot/contracts/phase-1-models/` snapshot으로 복원한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 4
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "4->5"
```

**Gate 4→5 통과 후 Phase 4 스냅샷 저장:**
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" save-phase --phase 4 --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 4 --event snapshot_save --detail "phase-4-snapshot saved"
```
이 스냅샷은 Phase 5 반복 실패 시 Phase 4의 깨끗한 상태로 복원하는 데 사용된다.

## Phase 5: 통합 및 빌드 검증

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 5 --detail "Integration & Build"
```

quality-engineer 에이전트를 Agent 도구로 디스패치. **직접 수행하지 않는다.**

수행 순서: 파일 등록 → App 엔트리포인트에 실제 Repository 주입 (ServiceStubs.swift는 Preview용으로 보존) → SPM Dependencies → Platform Requirements → 빌드 검증(최대 5회) → 테스트 → Docker 검증(해당 시)

**→ Gate 5→6**: BUILD SUCCEEDED + App에서 실제 Repository 사용 + ServiceStubs.swift 존재(Preview용). 실패 시 재실행 (최대 2회).

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 5
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "5->6"
```

**Phase 5 재실행 시 Phase 4 스냅샷 복원 옵션:**
quality-engineer가 Views/Services/App/ 파일을 수정하다가 원본보다 나쁜 상태로 만들 수 있다. Phase 5가 2회 실패하면 Phase 4 스냅샷에서 복원 후 재시도:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase --phase 4 --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event snapshot_restore --detail "phase-4-snapshot restored after 2 failures"
```

## Phase 6: TestFlight 배포

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 6 --detail "TestFlight Deploy"
```

deployer 에이전트를 Agent 도구로 디스패치.

ASC 인증 미설정(`ascConfigured == false`) 시 deployer가 Archive + 로컬 IPA export만 진행.

**→ Soft Gate**: 실패해도 Phase 7 진행.

```bash
# 성공 시:
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 6
# 실패 시:
# bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" fail-phase --phase 6 --error "<deploy error>" --increment-retry
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "6->7"
```

## Phase 7: Retrospective

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 7 --detail "Retrospective"
```

두 가지 산출물을 순서대로 생성:

1. **build-report 스킬** → `.autobot/build-report.md` (플러그인 수준 문제 기록)
2. **retrospective 스킬** → `.autobot/learnings.json` 갱신 (누적 학습)

## 완료 보고

**빌드 잠금 해제:**
```bash
rm -f ".autobot/build.lock"
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" complete-phase --phase 7 --detail "Build pipeline finished"
```

최종 결과를 사용자에게 간결하게 보고:
- 생성된 앱 이름 및 기능 요약
- 프로젝트 경로
- TestFlight 상태 (업로드 성공/실패 및 사유)
- 실패한 Phase가 있으면: **`/autobot:resume`으로 재시도 가능** 안내

**빌드 중 어느 시점에서 중단되더라도** (에러, 사용자 취소 등), 잠금 파일이 남아있을 수 있다. 다음 빌드 시 Phase 0에서 PID 유효성을 확인하고 자동 정리한다.
