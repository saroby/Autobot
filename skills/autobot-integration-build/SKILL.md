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
elif [ -f "$CLAUDE_PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/generate-pbxproj.py" ]; then
  python3 "$CLAUDE_PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/generate-pbxproj.py" \
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

> **Export Compliance contract**: `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption` 는 scaffold 의 두 generator 가 이미 `NO` 로 emit 한다 (CONVENTIONS.md "iOS project content contract"). 권한을 추가할 때 이 키를 제거하지 말 것 — 누락되면 archive 단계에서 차단된다.

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
  build 2>&1 | tee /tmp/xcb-attempt-${ATTEMPT}.log | tail -50
```

### Error Signature 기록 (필수, 매 attempt 후)

빌드가 실패한 직후 stderr 를 `error_signature.py` 로 정규화해 누적한다. 같은 시그니처가 spec `policies.circuitBreaker.errorSignatureRepeat.maxRepeats` (기본 2) 만큼 반복되면 breaker 가 트립되어 더 이상 동일 에러를 고치지 않는다 — 시간 낭비 방지.

```bash
SIGNATURE_RESULT=$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/error_signature.py" \
  record --phase 5 --stderr-file /tmp/xcb-attempt-${ATTEMPT}.log)
echo "$SIGNATURE_RESULT"  # {"tripped":true|false,"occurrences":N,"hash":"..."}

# 매 attempt 를 이벤트로도 남긴다 (run-summary 가 사용)
HASH=$(echo "$SIGNATURE_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['hash'])")
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase 5 --event build_fix_attempt \
  --detail "{\"attempt\":${ATTEMPT},\"signature\":\"${HASH}\",\"category\":\"<A|B|C|D|E>\"}"

# breaker 가 트립되면 더 고치지 말고 Phase 4 스냅샷으로 복원
if echo "$SIGNATURE_RESULT" | grep -q '"tripped":true'; then
  bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase --phase 4 --app-name "<AppName>"
  bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_fix_loop_exhausted \
    --detail "{\"attempts\":${ATTEMPT},\"lastSignature\":\"${HASH}\",\"abortStrategy\":\"snapshot_restore_then_handoff\"}"
  exit 1
fi
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

각 빌드 시도마다 이벤트 로그에 기록한다. detail의 `succeeded` 필드는 필수 (true/false):

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_attempt \
  --detail "{\"attempt\":${N},\"errors\":${ERROR_COUNT},\"succeeded\":false}"

# 수정 후
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_fix \
  --detail "{\"category\":\"import\",\"files\":[\"Views/HomeView.swift\"]}"
```

빌드가 성공하는 순간 다음 두 가지를 **모두** 기록한다 (Gate 5→6의 truth source는 metadata, build-log는 audit only):

```bash
# 감사 로그
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event build_attempt \
  --detail "{\"attempt\":${N},\"errors\":0,\"succeeded\":true}"

# Gate가 읽는 truth source — 최종 advance-phase 호출에 포함 필수
# visualJudge 는 Step 9 가 스크린샷을 얻었을 때만 포함한다 (없으면 Gate 가 benign-skip).
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 5 \
  --metadata build_succeeded=true \
  --metadata 'peerReview={"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}' \
  --metadata 'visualJudge={"verdict":"pass","highCount":0,"summary":"design tokens applied"}'
```

> `metadata.build_succeeded=true`와 `metadata.peerReview`가 최종 `advance-phase` 호출에 포함되지 않으면 Gate 5→6는 실패한다. `visualJudge`(Step 9)는 스크린샷을 얻은 경우 함께 전달한다 — 없으면 `visual_judge` 체크가 green-skip 한다.
> `advance-phase`는 metadata를 gate 평가 전에 반영한 뒤 통과 시 `completed`까지 한 번에 기록한다.

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

## Step 5: Authored 테스트 작성 (컴파일 + 통과 필수)

`<AppName>Tests/` 디렉토리에 Swift Testing 테스트를 작성한다. 이 테스트는 **반드시 컴파일되고 통과해야 한다** — Gate 5→6 의 `logic_tests_pass` 체크가 `xcodebuild test` 를 실행해 `.xcresult` 를 파싱하므로, 빌드만 성공하고 테스트가 깨지면 Gate 5→6 는 hard-fail 한다.

### 5a. P0 logic acceptance 당 1개 테스트 (이름 규칙 필수)

`.autobot/feature-spec.json` 의 각 P0 feature 에서 `kind == "logic"` 인 acceptance 마다, **acceptance id 와 동일한 이름의 `@Test func`** 를 작성한다. `check_logic_tests_pass` 의 completeness 서브체크가 authored 테스트 이름을 acceptance id 와 대조한다 (`addItem_increasesCount` ↔ `func addItem_increasesCount()`). 이름이 일치하지 않으면 비차단 WARNING 이 run-summary 에 남는다.

```swift
import Testing
@testable import <AppName>

@Suite("Logic acceptances")
struct LogicAcceptanceTests {
    // acceptance id "addItem_increasesCount" (P0, kind=logic) 에 대응
    @Test func addItem_increasesCount() throws {
        let store = ItemStore.inMemory()   // ServiceStubs / in-memory ModelContainer 사용
        let before = store.items.count
        store.add(Item(name: "X"))
        #expect(store.items.count == before + 1)   // postcondition: count_increased
    }
}
```

규칙:
- 테스트는 acceptance 의 `postcondition.kind` 를 실제로 검증한다 (`count_increased`, `value_persisted_after_relaunch` 등) — 단순 `#expect(true)` 금지.
- `flow` kind acceptance 는 여기서 다루지 않는다 (UI 구동은 Gate 5→6 의 `functional_flows_pass` 가 AXe 로 검증).
- 각 Data Model 생성 테스트 1개 + 가능하면 Repository CRUD 테스트도 추가.

### 5b. 컴파일 + 통과 확인

```bash
# Gate 와 동일 경로: integration_build(test=True) 가 호출하는 명령과 같다.
xcodebuild -project *.xcodeproj -scheme <AppName> \
  -destination "$SIM_DEST" \
  -resultBundlePath /tmp/Tests.xcresult \
  test 2>&1 | tail -30

# .xcresult 요약 파싱 (Gate 가 쓰는 것과 동일)
xcrun xcresulttool get test-results summary --path /tmp/Tests.xcresult --compact \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'], d['passedTests'],'/',d['totalTestCount'])"
# Expected: Passed N / N
```

테스트가 컴파일 실패하거나 1개라도 실패하면 Step 3 (Build-Fix Loop) 로 돌아가 수정한 뒤 재실행한다. `xcodebuild`/시뮬레이터가 없는 환경에서는 Gate 가 degraded-skip 으로 처리하므로 로컬 통과 여부를 기록만 한다.

## Step 6: Code Quality Check

빌드 성공 후 코드 품질을 확인한다:

| 항목 | 검증 방법 |
|------|----------|
| Force unwrap 없음 | `grep -rn '!' <AppName>/Views/ <AppName>/ViewModels/ <AppName>/Services/ \| grep -v '//' \| grep '![^=]'` |
| @MainActor on ViewModels | `grep -L '@MainActor' <AppName>/ViewModels/*.swift` |
| 모든 파일에 적절한 import | 빌드 성공으로 검증됨 |
| Swift 6 concurrency 위반 없음 | 빌드 경고 메시지 확인 |

## Step 7: Axiom Critical Audit (선택, soft-skip)

빌드가 통과하고 Step 6의 grep 체크가 끝났으면, `autobot-axiom-bridge` 스킬의 **Mode 1 (Gate-5 Critical Audit)** 을 실행한다. Axiom 플러그인이 설치되어 있을 때만 동작하며, 미설치 환경에서는 한 줄 로그만 남기고 즉시 통과한다.

```bash
Read $CLAUDE_PLUGIN_ROOT/skills/autobot-axiom-bridge/SKILL.md
```

목적:
- Swift 6 data race / SwiftData 스키마 실수 / 메모리 누수 / SwiftUI 구조 위반처럼 **빌드는 통과하지만 런타임에서 깨지는 4개 클래스**를 한 번에 잡는다.
- 발견된 critical 항목은 Step 3 (Build-Fix Loop) 의 다음 배치로 처리해 수정 → 재빌드 → critical 항목만 재감사 사이클을 돌린다.
- `phases.5.metadata.axiom_critical_audit` 에 결과를 기록 (`ran`, `auditors`, `critical_count`, `findings_path`).

호출 규칙은 bridge 스킬에 SSOT 로 정리되어 있다. 이 스킬에서는 다음만 기억한다:

- Axiom 부재 → soft skip, Gate 5→6 통과에 영향 없음.
- critical 0건 → Gate 5→6 진행.
- critical > 0 → `build_succeeded` 플래그를 켜기 전에 Step 3 로 돌아가 fix_hint 를 따라 수정. 5회 한계 도달 시 회고로 우회.

## Step 8: Opposite-Runtime Peer Review (필수 시도, soft-skip)

빌드와 Axiom critical audit 이 통과했으면 `autobot-peer-review-bridge` 스킬을 실행한다. 현재 실행 위치가 Codex면 Claude에게, Claude면 Codex에게 Phase 5 산출물을 리뷰시킨다.

```bash
Read $CLAUDE_PLUGIN_ROOT/skills/autobot-peer-review-bridge/SKILL.md
```

기록 규칙:

- `phases.5.metadata.peerReview.verdict == "PASS"` → Gate 5→6 진행.
- peer 도구 부재/호출 실패 → `verdict="skipped"` 와 `skipReason` 기록 후 진행.
- `verdict == "FAIL"` → `blockingFindings` 를 Step 3 Build-Fix Loop 의 다음 에러 배치로 처리한다.
- 누락은 실패다. Gate 5→6 의 `peer_review_acceptable` 체크가 `peerReview` 기록을 강제한다.

## Step 9: Visual Fidelity Judge (멀티모달, soft → DEGRADED-only)

빌드와 peer review 가 통과했으면, **빌드된 앱의 실제 화면이 디자인 의도를 충실히 구현했는지** 멀티모달로 판정한다. deltaE 색-매치(`check_visual_contract`)는 informational-only 라 디자인을 무시한 빌드(예: 디자인은 커스텀 coral 인데 system-blue 로 렌더)도 통과시킨다 — 이 step 이 그 격차를 메운다. Phase 2.5 plan-preview 가 *목업*을 비평하는 것과 달리, 여기선 *빌드 산출물*을 디자인 의도와 **비교**한다.

### 9a. 런타임 스크린샷 확보

```bash
JUDGE_SHOT=$(python3 "$CLAUDE_PLUGIN_ROOT/scripts/sim_runtime.py" \
  --project-dir "$PWD" --app-name "<AppName>" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('screenshotPath') or '')")
```

- 스크린샷을 못 얻으면 (`simctl`/시뮬레이터/빌드 부재) `JUDGE_SHOT` 가 빈 값 → **이 step 을 건너뛴다** (verdict 미기록). 이때 Gate 의 `visual_judge` 는 스크린샷도 없으므로 benign-skip(green); runtime_smoke 가 별도로 degraded 처리한다.
- **반대로 스크린샷을 얻었으면 verdict 를 반드시 기록해야 한다.** 스크린샷이 디스크에 있는데 `visualJudge` verdict 가 없으면 Gate 의 `visual_judge` 가 **DEGRADED** 처리한다 (anti-laundering — 검증 가능했는데 안 한 빌드를 VERIFIED 로 세탁 금지, `functional_flows_pass`/`peer_review_acceptable` 와 동일 원칙). 즉 sim 이 있는 환경에서 9b–9c 를 건너뛰면 배지가 DEGRADED 로 떨어진다.

### 9b. 충실도 판정 (Read 로 이미지 직접 분석)

`JUDGE_SHOT` 가 있으면 다음을 Read 해 **비교**한다. **1순위 oracle 은 사용자의 원문 아이디어** — design-spec 은 오케스트레이터가 *직접 작성한* 산출물이라, 그것만 채점하면 spec 에 박힌 결함(예: "꽉 채운다" 면서 letterbox 처방)까지 "spec 과 일치"로 합격시키는 자기-인증 루프가 된다. 그래서:
- **`build-state.json` 의 `idea` (사용자 verbatim)** — 무엇을 만들어 달라 했는가. **최우선.**
- 스크린샷 PNG (`JUDGE_SHOT`) — 빌드된 앱의 실제 렌더
- `.autobot/design-spec.md` + `.autobot/design-spec.json` — 색/타이포/간격 토큰 (보조 의도)
- `.autobot/designs/*.png` — Stitch 목업 (있으면)

먼저 **사용자 원문을 원자적 절(clause)로 분해**하고(예: "윈앰프 UI 그대로" / "기존 .wsz 스킨 사용" / "탭없이" / "화면을 꽉 채우는"), 각 절을 스크린샷에서 **met / unmet** 으로 판정해 `summary` 와 `violations` 에 그대로 적는다. 명시적 사용자 절이 unmet 이면 그것은 design-spec 일치 여부와 무관하게 **HIGH severity violation** 이다 (사용자가 요구한 것을 안 했으므로).

판정 기준 — **빌드가 사용자 요구/디자인을 명백히 버렸는가**를 본다 (보수적: 확신 없으면 pass, 단 *명시적 사용자 절* 위반은 보수성 예외 — 확실하면 fail):

- `verdict="fail"` (HIGH severity) — 디자인은 뚜렷한 정체성(커스텀 팔레트/레이아웃)을 지정했는데 빌드는 **generic system default**(system blue + system gray)로 렌더 / design-spec 의 primary 토큰이 화면에 전혀 안 보임 / 설계된 P0 화면이 **blank·부재**. 반드시 **구체 증거** 인용: 관측 색 vs design 토큰 hex, 부재 화면명.
- `verdict="pass"` — 빌드가 디자인 토큰/레이아웃을 충실히 반영. 소프트 드리프트(미세 간격·계층·radius 차이)는 fail 아님 (medium/low 로 summary 에만 기록).

> **보수적 판정 원칙**: 이 게이트의 fail 은 *출하를 막는다* (아래 DEGRADED-only 참조). vision judge 는 비결정적·미보정(ground-truth ~10 빌드)이므로, **애매하면 pass**. fail 은 "디자인을 명백히 버렸다"는 증거가 있을 때만.

### 9c. verdict 기록 (최종 advance-phase 에 포함)

verdict 를 `.autobot/artifacts/visual-judge.json` 에 쓰고, 감사 이벤트를 남긴 뒤, **최종 advance-phase 의 `--metadata visualJudge` 로 전달**한다 (Step 7/8 의 axiom/peerReview 와 동일 패턴):

```bash
mkdir -p .autobot/artifacts
cat > .autobot/artifacts/visual-judge.json <<'JSON'
{"verdict":"pass","highCount":0,"summary":"primary coral #FF6B6B 적용 확인, 탭바·계층 의도대로","violations":[]}
JSON

bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event visual_judge_verdict \
  --detail "{\"verdict\":\"pass\",\"highCount\":0,\"summary\":\"...\"}"
```

> verdict JSON 스키마: `{"verdict":"pass"|"fail", "highCount":<int>, "summary":"<1줄>", "violations":[{"severity":"high|medium|low","axis":"디자인","title":"...","evidence":"...","fix":"..."}]}`.

### 9d. Gate 매핑 (DEGRADED-only — 빌드를 멈추지 않는다)

`check_visual_judge` 가 `phases.5.metadata.visualJudge` 를 읽어:

| verdict | 스크린샷 | `allowVisualDrift` | 결과 |
|---|---|---|---|
| `pass` | — | — | green |
| `fail` | — | false (기본) | **DEGRADED** (hard-fail 아님) → 배지 DEGRADED → 출하 차단 |
| 없음/garbled | 있음 | false | **DEGRADED** (anti-laundering — 검증 가능했는데 verdict 없음) |
| 없음/garbled | 없음 | false | benign-skip (green) — sim 부재로 검증 불가 |
| 임의 | — | true | green — `--allow-visual-drift` 가 visual gating 전체 면제 |

**왜 hard-fail 이 아닌가**: Gate 5→6 은 `soft=false` 라 hard-fail 시 Phase 5 가 `failed` + retryCount++ 되어 글로벌 circuit breaker 를 태우고 자율 빌드를 멈춘다. 비결정적 judge 의 false-positive 가 "질문 없이 끝까지"를 깨선 안 된다. 대신 DEGRADED 가 *출하*를 막는다 — `functionalVerification` 을 DEGRADED 로 떨어뜨려 `/autobot:testflight`·`/autobot:app-review` 가 거부한다 (anti-laundering). 운영자는 `/autobot:resume 5 --allow-visual-drift` 로 수용 가능.

### 9e. 결정적 화면-충실도 루프 (occupancy — visual_judge 와 달리 차단함)

visual_judge 는 비결정적이라 DEGRADED-only 다. 하지만 사용자가 화면을 **꽉 채우라**(full-screen / edge-to-edge / 그대로) 요구했는데 UI 가 화면의 일부만 차지하는 것은 **결정적으로 측정 가능한 결함**이라 차단해도 된다. 최종 advance-phase **전에** 직접 실행한다:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/visual_contract.py" --project-dir "$PWD" \
  --screenshot "$JUDGE_SHOT" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['status']); print(d.get('reason','')); print(d.get('occupancy'))"
```

- `status == "failed"` 이고 reason 이 **screen-fill requirement unmet** 이면: 이것은 컴파일 에러와 동급의 결함이다. **Step 3 (Build-Fix Loop) 로 라우팅**해 레이아웃을 고친다 — 고정 크기 윈도우를 화면 폭/높이에 맞춰 채우도록 스케일(floor 정수배 대신 fit-to-screen 분수 스케일), 그리고/또는 sub-window(플레이리스트/EQ)를 기본 스택해 세로를 채운다. 고친 뒤 **재빌드 → 재스크린샷(9a) → 재측정**. `policies.qualityRefineLoop.maxAttempts`(기본 2) 까지 반복.
- `maxAttempts` 소진 후에도 unmet 이면 그대로 advance 한다 — Gate 5→6 의 `visual_contract` 가 hard-fail 하여 Phase 5 가 `failed` 가 되고, 배지가 **UNVERIFIED** 로 정직하게 떨어진다(도구 부재 DEGRADED 로 위장되지 않음). 자율성은 maxAttempts cap 으로 유지된다.
- `status == "passed"` (또는 fill 요구가 없는 앱 → occupancy informational) 이면 그대로 진행.

> 이 루프가 "게이트로는 품질을 못 만든다"는 한계를 메운다: occupancy 게이트는 *이빨*이고, 이 루프가 **렌더 → 사용자 원문 기준 측정 → 안 되면 고치고 재렌더**의 *반복*을 강제한다. visual_judge(9b) 의 사용자-절 위반도 동일하게 Step 3 로 라우팅해 N 회 고친다.

## Gate 5→6 통과 조건

빌드 성공만으로는 부족하다. 다음 모두 충족해야 한다 (authored 테스트 컴파일+통과 포함 — Gate `logic_tests_pass`):

```bash
# 1. 빌드 성공
xcodebuild build ... 2>&1 | tail -1 | grep -q "BUILD SUCCEEDED"

# 1b. Authored 테스트 컴파일 + 통과 (Gate logic_tests_pass)
#     xcodebuild test 가 .xcresult 를 만들고, Gate 가 summary 를 파싱한다.
#     xcodebuild/sim 부재 시 degraded-skip (DEGRADED verdict, hard-block 아님).
xcodebuild test ... -resultBundlePath /tmp/Tests.xcresult 2>&1 | tail -1
xcrun xcresulttool get test-results summary --path /tmp/Tests.xcresult --compact \
  | grep -q '"result":"Passed"'

# 2. App 엔트리포인트에서 Stub 미사용 확인
! grep -qi "Stub" <AppName>/App/<AppName>App.swift
grep -qi "Repository\|Service(" <AppName>/App/<AppName>App.swift
grep -qi "ModelContainer" <AppName>/App/<AppName>App.swift

# 3. ServiceStubs.swift 존재 확인 (Preview용 보존)
test -f <AppName>/App/ServiceStubs.swift

# 4. Privacy manifest 완성 확인
test -f <AppName>/PrivacyInfo.xcprivacy

# 5. (조건부) Docker 검증 통과

# 6. Axiom critical audit — Axiom 미설치면 자동 통과, 설치돼 있으면 critical 0건
#    (Step 7 에서 기록한 phases.5.metadata.axiom_critical_audit 를 신뢰)

# 7. Opposite-runtime peer review — peer 미설치면 skipped 기록으로 통과
#    (Step 8 에서 기록한 phases.5.metadata.peerReview 를 Gate 가 검사)
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
