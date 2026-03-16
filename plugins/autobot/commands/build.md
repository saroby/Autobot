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

## Phase 0: 환경 준비 및 과거 학습 로드

1. 과거 학습 데이터 확인:
   ```
   Read .autobot/learnings.json (있으면)
   ```
   과거 빌드에서 배운 교훈을 이번 빌드에 적용한다.

2. 설치된 플러그인 자동 감지:
   - `Skill` 도구로 사용 가능한 스킬 목록 파악
   - Axiom 스킬 (ios-ui, ios-data, ios-build 등) 사용 가능 여부 확인
   - Serena 시맨틱 코딩 도구 사용 가능 여부 확인
   - context7 문서 조회 도구 사용 가능 여부 확인
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

## Phase 2: Xcode 프로젝트 생성

ios-scaffold 스킬 참조하여:
1. Xcode 프로젝트 생성 (xcodegen 또는 swift package init)
2. iOS 26+ 타겟 설정
3. 기본 App 엔트리포인트 생성
4. Info.plist 및 에셋 카탈로그 설정
5. 번들 ID 설정: `com.saroby.<identifier name을 소문자로>` (예: `com.saroby.fitnesstracker`)

## Phase 3: 병렬 개발 (핵심 단계)

**반드시 Agent 도구를 사용하여 여러 에이전트를 동시에 실행한다.**

**전제조건**: Phase 1에서 `Models/*.swift` 파일들이 이미 생성되어 있어야 한다. 이 파일들이 두 에이전트 간의 **타입 계약(type contract)** 역할을 한다.

다음 에이전트들을 **하나의 메시지에서 동시에** 실행:

### Agent 1: ui-builder
- `Models/*.swift` 파일들을 **먼저 읽고** 정확한 타입명/이니셜라이저 파악
- `.autobot/architecture.md`를 읽고 SwiftUI 뷰 구현
- iOS 26+ Liquid Glass 스타일 적용
- NavigationStack 기반 네비게이션
- 모든 화면의 뷰 파일 생성
- `App/` 엔트리포인트에서 `.modelContainer(for:)` 에 모든 @Model 타입 등록
- **Models/ 디렉토리의 파일을 절대 수정하지 않는다**
- Axiom ios-ui 스킬 사용 가능하면 활용

### Agent 2: data-engineer
- `Models/*.swift` 파일들을 **먼저 읽고** 정확한 타입명/이니셜라이저 파악
- `.autobot/architecture.md`를 읽고 데이터 접근 레이어 구현
- Repository 패턴 적용 (기존 Model 타입 사용)
- 네트워킹 레이어 (필요시)
- 샘플 데이터 생성 (정확한 이니셜라이저 사용)
- **Models/ 디렉토리의 파일을 절대 수정하지 않는다**
- Axiom ios-data 스킬 사용 가능하면 활용

### Agent 3: quality-engineer (background)
- Phase 3 완료 후 자동 실행
- 기본 단위 테스트 작성
- UI 테스트 스켈레톤
- 빌드 검증

## Phase 4: 통합 및 빌드 검증

1. 모든 에이전트 결과물 통합
2. 컴파일 에러 수정:
   ```bash
   xcodebuild -project *.xcodeproj -scheme <scheme> -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build 2>&1
   ```
3. 에러 있으면 반복 수정 (최대 5회)
4. Axiom ios-build 스킬 사용 가능하면 활용

## Phase 5: TestFlight 배포

testflight-deploy 스킬 참조하여:

1. 코드 사이닝 설정:
   - 사용자의 개발 팀 ID 자동 감지
   - Automatic signing 사용
2. Archive 빌드:
   ```bash
   xcodebuild archive -project *.xcodeproj -scheme <scheme> \
     -archivePath build/<앱이름>.xcarchive \
     -destination 'generic/platform=iOS'
   ```
3. IPA Export + App Store Connect 업로드 (한 단계):
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

## 완료 보고

최종 결과를 사용자에게 간결하게 보고:
- 생성된 앱 이름 및 기능 요약
- 프로젝트 경로
- TestFlight 상태 (업로드 성공/실패 및 사유)
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
