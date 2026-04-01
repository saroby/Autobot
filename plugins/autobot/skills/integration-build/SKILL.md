---
name: autobot-integration-build
description: Use when validating and fixing an Autobot-generated iOS app build (Phase 5), wiring service stubs to real repositories, fixing compilation errors iteratively, resolving SPM dependencies, verifying Docker backends, or writing basic tests. Also use when the quality-engineer agent needs guidance on build-fix iteration strategy, error diagnosis, or when the same compilation error keeps recurring across fix attempts.
---

# Integration & Build Validation

Phase 5 스킬: Phase 4에서 병렬 생성된 코드를 통합하고, 컴파일 성공까지 반복 수정한다.

이 Phase가 Autobot 빌드에서 **가장 실패율이 높다** — 별도 에이전트가 생성한 코드 간의 불일치, import 누락, 타입 시그니처 차이가 여기서 드러난다. 체계적 진단 없이 에러를 하나씩 고치면 5회 제한에 도달하므로, **에러를 먼저 분류하고 근본 원인부터 수정**하는 것이 핵심이다.

## 최우선 원칙: Models/ 불가침

`<AppName>/Models/*.swift`는 architect가 정의한 **타입 계약(SSOT)**이다. 어떤 상황에서도 이 파일들을 수정하지 않는다.

에러가 Models/에서 비롯된 것처럼 보여도, 실제 수정은 항상 사용 코드(Views/, ViewModels/, Services/, App/)에서 한다. Models/의 타입 정의를 "정답"으로 놓고, 나머지 코드를 그 정답에 맞추는 것이 올바른 접근이다.

**흔한 함정 — Models/ 수정이 필요해 보이지만 실제로는 아닌 경우:**

| 증상 | 잘못된 수정 (금지) | 올바른 수정 |
|------|-------------------|------------|
| `ForEach`에서 "does not conform to Identifiable" | Models/에 `: Identifiable` 추가 | `ForEach(items, id: \.persistentModelID)` 사용. `@Model` 클래스는 `PersistentModel`을 통해 이미 `id`를 가진다 |
| `NavigationLink(value:)`에서 "does not conform to Hashable" | Models/에 `Hashable` 추가 | `NavigationLink(value: item.persistentModelID)` 사용하고 destination에서 ID로 조회, 또는 `.navigationDestination(for: PersistentIdentifier.self)` 사용 |
| ServiceProtocols.swift에서 "Cannot find type" | ServiceProtocols.swift에 import 추가 | ServiceProtocols.swift도 Models/ 내 파일이므로 수정 금지. 이 에러는 다른 파일의 import 문제에서 연쇄 발생한 것이므로, 사용 코드의 import부터 수정한다 |
| Models/의 타입이 `Int`인데 ViewModel이 `Double`로 사용 | Models/의 타입을 `Double`로 변경 | ViewModel의 타입을 `Int`로 변경 (Models/가 정답) |

## Workflow Overview

```
Step 0: 프로젝트 파일 동기화 (새 .swift 파일 빌드 등록)
    ↓
Step 1: Integration Wiring (Stub → 실제 Repository 교체)
    ↓
Step 2: Platform Requirements (Privacy, Entitlements, Permissions, SPM)
    ↓
Step 3: Build-Fix Loop (최대 5회 반복)
    ↓            ↑ 실패
    ↓         진단 → 분류 → 수정 → 재빌드
    ↓
Step 4: Docker Backend 검증 (조건부)
    ↓
Step 5: Test 작성
    ↓
Step 6: Code Quality Check
```

> **Step 순서가 중요하다**: Step 1~2를 빌드 전에 수행한다. Stub이 남아있거나 Privacy/Entitlements가 누락된 상태에서 빌드하면 교체 후 다시 빌드해야 하므로 시간 낭비다.

## Step 0: 프로젝트 파일 동기화

Phase 4에서 생성된 새 `.swift` 파일을 Xcode 프로젝트에 등록한다.

```bash
# xcodegen이 있으면
if command -v xcodegen &>/dev/null && [ -f project.yml ]; then
  xcodegen generate
# 없으면 pbxproj 재생성
elif [ -f "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/generate-pbxproj.py" ]; then
  python3 "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/generate-pbxproj.py" \
    --name "<AppName>" --bundle-id "<BundleID>" --sources-dir "<AppName>"
fi
```

> **Folder Reference 방식이면 이 단계를 건너뛸 수 있다.** `PBXFileSystemSynchronizedRootGroup`은 파일시스템과 자동 동기화되므로 재생성이 불필요하다. 빌드 시 "파일을 찾을 수 없다" 에러가 나면 그때 재생성한다.

## Step 1: Integration Wiring

ui-builder가 프로토콜 타입(`any XxxServiceProtocol`)과 Stub으로 작성한 코드를, data-engineer의 실제 Repository로 연결한다.

**교체 범위**: App 엔트리포인트(`<AppName>/App/<AppName>App.swift`) **하나만** 수정한다. View/ViewModel은 이미 프로토콜 타입을 사용하므로 수정 불필요.

상세 교체 패턴과 아키텍처별 변형은 **`references/wiring-patterns.md`** 참조.

### 핵심 원칙

1. **ServiceStubs.swift는 절대 삭제하지 않는다** — Preview와 테스트에서 계속 사용. 삭제하면 모든 `#Preview` 블록이 컴파일 에러.
2. **ModelContainer를 stored property로 생성** — `.modelContainer(for:)` modifier는 Environment에 주입하지만, `body` 안에서 `@Environment(\.modelContext)`를 사용할 수 없다. Repository init에 modelContext를 전달하려면 직접 생성해야 한다.
3. **교체 전 init 시그니처 확인**:
   ```bash
   grep -n 'init(' <AppName>/Services/*Repository.swift <AppName>/Services/*Service.swift 2>/dev/null
   ```

### Backend Integration (backend_required == true)

- APIClient가 `Bundle.main`의 `API_BASE_URL`을 사용하는지 확인
- Auth 헤더 주입 로직 존재 확인
- SSE 파싱 코드 존재 확인 (LLM 스트리밍 엔드포인트가 있을 때)
- `backend/.env`가 `.gitignore`에 포함 확인
- `backend/.env.example`에 모든 필수 키 나열 확인

## Step 2: Platform Requirements

architecture.md에 정의된 플랫폼 요구사항을 프로젝트에 반영한다. **빌드 전에 수행.**

### Privacy Manifest

`<AppName>/PrivacyInfo.xcprivacy`를 `.autobot/architecture.md`의 `Privacy API Categories`와 비교하여 누락 항목 추가.

### Entitlements

architecture.md의 `Entitlements` 섹션을 `<AppName>/<AppName>.entitlements`에 반영:

| Capability | Entitlement Key |
|-----------|----------------|
| iCloud | `com.apple.developer.icloud-container-identifiers`, `com.apple.developer.icloud-services` |
| Push | `aps-environment` |
| HealthKit | `com.apple.developer.healthkit` |

### Info.plist 권한

architecture.md의 `Required Permissions`를 빌드 설정에 반영:
- xcodegen: `project.yml`의 `INFOPLIST_KEY_*` 설정
- pbxproj: build settings에 직접 추가
- 예: `INFOPLIST_KEY_NSCameraUsageDescription = "카메라 설명"`

### SPM Dependencies

architecture.md의 `Dependencies` 섹션이 `N/A`가 아닐 때:

1. xcodegen: `project.yml`에 `packages:` + 타겟 `dependencies:` 추가 후 `xcodegen generate`
2. pbxproj: `xcodebuild -resolvePackageDependencies`
3. 빌드 전 패키지 해결:
   ```bash
   xcodebuild -project *.xcodeproj -scheme <scheme> -resolvePackageDependencies 2>&1 | tail -10
   ```

## Step 3: Build-Fix Loop

이 스킬의 핵심. 빌드를 실행하고, 실패하면 에러를 진단하여 수정하는 루프.

### 빌드 명령

```bash
# 사용 가능한 시뮬레이터를 동적으로 탐색
SIM_DEST=$(xcrun simctl list devices available -j | python3 -c "
import json, sys
data = json.load(sys.stdin)
for runtime, devices in data['devices'].items():
    if 'iOS' in runtime:
        for d in devices:
            if 'iPhone' in d['name'] and d['isAvailable']:
                print(f\"platform=iOS Simulator,id={d['udid']}\")
                sys.exit(0)
print('generic/platform=iOS Simulator')
")
xcodebuild -project *.xcodeproj -scheme <scheme> \
  -destination "$SIM_DEST" \
  build 2>&1 | tail -50
```

### 에러 진단 의사결정 트리

빌드 실패 시 에러 메시지를 **먼저 분류**한 다음 수정한다. 분류 없이 하나씩 고치면 5회 제한에 도달하기 쉽다.

```
빌드 에러 발생
├── 에러가 10개 이상인가?
│   ├── Yes → 대부분 같은 근본 원인일 가능성 높음
│   │   ├── 모두 "Cannot find type" → import 누락 (1곳 수정으로 연쇄 해결)
│   │   ├── 모두 같은 파일 → 그 파일의 구조적 문제 (시그니처 불일치)
│   │   └── 파일이 다양 → Phase 4 재생성 고려 (코드 품질이 전체적으로 낮음)
│   └── No → 개별 에러 분류 후 수정
│
├── 에러 분류:
│   ├── [A] Import/Module 에러 → references/build-error-catalog.md "Import 에러" 참조
│   ├── [B] Type/Signature 에러 → references/build-error-catalog.md "타입 에러" 참조
│   ├── [C] Concurrency 에러 → references/build-error-catalog.md "동시성 에러" 참조
│   ├── [D] SwiftData 에러 → references/build-error-catalog.md "SwiftData 에러" 참조
│   └── [E] 프로젝트 설정 에러 → references/build-error-catalog.md "프로젝트 에러" 참조
│
└── 수정 전략:
    ├── 같은 카테고리 에러가 3개 이상 → 근본 원인 1개를 찾아 수정 (연쇄 해결 기대)
    ├── 다른 카테고리 에러가 혼재 → 우선순위: [E] → [A] → [D] → [B] → [C]
    │   (프로젝트 설정 → import → SwiftData → 타입 → 동시성 순서)
    └── 3회 수정 후 같은 에러 반복 → 해당 파일을 처음부터 다시 작성
```

**에러 카테고리별 상세 패턴과 수정법은 `references/build-error-catalog.md` 참조.**

### 반복 전략

각 빌드 시도마다 이벤트 로그에 기록한다:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_attempt \
  --detail "{\"attempt\":${N},\"errors\":${ERROR_COUNT}}"

# 수정 후
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_fix \
  --detail "{\"category\":\"import\",\"files\":[\"Views/HomeView.swift\"]}"
```

| 반복 횟수 | 전략 |
|----------|------|
| 1회차 | 에러 전체 분류 → 근본 원인 수정 → 연쇄 해결 기대 |
| 2회차 | 남은 에러 개별 수정 |
| 3회차 | 남은 에러 개별 수정 + 파일 간 의존성 재확인 |
| 4회차 | 구조적 문제 의심 → 문제 파일을 처음부터 재작성 |
| 5회차 | 최후 시도. 실패하면 Phase 4 스냅샷 복원 또는 재생성 권고 |

### 수정 범위 판단

```
에러를 고칠 때 어디를 수정할 것인가?

에러가 Models/*.swift 파일에서 보고되었는가?
├── Yes → Models/는 절대 수정 금지 (architect의 타입 계약)
│   ├── "Cannot find type" → 연쇄 에러다. 사용 코드의 import부터 수정
│   ├── "does not conform to Identifiable/Hashable" → 함정 에러. 사용 코드에서 해결
│   │   (상세: build-error-catalog.md "함정 에러" 섹션 참조)
│   └── 타입 불일치 → Models/가 "정답". 사용 코드를 Models/에 맞춰 수정
└── No → 에러가 있는 파일을 직접 수정

수정 후 다른 파일에 연쇄 에러가 예상되는가?
├── Yes → 연관 파일도 함께 수정 (한 번의 빌드로 확인)
└── No → 단일 파일 수정 후 빌드
```

## Step 4: Docker Backend 검증

`build-state.json`의 `backend_required == true`일 때만 실행. iOS 빌드 성공 후에 수행한다.

```bash
cd backend && docker compose build
docker compose up -d --wait
curl -f http://localhost:8080/health  # Expected: {"status": "ok"}
docker compose down && cd ..
```

실패 시 진단:

| 실패 지점 | 원인 | 해결 |
|----------|------|------|
| `docker compose build` | requirements.txt 누락/Dockerfile 오류 | 에러 메시지 읽고 수정 |
| `docker compose up` | 포트 충돌 | `lsof -i :8080`으로 확인 후 프로세스 종료 |
| health check | /health 라우트 없음 | `app/main.py`에 health 엔드포인트 추가 |

## Step 5: Test 작성

`<AppName>Tests/` 디렉토리에 기본 테스트를 작성한다.

```swift
import Testing
@testable import AppName

@Suite("Item Model Tests")
struct ItemTests {
    @Test func createItem() {
        let item = Item(name: "Test")
        #expect(item.name == "Test")
        #expect(item.createdAt <= .now)
    }
}
```

최소 기준:
- 각 Data Model에 대해 생성 테스트 1개
- Repository에 대해 기본 CRUD 테스트 (가능하면)

## Step 6: Code Quality Check

빌드 성공 후 코드 품질을 확인한다:

| 항목 | 검증 방법 |
|------|----------|
| Force unwrap 없음 | `grep -rn '!' <AppName>/Views/ <AppName>/ViewModels/ <AppName>/Services/ \| grep -v '//' \| grep '![^=]'` |
| @MainActor on ViewModels | `grep -L '@MainActor' <AppName>/ViewModels/*.swift` |
| 모든 파일에 적절한 import | 빌드 성공으로 검증됨 |
| Swift 6 concurrency 위반 없음 | 빌드 경고 메시지 확인 |

## Gate 5→6 통과 조건

빌드 성공만으로는 부족하다. 다음 모두 충족해야 한다:

```bash
# 1. 빌드 성공
xcodebuild build ... 2>&1 | tail -1 | grep -q "BUILD SUCCEEDED"

# 2. App 엔트리포인트에서 Stub 미사용 확인
! grep -qi "Stub" <AppName>/App/<AppName>App.swift
grep -qi "Repository\|Service(" <AppName>/App/<AppName>App.swift
grep -qi "ModelContainer" <AppName>/App/<AppName>App.swift

# 3. ServiceStubs.swift 존재 확인 (Preview용 보존)
test -f <AppName>/App/ServiceStubs.swift

# 4. Privacy manifest 완성 확인
test -f <AppName>/PrivacyInfo.xcprivacy

# 5. (조건부) Docker 검증 통과
```

## Phase 4 재생성 판단 기준

5회 빌드 수정으로도 해결이 안 되면 코드 자체의 품질이 너무 낮은 것이다. 이때는 무한 수정보다 재생성이 효율적이다.

| 조건 | 액션 |
|------|------|
| 같은 에러 3회 반복 | 해당 파일만 삭제 후 재작성 |
| 에러 10개 이상이 3회 연속 | Phase 4 스냅샷 복원 후 재시도, 또는 Phase 4 전체 재생성 (`/autobot:resume 4`) |
| Models/의 타입과 사용 코드가 구조적 불일치 | Phase 1(architect) 재검토 권고 |

**Phase 4 스냅샷 복원 (Phase 5에서만):**
quality-engineer의 수정이 코드를 악화시킨 경우, Phase 4 완료 시점의 깨끗한 상태로 되돌린다:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase --phase 4 --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event snapshot_restore --detail "Restoring phase-4 snapshot"
```

## Additional Resources

| Reference | 내용 |
|-----------|------|
| **`references/build-error-catalog.md`** | 카테고리별 빌드 에러 패턴 + 수정 레시피 |
| **`references/wiring-patterns.md`** | Integration Wiring 아키텍처별 상세 패턴 |
