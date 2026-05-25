# SwiftUI — iOS 26+ Distilled

> **출처**: axiom-swiftui (MIT, WWDC 2025+) 의 핵심 규칙을 Autobot 자족 형태로 증류. 외부 axiom 없어도 동일하게 작동.
>
> **사용자**: `ui-builder` 에이전트(필수). 모든 View / ViewModel 생성 코드는 이 규칙을 만족해야 한다.

---

## 0. 절대 규칙 (위반 시 Gate 4→5 자동 실패)

1. **`@State var foo`는 금지. 항상 `@State private var foo`.** 누락 시 자식 뷰가 별도 진리원본을 만들어 *조용한* 상태 버그 발생.
2. **`ObservableObject` / `@StateObject` / `@ObservedObject` 신규 사용 금지.** iOS 17+ 부터 `@Observable` 클래스 + `@State`/`@Bindable`/`@Environment` 가 표준.
3. **NavigationStack/NavigationSplitView 만 사용. `NavigationView` 신규 사용 금지** (iOS 16+ deprecated).
4. **View body 안에서 비동기 호출, 무거운 계산, 상태 변이 금지.** body 는 순수 함수. 비동기는 `.task {}`, 변이는 액션 핸들러에서.
5. **`Color`/`Font` 리터럴 하드코딩 금지.** semantic 토큰 또는 Asset Catalog. (design.md 참조)

---

## 1. State Ownership — 4가지 도구의 결정 트리

```
이 데이터의 진리원본(source of truth)은 누구인가?
│
├─ 이 View 자신
│   └─ 값 타입(struct, enum, primitive) → @State private var
│       참조 타입(@Observable 클래스)  → @State private var
│
├─ 부모 View (이미 @State 보유)
│   └─ 단방향 읽기만   → 일반 let 프로퍼티로 전달
│       양방향 바인딩  → @Binding (값 타입) / @Bindable (참조 타입)
│
├─ 앱 전역
│   └─ @Environment(SomeObservable.self) — root 에서 .environment()
│
└─ 시스템
    └─ @Environment(\.colorScheme), \.dismiss, \.scenePhase 등 키패스
```

### @Observable 클래스 패턴 (iOS 17+ 표준)

```swift
@Observable
final class FeedModel {
    var items: [Item] = []
    var isLoading = false

    func load() async {
        isLoading = true
        defer { isLoading = false }
        items = try await api.fetch()
    }
}

struct FeedView: View {
    @State private var model = FeedModel()        // 소유

    var body: some View {
        List(model.items) { ItemRow(item: $0) }
            .task { await model.load() }            // 비동기는 .task
    }
}

struct ItemEditView: View {
    @Bindable var model: FeedModel                  // 자식이 양방향 바인딩 필요할 때
}
```

**금지 패턴**:
- `@StateObject var model = FeedModel()` — 옛 방식.
- `@State var model` (private 누락).
- `ObservableObject` 채택 + `@Published`.

---

## 2. Navigation — NavigationStack 라우터 패턴

### 단일 스택

```swift
@Observable
final class Router {
    var path = NavigationPath()
    func push<V: Hashable>(_ value: V) { path.append(value) }
    func pop() { path.removeLast() }
    func popToRoot() { path = NavigationPath() }
}

struct RootView: View {
    @State private var router = Router()

    var body: some View {
        NavigationStack(path: $router.path) {
            HomeView()
                .navigationDestination(for: Item.self) { ItemDetailView(item: $0) }
                .navigationDestination(for: Profile.self) { ProfileView(profile: $0) }
        }
        .environment(router)
    }
}
```

### 규칙

- 한 `NavigationStack` = 한 `path`. 분할 화면이면 `NavigationSplitView` (iPad/macOS 자동 적응).
- 모든 destination 은 `.navigationDestination(for:)` 으로 등록. 인라인 `NavigationLink(destination:)` 사용 금지 (deep linking 깨짐).
- deep link / state restoration 이 필요한 앱이면 `path: NavigationPath` 가 *Codable* 한 값만 담아야 함 (`@Observable` 클래스 직접 push 금지).
- 라우터는 단 1곳 (`@Environment`). 뷰 내부에서 별도 path 들고 다니지 말 것.

### 흔한 실수

- **Two-level NavigationStack 중첩**: 어느 path 에 push 됐는지 헷갈리는 버그. 한 화면 = 한 stack.
- **`@State` 로 path 보관**: 라우터 재사용 불가. `@Observable` 클래스에 넣고 `@Environment` 로 전달.

---

## 3. Performance — 즉시 점검 7가지

| 증상 | 점검 | 해결 |
|---|---|---|
| List/ForEach 스크롤 jank | `ForEach(items)` 가 `id:` 없이? | `ForEach(items, id: \.id)` 또는 `Identifiable` |
| body 가 자주 호출됨 | `let _ = print("body")` 로 카운트 | 부모 상태 분리, 자식 뷰 작게 |
| 큰 List 느림 | `List` 사용? | iOS 18+: 큰 데이터셋은 `LazyVStack + ScrollView` 검토 |
| 이미지 로딩 느림 | `AsyncImage(url:)` 단독 | placeholder + transaction + 캐시 레이어 |
| 애니메이션 stutter | `.animation(.default)` 무조건 부착 | value-bound: `.animation(.default, value: model.x)` |
| Preview 크래시 | 비동기 init 또는 무한 데이터 | `#Preview { … }` 안에서 mock 주입 |
| Sheet 열 때 lag | `.sheet(item:)` content 가 무거움 | Sheet 뷰 자체를 lazy 로 — `if isPresented` 안에서 만들기 |

### 절대 패턴

```swift
// ❌ body 안에서 계산
var body: some View {
    let filtered = items.filter { $0.isActive }
    List(filtered) { … }
}

// ✅ @Observable 모델에 캐시
@Observable
final class ListModel {
    var items: [Item] = []
    var filtered: [Item] { items.filter(\.isActive) }
}
```

```swift
// ❌ View 안에서 비동기 .task 없이
var body: some View {
    Text(loadedText)
    // loadedText 는 어디서 채우지?
}

// ✅ .task 로
var body: some View {
    Text(model.text)
        .task { await model.load() }
}
```

---

## 4. iOS 26 SwiftUI 신기능

- **`.tabRole(.search)`**: 검색 탭 표준 마킹.
- **`Tab(value:role:)`**: TabView 새 API (iOS 26).
- **`.glassEffect()`**: design.md 참조.
- **`@Animatable` macro**: 커스텀 애니메이션 타입 자동 derivation.
- **새 ScrollView API**: `.scrollPosition(id:)`, `.scrollTargetBehavior(.viewAligned)`.
- **List 커스텀 컨테이너**: iOS 18+ `.containerRelativeFrame`, 자체 컨테이너 정의 가능.

---

## 5. Anti-Rationalization 표

| 생각 | 현실 |
|---|---|
| "그냥 @State var 로 빠르게 가자" | private 누락 → 자식이 별도 source of truth 생성 → 조용한 버그 |
| "ObservableObject 도 작동하잖아" | iOS 17+ 에서는 @Observable 이 *더 적은 업데이트* 발생. 성능 차이 명백. |
| "NavigationView 도 deprecated 일 뿐 동작은 함" | iPad 분할 동작이 다르고, iOS 26 검색 표면 통합 안 됨. |
| "body 안에서 한 줄 계산은 괜찮겠지" | body 는 매 업데이트마다 호출. O(n) → O(n²) 쉽게 됨. |
| "Preview 는 그냥 데이터 하드코딩" | mock 의존성 주입 패턴 안 만들면 ViewModel 테스트도 못 함. |
| ".animation(.default) 부착하면 다 됨" | value-bound 가 아니면 *모든 상태 변화*에 애니메이션. 의도 안 한 깜빡임. |
| "List 가 느려서 LazyVStack 으로 바꿀게" | 먼저 `id:` 누락·body 무거움 확인. 80% 케이스는 그것. |

---

## 6. ui-builder Self-Check (Phase 4 완료 직전)

- [ ] `@State var` (private 누락) 0건 — `grep -nE '@State var ' Views/`
- [ ] `ObservableObject` / `@StateObject` 0건 — `grep -nE 'ObservableObject|@StateObject' Views/`
- [ ] `NavigationView(` 0건 — `grep -nE 'NavigationView\(' Views/`
- [ ] 모든 비동기 호출은 `.task` 또는 액션 핸들러 안
- [ ] body 안에 `for`, `while`, 무거운 `filter`/`map` chain 0건
- [ ] 모든 `ForEach` 가 `id:` 또는 `Identifiable`
- [ ] sheet/fullScreenCover 에 dismiss 경로 명시
- [ ] semantic color / Dynamic Type 만 사용 (design.md 참조)

체크 1개라도 빠지면 Phase 4 완료 보고 금지.
