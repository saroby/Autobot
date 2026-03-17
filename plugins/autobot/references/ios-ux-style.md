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

// 버튼
Button("Action") { }
    .buttonStyle(.liquidGlass)

// 툴바
.toolbar {
    ToolbarItem(placement: .automatic) { ... }
}
```

### Colors & Materials

- Semantic colors 사용: `.primary`, `.secondary`, `.accent`
- 하드코딩 컬러 금지
- Dark Mode 자동 지원

### Typography

- Dynamic Type 필수 지원
- 하드코딩 폰트 사이즈 금지

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
