# Build & Testing — Xcode 26+ Distilled

> **출처**: axiom-build + axiom-testing (MIT, WWDC 2025+) 의 핵심 규칙을 Autobot 자족 형태로 증류. 외부 axiom 없어도 동일하게 작동.
>
> **사용자**: `quality-engineer` 에이전트(필수). Phase 5 빌드 검증·테스트 작성·실패 진단 시 이 규칙을 따른다.

---

## 0. 절대 규칙

1. **환경 먼저, 코드 나중.** 같은 코드가 어제는 됐고 오늘 안 된다? 9할은 환경 (DerivedData, simulator state, SPM 캐시, 좀비 프로세스).
2. **빌드 실패 메시지는 *마지막* 에러부터 읽지 말 것.** Swift 컴파일러는 첫 에러가 진짜 원인이고 나머지는 파생. `xcodebuild` 출력은 *처음*부터.
3. **새 테스트는 Swift Testing (`@Test`, `#expect`). XCTest 신규 작성 금지** (iOS 18+ 표준).
4. **`sleep()` / `Thread.sleep` 으로 비동기 대기 금지.** `confirmation`, `await expectation.fulfilled`, `XCUIElement.waitForExistence` 사용.
5. **테스트 사이 공유 가변 상태 금지.** `@Test(arguments:)` 또는 fixture, mock 주입.

---

## 1. 빌드 실패 분류 — 첫 30초 진단

`xcodebuild` 가 실패하면 *원인을 코드에서 찾기 전에* 다음 순서로 환경을 확인.

### 환경 체크리스트 (병렬 가능)

```bash
# 1. 좀비 xcodebuild 프로세스
pgrep -af xcodebuild | head -10
# 5개 이상 → killall xcodebuild

# 2. DerivedData 크기
du -sh ~/Library/Developer/Xcode/DerivedData
# 10GB+ → 프로젝트별 정리 또는 전체 삭제 (마지막 수단)

# 3. 시뮬레이터 상태
xcrun simctl list devices booted
# 부팅된 게 너무 많으면 → xcrun simctl shutdown all

# 4. SPM 캐시
ls ~/Library/Caches/org.swift.swiftpm/ 2>/dev/null
ls ~/Library/Developer/Xcode/DerivedData/<Project>/SourcePackages

# 5. CoreSimulator 데몬
launchctl list | grep CoreSimulator
```

### 에러 메시지 → 도메인 매핑

| 메시지 패턴 | 도메인 | 조치 |
|---|---|---|
| `No such module 'X'` | SPM/패키지 | DerivedData 의 SourcePackages 삭제 + Reset Package Caches |
| `duplicate symbol _OBJC_CLASS_$_X` | 링커 | 같은 의존성 두 번 링크. Package.resolved + target dependencies 점검 |
| `... has different visibility ...` | Swift 6 concurrency | data-concurrency.md 참조 |
| `Cannot find type 'X' in scope` | 모듈/import | import 누락, 또는 target membership |
| `Sandbox: bash deny` | 빌드 스크립트 권한 | ENABLE_USER_SCRIPT_SANDBOXING=NO 또는 스크립트 권한 조정 |
| `Could not find or use auto-linked framework` | 시뮬레이터 SDK | Clean Build Folder + 시뮬레이터 재선택 |
| `unable to attach DB: ... database is locked` | DerivedData 잠금 | 좀비 xcodebuild kill |
| `<unknown>:0: error: unknown argument: '-XXX'` | 잘못된 빌드 설정 | OTHER_SWIFT_FLAGS 점검 |
| `Code Signing 'X' failed` | 서명/프로비저닝 | Team ID, Bundle ID, automatic signing 점검 |
| `SwiftCompile failed with a nonzero exit code` (출력 없음) | 컴파일러 크래시 | `-Xfrontend -debug-time-function-bodies` 로 느린 표현식 찾기 |

### 가장 흔한 한 줄 해결

```bash
# DerivedData 프로젝트별 삭제 (전체 삭제는 마지막 수단)
rm -rf ~/Library/Developer/Xcode/DerivedData/${PROJECT}-*

# 시뮬레이터 리셋
xcrun simctl shutdown all && xcrun simctl erase all

# SPM 캐시
swift package purge-cache  # 프로젝트 루트에서
```

---

## 2. Swift Testing — iOS 18+ 표준

### 기본 골격

```swift
import Testing
@testable import MyApp

@Suite("ItemRepository")
struct ItemRepositoryTests {

    @Test("새 아이템 추가 후 fetch 하면 결과에 포함된다")
    func addAndFetch() async throws {
        let repo = makeInMemoryRepo()
        try repo.add("hello")
        let items = try repo.all()
        #expect(items.contains { $0.title == "hello" })
    }

    @Test("같은 ID 두 번 추가 시 unique 위반", arguments: [
        UUID(), UUID(), UUID()
    ])
    func duplicateID(id: UUID) async throws {
        // parameterized — arguments 마다 한 번씩 실행
    }
}
```

### XCTest 와의 차이 — 새로 익혀야 할 것

| XCTest | Swift Testing |
|---|---|
| `XCTAssertEqual(a, b)` | `#expect(a == b)` |
| `XCTAssertTrue(x)` | `#expect(x)` |
| `XCTFail("msg")` | `Issue.record("msg")` |
| `setUp() / tearDown()` | `init()` / `deinit` (struct) |
| `XCTSkip(...)` | `withKnownIssue { ... }` 또는 `@Test(.disabled(...))` |
| 글로벌 비동기 expectation | `confirmation(...) { confirm in ... confirm() }` |

### 비동기 대기 — sleep 금지 패턴

```swift
// ❌ XCTest 시절 잔존
try await Task.sleep(for: .seconds(1))
#expect(model.didFire)

// ✅ confirmation
await confirmation("model fires") { confirm in
    model.onFire = { confirm() }
    model.trigger()
}
```

### Suite-level 격리

```swift
@Suite(.serialized)            // 안에 든 테스트들이 순차 실행 (공유 리소스)
struct DatabaseTests { … }

@Suite(.tags(.flaky))          // 태깅으로 그룹 실행
struct NetworkTests { … }
```

기본은 *병렬 실행*. 공유 자원이 있으면 `.serialized` 명시.

---

## 3. UI Testing — XCUITest

### Recording UI Automation (Xcode 26+)

Xcode 26 의 신규 *Recording UI Automation* 기능:
1. UI Test 타깃에서 `Record` 버튼.
2. 시뮬레이터에서 사용자 흐름 수행.
3. Xcode 가 코드 생성 — `XCUIElement` 호출이 조건 기반 대기 포함.
4. `Replay` 로 검증, `Review` 로 코드 정리.

수동 작성보다 *조건 기반 대기*가 자동 삽입되어 flaky 가 급감.

### 절대 패턴

```swift
// ❌ sleep
sleep(2)
let cell = app.cells.firstMatch
cell.tap()

// ✅ waitForExistence
let cell = app.cells.firstMatch
#expect(cell.waitForExistence(timeout: 5))
cell.tap()
```

```swift
// ❌ 좌표 탭
app.tap(at: CGPoint(x: 100, y: 200))

// ✅ accessibility identifier
app.buttons["save_button"].tap()
```

모든 인터랙티브 요소에 `.accessibilityIdentifier("…")` 부착. ui-builder 가 이미 부착했어야 함.

---

## 4. 실패한 테스트 진단 4단계

1. **재현 가능한가?** `xcodebuild test -only-testing:Module/SuiteName/testName -resultBundlePath out.xcresult` 로 1회 더 실행.
2. **격리 문제?** 단독으로 통과하지만 묶음 실행 시 실패 → 공유 상태. `.serialized` 또는 fixture 격리.
3. **타이밍 문제?** sleep 사용 또는 confirmation 없이 비동기? → confirmation 패턴으로 재작성.
4. **환경 문제?** 시뮬레이터 부팅 누락, 권한 다이얼로그? → `xcrun simctl privacy ... grant ...` 사전 처리.

`.xcresult` 번들은 `xcrun xcresulttool get --format json --path out.xcresult` 로 구조화 추출.

---

## 5. Anti-Rationalization 표

| 생각 | 현실 |
|---|---|
| "DerivedData 지우면 일단 빌드 됨" | 매번 지우면 캐시 의미 없음. 진짜 원인(좀비 프로세스, 동시 빌드, 패키지 충돌)을 찾을 것. |
| "재현 안 되는 빌드 실패는 그냥 retry" | 환경 noise 가 누적된다. 첫 발견 시 환경 체크 5분 해서 패턴 식별. |
| "테스트 하나가 가끔 깨지지만 다른 건 다 통과" | flaky 테스트는 *전염성*. 한 개를 방치하면 곧 모두 신뢰 못 함. 격리/대기 패턴 재작성. |
| "Swift Testing 은 새거라 익숙해지면 옮길게" | 새 코드는 Swift Testing 으로. 혼재가 가능하니 마이그레이션 미루지 말 것. |
| "sleep(1) 한 번이면 충분" | CI 의 부하 따라 1초가 짧을 수도 길 수도. confirmation 으로 명시. |
| "UI 테스트는 너무 flaky 라 안 쓴다" | Recording UI Automation + accessibility identifier 조합이면 95%+ 안정. 안 쓸 사유 없음. |
| "에러 메시지가 너무 많아서 마지막 거 본다" | Swift 컴파일러는 *첫* 에러가 진짜 원인. 마지막은 파생. |

---

## 6. quality-engineer Self-Check (Phase 5 완료 직전)

- [ ] `xcodebuild build` 성공 (warning 0 또는 known issue 표시)
- [ ] 단위 테스트 1개 이상, 모두 통과
- [ ] 모든 신규 테스트가 Swift Testing (`@Test`, `#expect`)
- [ ] `sleep(` / `Thread.sleep` 0건 (`grep -rn "sleep(" Tests/`)
- [ ] `XCTAssert` 신규 0건 (기존 코드 마이그레이션은 별도 추적)
- [ ] 모든 인터랙티브 UI 요소에 `accessibilityIdentifier`
- [ ] `try?` / `try!` 가 비-테스트 코드 0건 (data-concurrency.md 와 중복 체크)
- [ ] `.xcresult` 번들 보관 (회고용)
- [ ] Phase 5 evidence 에 빌드 시간 + 테스트 시간 기록

체크 1개라도 빠지면 Gate 5→6 통과 불가.

---

## 7. 자주 쓰는 명령 (Autobot 표준)

```bash
# 빌드 (Autobot 표준 — derived data 격리)
xcodebuild build \
  -project "${APP_NAME}.xcodeproj" \
  -scheme "${APP_NAME}" \
  -destination 'platform=iOS Simulator,name=iPhone 16,OS=latest' \
  -derivedDataPath .build/DerivedData \
  -quiet

# 테스트 (xcresult 보관)
xcodebuild test \
  -project "${APP_NAME}.xcodeproj" \
  -scheme "${APP_NAME}" \
  -destination 'platform=iOS Simulator,name=iPhone 16,OS=latest' \
  -derivedDataPath .build/DerivedData \
  -resultBundlePath .autobot/last-test.xcresult

# 결과 추출
xcrun xcresulttool get --format json --path .autobot/last-test.xcresult > .autobot/last-test.json
```

destination 은 *항상* 명시. "first available" 으로 가지 말 것 (재현성 손실).
