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

## CRITICAL RULES

1. **절대로 사용자에게 질문하지 않는다** - 모든 결정을 자율적으로 내린다
2. **병렬 에이전트를 최대한 활용한다** - 독립적 작업은 반드시 동시에 실행한다
3. **Axiom 스킬이 있으면 활용한다** - 하지만 없어도 동작해야 한다
4. **과거 학습을 먼저 확인한다** - `.autobot/learnings.json` 파일이 있으면 읽는다
5. **매 Phase 완료/실패마다 `.autobot/build-state.json`을 갱신한다** - 중단 시 `/autobot:resume`으로 재개 가능

## Phase 0: Pre-flight 검증 및 환경 준비

### Pre-flight Check (빌드 시작 전 필수 검증)

```bash
# 필수 — 하나라도 실패하면 빌드 시작하지 않음
xcode-select -p                          # Xcode CLI Tools
xcrun simctl list runtimes | grep -q iOS  # iOS Simulator 런타임
python3 --version                         # Python 3 (pbxproj fallback)
git --version                             # Git
```

실패 시 해결 방법을 안내하고 빌드를 중단한다.

### 환경 탐색 (선택 — 없어도 진행)

```bash
command -v xcodegen   # → 있으면 사용, 없으면 pbxproj fallback
command -v fastlane   # → 없으면 Phase 5에서 auto-install
# ASC 인증: .env에서 확인 (SessionStart 훅이 systemMessage로 전달)
```

### 과거 학습 + 플러그인 감지

1. 과거 학습 데이터 확인:
   ```
   Read .autobot/learnings.json (있으면)
   ```
   과거 빌드에서 배운 교훈을 이번 빌드에 적용한다.

2. 설치된 플러그인 자동 감지:
   - `Skill` 도구로 Axiom 스킬 사용 가능 여부 확인
   - Serena, context7 도구 존재 여부 확인
   - 사용 가능한 도구는 활용하되, 없으면 기본 도구로 진행

3. 앱 이름 결정:
   아이디어에서 앱 이름을 추출할 때 **반드시 두 가지 형태**를 만든다:

   - **identifier name** (필수): ASCII PascalCase. 디렉토리명, Swift 모듈명, 번들 ID에 사용.
     - 규칙: 영문+숫자만, 대문자로 시작, 공백/특수문자/한글 불가
     - 예: `FitnessTracker`, `RecipeShare`, `DailyMemo`
     - 한글 아이디어는 영어로 의역: "소셜 피트니스" → `SocialFitness`
   - **display name** (선택): 사용자에게 보이는 이름. 한글, 공백, 이모지 허용.
     - 예: `피트니스 트래커`, `레시피 공유`
     - CFBundleDisplayName에 사용

   identifier name 검증 규칙:
   ```
   1. /^[A-Z][a-zA-Z0-9]*$/ 패턴 충족 (영문 대문자 시작, 영숫자만)
   2. Swift 예약어 불가 (Class, Type, Self, Protocol 등)
   3. 2-30자 이내
   4. 이 규칙을 통과하지 못하면 빌드를 시작하지 않고 이름을 재생성
   ```

4. 작업 디렉토리 준비:
   - 프로젝트용 새 디렉토리 생성 (**identifier name** 사용)
   - Git 초기화
   - `.autobot/` 디렉토리 생성 (빌드 메타데이터용)

5. **빌드 상태 파일 초기화** (`.autobot/build-state.json`):
   ```json
   {
     "buildId": "build-YYYYMMDD-identifiername",
     "appName": "<identifier name>",
     "displayName": "<display name>",
     "bundleId": "com.saroby.<identifier name 소문자>",
     "projectPath": "<프로젝트 절대 경로>",
     "idea": "<사용자 입력 아이디어 원문>",
     "startedAt": "<ISO 8601>",
     "phases": {
       "0": { "status": "completed", "completedAt": "<ISO 8601>" },
       "1": { "status": "pending" },
       "2": { "status": "pending" },
       "3": { "status": "pending" },
       "4": { "status": "pending" },
       "5": { "status": "pending" },
       "6": { "status": "pending" }
     }
   }
   ```
   이 파일은 매 Phase 완료/실패 시 갱신된다. 중단되면 `/autobot:resume`으로 재개할 수 있다.

## Phase 1: 앱 아키텍처 설계 + 타입 계약 생성 (architect 에이전트)

TaskCreate로 전체 빌드 진행 상황을 추적한다.

architect 에이전트를 Agent 도구로 실행:
- 앱 아이디어 분석
- 핵심 기능 3-7개 정의
- 화면 목록 및 네비게이션 구조 설계
- 데이터 모델 (@Model) 설계
- 네트워킹 API 구조 설계 (필요시)
- **컴파일 가능한 Swift @Model 파일 생성** (타입 계약)

결과물:
1. `.autobot/architecture.md` — 설계 문서
2. `<프로젝트>/Models/*.swift` — **컴파일 가능한 @Model 클래스 파일들** (타입 계약)
   - 모든 stored property, initializer, @Relationship 포함
   - 관련 enum 정의 포함
   - 네트워킹 필요 시 Codable response 타입 포함

이 Model 파일들이 Phase 3 병렬 에이전트들의 **공유 타입 계약** 역할을 한다.

**→ Gate 1→2 검증** (orchestrator/references/phase-gates.md 참조):
- `.autobot/architecture.md` 존재, `## Screens`/`## Integration Map`/`## Privacy API Categories` 섹션 포함
- `Models/*.swift` 1개 이상 존재, `Models/ServiceProtocols.swift` 존재
- 모든 Models/*.swift에 `import` 문 포함
- **Models/ 체크섬 저장**: `find Models/ -name "*.swift" -exec md5 {} \; | sort | md5` → `build-state.json.modelsChecksum`에 기록
- Gate 실패 시 → architect 재실행 (최대 2회)

**→ Gate 통과 시 `build-state.json`의 `phases.1`을 `{"status": "completed", "completedAt": "<ISO 8601>"}` 로 갱신**

## Phase 2: Xcode 프로젝트 생성

ios-scaffold 스킬 참조하여:
1. Xcode 프로젝트 생성 (xcodegen 또는 built-in pbxproj generator)
2. iOS 26+ 타겟 설정
3. 기본 App 엔트리포인트 생성
4. Info.plist 및 에셋 카탈로그 설정
5. 번들 ID 설정: `com.saroby.<identifier name을 소문자로>` (예: `com.saroby.fitnesstracker`)
6. `.gitignore` 생성 (DerivedData, build artifacts 등 제외)
7. `PrivacyInfo.xcprivacy` 생성 후, `.autobot/architecture.md`의 Privacy API Categories 반영
8. `.entitlements` 파일에 architecture.md의 Entitlements 반영
9. architecture.md의 Required Permissions를 빌드 설정에 반영:
   - xcodegen: `project.yml`의 `INFOPLIST_KEY_` 설정에 추가
   - fallback: `generate-pbxproj.py`의 build settings에 추가
   - 예: `INFOPLIST_KEY_NSCameraUsageDescription = "카메라 접근 설명"`
10. architecture.md에 Dependencies가 있으면:
    - xcodegen: `project.yml`에 `packages` 및 `dependencies` 추가
    - fallback: `Package.swift` 생성 후 xcodebuild가 resolve

**→ Gate 2→3 검증**: `.xcodeproj` 존재, `project.pbxproj` 크기 > 0, `PrivacyInfo.xcprivacy` 존재, `.entitlements` 존재, `.gitignore` 존재
**→ Gate 통과 시 `build-state.json`의 `phases.2`를 `{"status": "completed", "completedAt": "<ISO 8601>"}` 로 갱신**

## Phase 3: 병렬 개발 (핵심 단계)

**반드시 Agent 도구를 사용하여 여러 에이전트를 동시에 실행한다.**

**전제조건**: Phase 1에서 `Models/*.swift` 및 `Models/ServiceProtocols.swift` 파일들이 이미 생성되어 있어야 한다. Model 파일들이 타입 계약, Service 프로토콜이 통합 계약 역할을 한다.

### 격리 전략: 파일 소유권 규칙

에이전트들은 **파일 소유권 규칙**으로 충돌을 방지한다. 각 에이전트가 쓸 수 있는 디렉토리가 완전히 분리되어 있으므로 별도 격리 없이 병렬 실행이 안전하다:

| Agent | Writes To | MUST NOT Touch |
|-------|-----------|----------------|
| ui-builder | `Views/`, `ViewModels/`, `App/` | `Models/`, `Services/` |
| data-engineer | `Services/`, `Utilities/` | `Models/`, `Views/`, `ViewModels/`, `App/` |
| backend-engineer | `backend/` | 그 외 전부 |

다음 에이전트들을 **하나의 메시지에서 동시에** 실행:

### Agent 1: ui-builder
- `Models/*.swift` 파일들을 **먼저 읽고** 정확한 타입명/이니셜라이저 파악
- `Models/ServiceProtocols.swift`를 읽고 ViewModel이 의존할 프로토콜 파악
- `.autobot/architecture.md`를 읽고 SwiftUI 뷰 구현
- iOS 26+ Liquid Glass 스타일 적용
- NavigationStack 기반 네비게이션
- 모든 화면의 뷰 파일 생성
- ViewModel은 **Service 프로토콜**에 의존 (구현체가 아닌 인터페이스)
- `App/` 엔트리포인트에서 `.modelContainer(for:)` 에 모든 @Model 타입 등록
- `App/ServiceStubs.swift`에 프로토콜의 임시 stub 구현 생성
- **Models/ 디렉토리의 파일을 절대 수정하지 않는다**
- Axiom ios-ui 스킬 사용 가능하면 활용

### Agent 2: data-engineer
- `Models/*.swift` 파일들을 **먼저 읽고** 정확한 타입명/이니셜라이저 파악
- `Models/ServiceProtocols.swift`를 읽고 구현할 프로토콜 파악
- `.autobot/architecture.md`를 읽고 데이터 접근 레이어 구현
- **Service 프로토콜을 구현하는 Repository** 생성 (정확한 메서드 시그니처 준수)
- 네트워킹 레이어 (필요시)
- 샘플 데이터 생성 (정확한 이니셜라이저 사용)
- **Models/ 디렉토리의 파일을 절대 수정하지 않는다**
- Axiom ios-data 스킬 사용 가능하면 활용

**→ Gate 3→4 검증**:
- `Views/` 에 .swift 1개+, `ViewModels/` 에 .swift 1개+, `Services/` 에 .swift 1개+
- `App/<AppName>App.swift`에 `.modelContainer` 포함
- **Models/ 무결성**: 체크섬 재계산 → `build-state.json.modelsChecksum`과 비교
  - 불일치 → `git checkout -- Models/` 자동 복원 후 Gate 재검증
- 에이전트 간 파일 소유권 위반 없음 (각자 지정 디렉토리에만 쓰기)
- Gate 실패 시 → Phase 3 재실행 (최대 2회)

**→ Gate 통과 시 `build-state.json`의 `phases.3`을 `{"status": "completed"}` 로 갱신**
**→ Gate 2회 실패 시 `phases.3`을 `{"status": "failed", "error": "..."}` 로 갱신하고 Phase 6(회고)으로 건너뜀**

## Phase 4: 통합 및 빌드 검증

1. **Xcode 프로젝트에 새 파일 등록** (Phase 3에서 생성된 .swift 파일들):
   - xcodegen: `xcodegen generate` 재실행 (sources를 자동 스캔)
   - fallback: `generate-pbxproj.py` 재실행 (재귀 탐색으로 모든 .swift 파일 등록)
   - 이 단계 없으면 Phase 3에서 만든 파일이 빌드에 포함되지 않음
3. **Integration Wiring**: `App/ServiceStubs.swift`를 삭제하고, 실제 Repository 구현체로 연결
   - App 엔트리포인트에서 `ModelContainer` → `Repository` → `ViewModel` 주입 체인 구성
4. **PrivacyInfo.xcprivacy 보완**: `.autobot/architecture.md`의 Privacy API Categories를 확인하고 빠진 항목 추가
5. **Entitlements 보완**: architecture.md의 Entitlements 항목을 `.entitlements` 파일에 반영
6. 컴파일 에러 수정:
   ```bash
   xcodebuild -project *.xcodeproj -scheme <scheme> -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build 2>&1
   ```
7. 에러 있으면 반복 수정 (최대 5회)
8. Axiom ios-build 스킬 사용 가능하면 활용

**→ Gate 4→5 검증**:
- `xcodebuild build` 종료 코드 == 0 ("BUILD SUCCEEDED")
- `App/ServiceStubs.swift` 삭제 완료
- `PrivacyInfo.xcprivacy`에 architecture.md의 모든 API 카테고리 반영됨
- Gate 실패 시 → quality-engineer 재실행 (최대 2회, 이전 에러 전달)

**→ Gate 통과 시 `build-state.json`의 `phases.4`를 `{"status": "completed"}` 로 갱신**
**→ Gate 2회 실패 시 `phases.4`를 `{"status": "failed", "error": "..."}` 로 갱신하고 Phase 6(회고)으로 건너뜀**

## Phase 5: TestFlight 배포

testflight-deploy 스킬 참조하여:

1. **App Store Connect 앱 등록** (fastlane produce):
   - fastlane 설치 확인 (`brew install fastlane` 없으면 자동 설치)
   - `fastlane produce create`로 App ID + ASC 앱 등록 (멱등 — 이미 있으면 스킵)
   - 번들 ID: `com.saroby.<identifier name 소문자>`
   - 앱 이름: architecture.md의 display name
   - 언어: ko, SKU: 번들 ID와 동일
2. 코드 사이닝 설정:
   - 사용자의 개발 팀 ID 자동 감지
   - Automatic signing 사용
3. Archive 빌드:
   ```bash
   xcodebuild archive -project *.xcodeproj -scheme <scheme> \
     -archivePath build/<앱이름>.xcarchive \
     -destination 'generic/platform=iOS'
   ```
4. IPA Export + App Store Connect 업로드 (한 단계):
   ```bash
   xcodebuild -exportArchive \
     -archivePath build/<앱이름>.xcarchive \
     -exportOptionsPlist ExportOptions.plist \
     -exportPath build/export \
     -allowProvisioningUpdates \
     -authenticationKeyPath "$ASC_API_KEY_PATH" \
     -authenticationKeyID "$ASC_API_KEY_ID" \
     -authenticationKeyIssuerID "$ASC_API_ISSUER_ID"
   ```
   ExportOptions.plist에 `destination: upload`를 설정하면 export와 업로드가 동시에 수행된다.

5. TestFlight 테스터 그룹 설정:
   - '내부' 그룹 생성 (App Store Connect API 사용)
   - 사용자의 Apple 계정 초대
   - 빌드를 그룹에 할당

**→ Phase 5 완료 시 `build-state.json`의 `phases.5`를 `{"status": "completed", "completedAt": "<ISO 8601>"}` 로 갱신**
**→ Phase 5 실패 시 `phases.5`를 `{"status": "failed", "error": "<에러 메시지>", "failedAt": "<ISO 8601>"}` 로 갱신하고 Phase 6(회고)으로 건너뜀**

## Phase 6: 회고 및 자기 개선

retrospective 스킬 참조하여:

1. 빌드 과정에서 발생한 이슈 정리
2. 성공/실패 패턴 분석
3. `.autobot/learnings.json` 업데이트:
   ```json
   {
     "builds": [
       {
         "date": "2026-03-16",
         "app": "앱이름",
         "issues": ["이슈1", "이슈2"],
         "solutions": ["해결1", "해결2"],
         "duration_phases": {"planning": 30, "coding": 120, "deploy": 60},
         "success": true
       }
     ],
     "patterns": {
       "common_build_errors": [...],
       "effective_architectures": [...],
       "deployment_tips": [...]
     }
   }
   ```

**→ Phase 6 완료 시 `build-state.json`의 `phases.6`을 `{"status": "completed", "completedAt": "<ISO 8601>"}` 로 갱신**

## 완료 보고

최종 결과를 사용자에게 간결하게 보고:
- 생성된 앱 이름 및 기능 요약
- 프로젝트 경로
- TestFlight 상태 (업로드 성공/실패 및 사유)
- 실패한 Phase가 있으면: **`/autobot:resume`으로 재시도 가능** 안내
- 다음에 개선할 점 (있으면)

## 플러그인 감지 패턴

설치된 플러그인을 감지할 때 다음 패턴을 사용:
```
# Axiom 스킬 사용 가능 여부 확인
Skill 도구로 "axiom:axiom-ios-ui" 호출 시도
→ 성공하면 Axiom 사용, 실패하면 기본 지식으로 진행

# Serena 도구 사용 가능 여부 확인
mcp__plugin_serena_serena__find_symbol 등의 도구 존재 여부 확인
→ 있으면 시맨틱 편집 활용, 없으면 일반 편집

# context7 문서 조회
mcp__context7__resolve-library-id 도구 존재 여부 확인
→ 있으면 최신 라이브러리 문서 참조
```

이 패턴들은 플러그인에 의존하지 않고, 있으면 활용하는 방식이다.
