# Integration Wiring Patterns

App 엔트리포인트에서 Stub을 실제 Repository로 교체하는 패턴.
아키텍처 복잡도에 따라 3가지 패턴을 제공한다.

## Pattern 1: Simple (로컬 전용, 서비스 1~2개)

가장 흔한 패턴. SwiftData만 사용하고 백엔드가 없는 앱.

### Before (ui-builder 생성 — Stub 사용)

```swift
import SwiftUI
import SwiftData

@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: [Item.self, Tag.self])
    }
}
```

이 상태에서는 ViewModel이 Stub을 사용하거나, ModelContext를 Environment에서 받아 직접 사용한다.

### After (quality-engineer 교체 — 실제 Repository)

```swift
import SwiftUI
import SwiftData

@main
struct MyApp: App {
    let container: ModelContainer

    init() {
        do {
            container = try ModelContainer(for: Item.self, Tag.self)
        } catch {
            fatalError("ModelContainer init failed: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView(
                itemService: ItemRepository(modelContext: container.mainContext),
                tagService: TagRepository(modelContext: container.mainContext)
            )
        }
        .modelContainer(container)
    }
}
```

### 왜 ModelContainer를 직접 생성하는가?

`.modelContainer(for:)` modifier는 SwiftUI Environment에 주입하지만, App 구조체의 `body` 안에서는 `@Environment(\.modelContext)`에 접근할 수 없다. Repository의 init에 `modelContext`를 전달하려면 `ModelContainer`를 stored property로 가지고, `container.mainContext`를 사용해야 한다.

## Pattern 2: Multi-Service (로컬 전용, 서비스 3개 이상)

서비스가 많아지면 ContentView의 init 파라미터가 과도해진다. 이때는 서비스를 묶는 Container를 만든다.

### After

```swift
import SwiftUI
import SwiftData

@main
struct MyApp: App {
    let container: ModelContainer
    let services: ServiceContainer

    init() {
        do {
            container = try ModelContainer(for: Item.self, Tag.self, Category.self)
        } catch {
            fatalError("ModelContainer init failed: \(error)")
        }
        let context = container.mainContext
        services = ServiceContainer(
            itemService: ItemRepository(modelContext: context),
            tagService: TagRepository(modelContext: context),
            categoryService: CategoryRepository(modelContext: context)
        )
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(services)
        }
        .modelContainer(container)
    }
}
```

ServiceContainer:
```swift
// 이 파일은 quality-engineer가 생성한다 (App/ 디렉토리에)
import SwiftUI

@Observable @MainActor
final class ServiceContainer {
    let itemService: any ItemServiceProtocol
    let tagService: any TagServiceProtocol
    let categoryService: any CategoryServiceProtocol

    init(
        itemService: any ItemServiceProtocol,
        tagService: any TagServiceProtocol,
        categoryService: any CategoryServiceProtocol
    ) {
        self.itemService = itemService
        self.tagService = tagService
        self.categoryService = categoryService
    }
}
```

> **주의**: ServiceContainer 패턴을 사용할 때, View/ViewModel이 이미 개별 서비스를 init 파라미터로 받도록 생성되었다면, ContentView에서 environment의 ServiceContainer를 꺼내 각 ViewModel에 전달하는 연결 코드가 필요하다.

## Pattern 3: Backend (백엔드 필수 앱)

OAuth + LLM 프록시가 있는 앱. APIClient와 AuthService가 추가된다.

### After

```swift
import SwiftUI
import SwiftData

@main
struct MyApp: App {
    let container: ModelContainer
    let apiClient: APIClient

    init() {
        do {
            container = try ModelContainer(for: User.self, ChatMessage.self)
        } catch {
            fatalError("ModelContainer init failed: \(error)")
        }

        guard let baseURL = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
              let url = URL(string: baseURL) else {
            fatalError("API_BASE_URL not configured in Info.plist")
        }
        apiClient = APIClient(baseURL: url)
    }

    var body: some Scene {
        WindowGroup {
            ContentView(
                authService: AuthRepository(apiClient: apiClient),
                chatService: ChatRepository(
                    apiClient: apiClient,
                    modelContext: container.mainContext
                )
            )
        }
        .modelContainer(container)
    }
}
```

### Backend Wiring 체크리스트

1. `API_BASE_URL`을 `Bundle.main`에서 읽는지 확인
2. `Debug.xcconfig` → `http://localhost:8080`, `Release.xcconfig` → `https://$(PRODUCTION_HOST)` 확인
3. AuthRepository가 JWT 토큰을 저장/주입하는 로직이 있는지 확인
4. SSE 스트리밍 엔드포인트가 `URLSession` bytes iteration을 사용하는지 확인

## Wiring 검증

교체 후 다음을 확인한다:

```bash
# 1. Stub 참조가 App 엔트리포인트에 없는지
! grep -qi "Stub" <AppName>/App/<AppName>App.swift

# 2. 실제 Repository/Service가 사용되는지
grep -qi "Repository\|Service(" <AppName>/App/<AppName>App.swift

# 3. ModelContainer가 직접 생성되는지
grep -qi "ModelContainer" <AppName>/App/<AppName>App.swift

# 4. ServiceStubs.swift가 여전히 존재하는지 (삭제하면 Preview 에러)
test -f <AppName>/App/ServiceStubs.swift
```

## 흔한 Wiring 실수

| 실수 | 증상 | 수정 |
|------|------|------|
| ServiceStubs.swift 삭제 | 모든 #Preview 컴파일 에러 | 파일 복원. Stubs는 Preview 전용으로 유지 |
| Repository init에 잘못된 타입 전달 | "Cannot convert value" 에러 | `grep 'init(' Services/*Repository.swift`로 실제 시그니처 확인 |
| .modelContainer(for:)에 모든 @Model 미등록 | 런타임 크래시 (빌드는 성공) | Models/의 모든 @Model class를 등록 |
| ContentView init 파라미터 불일치 | "Missing argument" 에러 | ContentView의 init을 확인하고 모든 서비스 전달 |
| API_BASE_URL 미설정 | 런타임 fatalError | Debug.xcconfig에 `API_BASE_URL = http:/$()/localhost:8080` 확인 |
