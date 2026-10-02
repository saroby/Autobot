## Step 5: Authored 테스트 작성 (컴파일 + 통과 필수)

`<AppName>Tests/` 디렉토리에 Swift Testing 테스트를 작성한다. 이 테스트는 **반드시 컴파일되고 통과해야 한다** — Gate 5→6 의 `logic_tests_pass` 체크가 `xcodebuild test` 를 실행해 `.xcresult` 를 파싱하므로, 빌드만 성공하고 테스트가 깨지면 Gate 5→6 는 hard-fail 한다.

### 5a. P0 logic acceptance 당 1개 테스트 (이름 규칙 필수)

`.autobot/feature-spec.json` 의 각 P0 feature 에서 `kind == "logic"` 인 acceptance 마다, **acceptance id 와 동일한 이름의 `@Test func`** 를 작성한다. `check_logic_tests_pass` 의 completeness 서브체크가 authored 테스트 이름을 acceptance id 와 대조한다 (`addItem_increasesCount` ↔ `func addItem_increasesCount()`). 이름이 없거나 일치하지 않으면 DEGRADED로 기록되어 출하가 차단되므로 handoff 전에 누락된 named test를 추가한다.

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
