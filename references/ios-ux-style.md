# iOS UX Style Guide

> **이 파일은 Autobot의 모든 에이전트가 공유하는 단일 디자인 소스입니다.**
> iOS 새 버전이 나오면 이 파일만 업데이트하세요. 에이전트 프롬프트는 수정 불필요.

## Target

- **Deployment Target**: iOS 26.0
- **Swift Version**: 6.0
- **Xcode Version**: 26.0
- **Design Language**: Liquid Glass

## Design System

### Liquid Glass (iOS 26+)

```swift
// 배경 표면에 글래스 효과
.glassEffect()

// 버튼 — glass / glassProminent (`.liquidGlass` 라는 멤버는 존재하지 않는다)
Button("Action") { }
    .buttonStyle(.glass)

// primary action 강조 버튼
Button("Save") { }
    .buttonStyle(.glassProminent)

// 툴바
.toolbar {
    ToolbarItem(placement: .automatic) { ... }
}
```

### Colors & Materials

- **architect가 `## Design Direction`에서 정의한 커스텀 팔레트가 있으면 `Theme.*` 토큰을 사용** (Theme.primary, Theme.surface 등)
- Theme이 없는 fallback에서만 시스템 semantic colors 사용: `.primary`, `.secondary`, `.accent`
- 하드코딩 컬러(hex literal) 금지 — Asset Catalog 기반 `Color("name")` 사용
- Dark Mode 자동 지원 (Asset Catalog Light/Dark 변형)

### Typography

- Dynamic Type 필수 지원
- 하드코딩 폰트 사이즈 금지
- **Theme이 있으면 `Theme.display()`, `Theme.headline()`, `Theme.body()` 사용** — font design(.rounded/.default/.serif)이 앱 성격에 맞게 설정됨

## SwiftUI Patterns

### State Management

```swift
// ViewModel — @Observable (NOT ObservableObject)
@Observable @MainActor
final class ScreenViewModel { ... }

// View에서 소유 — @State (NOT @StateObject)
@State private var viewModel: ScreenViewModel
```

### Navigation

```swift
// NavigationStack + value-based destination
NavigationStack {
    List(items) { item in
        NavigationLink(value: item) { ... }
    }
    .navigationDestination(for: Item.self) { item in
        DetailView(item: item)
    }
}
```

### Search

검색을 구현할 땐 **커스텀 검색 UI 를 만들기 전에 SwiftUI 네이티브 [`.searchable(text:placement:prompt:)`](https://developer.apple.com/documentation/swiftui/view/searchable(text:placement:prompt:)) 를 먼저 고려한다.** 시스템 검색 바 배치·키보드·접근성·취소 동작을 공짜로 얻는다. TextField + 필터 리스트를 손으로 조립하는 건 네이티브가 부족할 때만.

```swift
NavigationStack {
    List(results) { item in ... }
        .searchable(text: $query, prompt: "검색")
}
```

### 화면 액션 버튼 배치

화면 단위 액션(추가·편집·완료·공유·필터·설정 등)은 **하단에 긴(풀-폭) 버튼을 새로 만들기보다 네비게이션 바 `.toolbar` 버튼을 우선한다.** 시스템이 배치·터치 타깃·Dynamic Type·접근성을 처리하고, 버튼이 콘텐츠 영역을 잠식하지 않는다.

```swift
.toolbar {
    ToolbarItem(placement: .primaryAction) {
        Button("추가", systemImage: "plus") { ... }
    }
}
```

- placement 관례: `.primaryAction`(우상단) = 주요 추가/생성, `.topBarLeading` = 편집/닫기, sheet 는 `.confirmationAction` / `.cancellationAction`.
- 하단 고정 버튼은 **단일 커밋형 플로우의 최종 확정**(결제 "결제하기", 온보딩 "시작하기", 폼 "저장")에만 쓴다 — 이때도 위 Tab Bar rule 2 대로 `.safeAreaInset(edge: .bottom)` 으로 부착한다.
- "액션이 하나뿐" 이라는 이유로 하단 풀-폭 버튼을 기본값으로 두지 않는다. 기본은 툴바다.

### Tab View

```swift
// Modern Tab syntax
TabView {
    Tab("Home", systemImage: "house") {
        HomeView()
    }
    Tab("Settings", systemImage: "gear") {
        SettingsView()
    }
}
```

#### Tab Bar 와 콘텐츠 겹침 방지 (필수)

iOS 26 의 Liquid Glass `TabView` 는 시스템이 자동으로 자식 뷰에 bottom safe-area inset 을 더해 준다. **이 inset 을 무시하거나 덮어쓰면 콘텐츠(스크롤 마지막 항목, floating button, 커스텀 bottom bar)가 탭바에 가려진다.** 다음 규칙을 반드시 지킨다.

1. **탭 자식 뷰의 루트에 `.ignoresSafeArea(.container, edges: .bottom)` 또는 `.ignoresSafeArea(.all, edges: .bottom)` 금지.**
   - 배경 컬러/그라디언트에 한해서만 허용:
     ```swift
     ZStack {
         Theme.background.ignoresSafeArea() // 배경만, 콘텐츠는 별개
         contentView                          // 콘텐츠는 safe area 안쪽
     }
     ```
2. **Floating button, custom bottom bar, sticky CTA 는 `.safeAreaInset(edge: .bottom)` 으로 부착한다.** `overlay(alignment: .bottom)` + 고정 offset 금지.
   ```swift
   List(items) { ... }
       .safeAreaInset(edge: .bottom) {
           PrimaryButton("저장") { save() }
               .padding(.horizontal)
               .padding(.bottom, 8)
       }
   ```
3. **`ScrollView` 마지막 항목이 탭바와 겹치지 않는다는 가정 금지** — SwiftUI 가 자동으로 inset 을 더하지만, 커스텀 `LazyVStack` 안에 `.padding(.bottom, 고정값)` 만 주고 inset 을 제거하면 깨진다. `.contentMargins(.bottom, ...)` 또는 위의 `.safeAreaInset` 을 사용한다.
4. **고정 픽셀로 탭바 높이를 가정해 padding 을 주는 코드 금지** (`.padding(.bottom, 49)`, `.padding(.bottom, 83)` 등). iOS 26 Liquid Glass 탭바 높이는 디바이스/방향/dynamic type 에 따라 달라진다. 항상 safe area API 로 위임한다.
5. **Sheet/FullScreenCover 내부 탭바**: sheet 안에 별도 `TabView` 를 두는 경우, 부모의 inset 이 전달되지 않는다. sheet 루트에 `.toolbarBackground(.visible, for: .tabBar)` 와 자체 `.safeAreaInset(edge: .bottom)` 을 함께 사용한다.
6. **Hide tab bar in nested NavigationStack**: `.toolbar(.hidden, for: .tabBar)` 를 푸시된 화면에 적용했다면, 그 화면의 bottom 콘텐츠는 `.safeAreaInset` 대신 `.padding(.bottom)` 로 충분 — 단 푸시-팝 사이에 일관된 처리가 필요하다.

**셀프 체크리스트** (ui-builder 가 탭 화면을 만들 때마다 확인):
- [ ] 자식 뷰에 `.ignoresSafeArea(.*, edges: .bottom)` 이 있는가? → 배경 외에는 제거
- [ ] Floating/sticky 요소가 `.safeAreaInset(edge: .bottom)` 으로 부착됐는가?
- [ ] 하드코딩된 `.padding(.bottom, <number>)` 가 탭바 높이를 보정하려는 의도인가? → 제거하고 safe area 사용
- [ ] 스크롤 마지막 항목이 미리보기에서 탭바에 가리지 않는가?

### Data Persistence

```swift
// SwiftData — @Model
@Model final class Item { ... }

// Query
@Query var items: [Item]

// Container registration
.modelContainer(for: [Item.self, Tag.self])

// FetchDescriptor for services
let descriptor = FetchDescriptor<Item>(
    predicate: #Predicate { $0.isCompleted },
    sortBy: [SortDescriptor(\.createdAt, order: .reverse)]
)
```

### Concurrency

```swift
// Swift 6 strict concurrency
@MainActor protocol ServiceProtocol { ... }
// async/await for networking
func fetch() async throws -> [Item]
```

### Keyboard Dismissal

TextField/TextEditor 외부 탭 시 키보드를 자동으로 닫는다. **모든 앱의 루트 뷰에 적용 필수.**

⚠️ **`.onTapGesture` 사용 금지** — 루트 뷰에 적용하면 Button, NavigationLink, List row 등 자식 뷰의 탭을 가로채서 앱 전체가 먹통이 된다. 반드시 `.simultaneousGesture`를 사용한다.

```swift
// App 엔트리포인트에서 전역 적용
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .dismissKeyboardOnTap()
        }
    }
}

// ViewModifier — Utilities/ 또는 App/ 에 한 번만 정의
extension View {
    func dismissKeyboardOnTap() -> some View {
        self.simultaneousGesture(
            TapGesture().onEnded {
                UIApplication.shared.sendAction(
                    #selector(UIResponder.resignFirstResponder),
                    to: nil, from: nil, for: nil
                )
            }
        )
    }
}
```

`.simultaneousGesture`는 자식 뷰의 제스처와 **동시에** 발동하므로, 키보드는 닫히면서도 Button/NavigationLink 등이 정상 동작한다.

ScrollView 내부에서는 추가로:
```swift
.scrollDismissesKeyboard(.interactively)
```

## Accessibility

- 모든 인터랙티브 요소에 `.accessibilityLabel()` 필수
- 상대적 크기 사용 (하드코딩 사이즈 금지)
- Semantic colors로 충분한 대비 보장

## SF Symbols

- SF Symbols 6+ 사용
- 아이콘은 시스템 심볼 우선

## Anti-Patterns (금지 사항)

| 금지 | 대신 사용 |
|------|----------|
| `ObservableObject` | `@Observable` |
| `@StateObject` | `@State` |
| `@Published` | `@Observable` 내 일반 프로퍼티 |
| `NavigationView` | `NavigationStack` |
| `UIKit` wrapping (불필요 시) | Native SwiftUI |
| 하드코딩 컬러/사이즈 | Semantic colors, Dynamic Type |
| `List { ForEach { NavigationLink(destination:)` | `NavigationLink(value:)` + `.navigationDestination` |
| `.onTapGesture` on root (키보드 닫기용) | `.simultaneousGesture(TapGesture())` |
| 화면 액션에 하단 풀-폭 버튼 (추가·편집·필터 등) | 네비게이션 바 `.toolbar` 버튼 (`.primaryAction` 등) — 하단 고정은 단일 커밋형 확정에만 |
