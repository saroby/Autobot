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
  - mcp__github__create_repository
  - mcp__github__push_files
---

# Autobot Build Orchestrator

사용자의 앱 아이디어를 받아 질문 없이 엔터프라이즈급 iOS 26+ 앱을 완성하여 TestFlight에 배포한다.

**상세 Phase 로직, Gate 검증, 에러 복구는 `autobot-orchestrator` 스킬을 참조한다.**

## CRITICAL RULES

1. **절대로 사용자에게 질문하지 않는다** — 모든 결정을 자율적으로 내린다
2. **병렬 에이전트를 최대한 활용한다** — 독립적 작업은 반드시 동시에 실행한다
3. **매 Phase 완료/실패마다 `.autobot/build-state.json`을 갱신한다** — 중단 시 `/autobot:resume`으로 재개 가능

## Phase 0: Pre-flight 검증 및 환경 준비

### 필수 환경 검증

```bash
xcode-select -p                          # Xcode CLI Tools
xcrun simctl list runtimes | grep -q iOS  # iOS Simulator 런타임
python3 --version                         # Python 3 (pbxproj fallback)
git --version                             # Git
```

하나라도 실패하면 해결 방법을 안내하고 빌드를 중단한다.

### 선택 환경 + 과거 학습

```bash
command -v xcodegen   # → 있으면 사용, 없으면 pbxproj fallback
command -v fastlane   # → 없으면 Phase 5에서 auto-install
```

1. `.autobot/learnings.json` 읽기 (있으면) — 과거 빌드 교훈 적용
2. Axiom/Serena/context7 플러그인 감지 (orchestrator 스킬의 Plugin Detection 참조)

**ASC 인증 미설정 시 즉시 경고:**
```
⚠️ App Store Connect 인증 정보가 설정되지 않았습니다.
   Phase 5(TestFlight 배포)가 건너뛰어집니다.
   빌드는 로컬에서만 완료됩니다.
   설정 방법: .env 파일에 ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH 추가
```

### 앱 이름 결정

아이디어에서 두 가지 형태를 만든다:

- **identifier name**: ASCII PascalCase (`/^[A-Z][a-zA-Z0-9]*$/`, 2-30자). 한글 → 영어 의역.
- **display name**: 한글/공백/이모지 허용. CFBundleDisplayName에 사용.

identifier name이 Swift 예약어이거나 패턴 미충족 시 재생성.

### 작업 디렉토리 + 상태 파일 초기화

프로젝트 디렉토리 생성 (identifier name 사용), git init, `.autobot/build-state.json` 생성.

상태 파일 스키마와 `environment` 필드는 orchestrator 스킬의 **Build State Management** 섹션 참조. `ascConfigured`가 `false`이면 Phase 5에서 업로드를 건너뛴다.

**→ Gate 0→1 검증 후 진행**

## Phase 1: Architecture + Type Contract

architect 에이전트를 Agent 도구로 디스패치. TaskCreate로 진행 추적.

**중요**: architect에게 소스 디렉토리 경로(`<AppName>/<AppName>/`)를 전달해야 한다. 모든 소스 파일은 Xcode 소스 그룹인 `<AppName>/` 서브디렉토리에 생성된다.

결과물:
1. `.autobot/architecture.md` — 설계 문서
2. `<AppName>/Models/*.swift` — 컴파일 가능한 @Model 파일 (타입 계약)
3. `<AppName>/Models/ServiceProtocols.swift` — 통합 계약

**→ Gate 1→2**: architecture.md + `<AppName>/Models/` 존재 + 체크섬 저장. 실패 시 architect 재실행 (최대 2회).

## Phase 2: Xcode 프로젝트 생성

ios-scaffold 스킬 참조하여 직접 수행. **반드시 `--project-dir .`를 전달**하여 Phase 0에서 생성한 프로젝트 디렉토리를 재사용한다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "<AppName>" \
  --bundle-id "<BundleId>" \
  --project-dir "." \
  --deployment-target "26.0"
```

이렇게 하면 현재 디렉토리(`.`)가 프로젝트 루트, `./<AppName>/`이 소스 디렉토리가 된다.

1. Xcode 프로젝트 생성 (xcodegen 우선, fallback: pbxproj)
2. PrivacyInfo.xcprivacy, .entitlements, .gitignore 생성
3. architecture.md의 Permissions/Dependencies 반영
4. (backend_required) xcconfig + .gitignore backend/.env 추가

**→ Gate 2→3**: .xcodeproj + 필수 파일 존재 확인.

## Phase 3: 병렬 개발

**반드시 하나의 메시지에서 Agent 도구를 동시에 호출한다.**

| Agent | subagent_type | Writes To | Reads |
|-------|---------------|-----------|-------|
| ui-builder | `ui-builder` | `<AppName>/Views/`, `<AppName>/ViewModels/`, `<AppName>/App/` | `<AppName>/Models/`, architecture.md |
| data-engineer | `data-engineer` | `<AppName>/Services/`, `<AppName>/Utilities/` | `<AppName>/Models/`, architecture.md |
| backend-engineer | `backend-engineer` | `backend/` | `<AppName>/Models/APIContracts.swift`, architecture.md |

backend-engineer는 `build-state.json.backend_required == true`일 때만 디스패치.

**→ Gate 3→4**: 파일 존재 + `<AppName>/Models/` 체크섬 무결성 확인. 불일치 시 `git checkout -- <AppName>/Models/` 복원.

## Phase 4: 통합 및 빌드 검증

quality-engineer 에이전트를 Agent 도구로 디스패치. **직접 수행하지 않는다.**

수행 순서: 파일 등록 → stub→Repository 교체 → Platform Requirements → 빌드 검증(최대 5회) → 테스트 → Docker 검증(해당 시)

**→ Gate 4→5**: BUILD SUCCEEDED + ServiceStubs.swift 삭제 완료. 실패 시 재실행 (최대 2회).

## Phase 5: TestFlight 배포

deployer 에이전트를 Agent 도구로 디스패치.

ASC 인증 미설정(`ascConfigured == false`) 시 deployer가 Archive + 로컬 IPA export만 진행.

**→ Soft Gate**: 실패해도 Phase 6 진행.

## Phase 6: Retrospective

두 가지 산출물을 순서대로 생성:

1. **build-report 스킬** → `.autobot/build-report.md` (플러그인 수준 문제 기록)
2. **retrospective 스킬** → `.autobot/learnings.json` 갱신 (누적 학습)

## 완료 보고

최종 결과를 사용자에게 간결하게 보고:
- 생성된 앱 이름 및 기능 요약
- 프로젝트 경로
- TestFlight 상태 (업로드 성공/실패 및 사유)
- 실패한 Phase가 있으면: **`/autobot:resume`으로 재시도 가능** 안내
