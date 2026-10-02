# Optional ui-builder patterns

Use only when a pattern needs clarification. Adapt examples to the actual contracts; these are not additional requirements.

## Example 1

```swift
// ViewModel pattern — 프로토콜에 의존, 구현체에 의존하지 않음.
// 에러는 do/catch 로 노출한다 — `try?` 로 삼키면 로드 실패가 "데이터 없음"으로
// 위장된다 (quality-engineer 체크리스트: 비-테스트 코드 신규 try?/try! 0건).
@Observable @MainActor
final class ScreenNameViewModel {
    var items: [Item] = []
    var isLoading = false
    var errorMessage: String?
    private let service: any ItemServiceProtocol

    init(service: any ItemServiceProtocol) {
        self.service = service
    }

    func loadItems() {
        isLoading = true
        defer { isLoading = false }
        do {
            items = try service.fetchAll()
            errorMessage = nil
        } catch {
            // View 는 errorMessage 를 EmptyStateView 의 에러 variant 로 렌더한다
            errorMessage = error.localizedDescription
        }
    }
}

// View pattern — 프로토콜 타입으로 서비스를 받는다
struct ScreenNameView: View {
    @State private var viewModel: ScreenNameViewModel

    init(service: any ItemServiceProtocol) {
        _viewModel = State(initialValue: ScreenNameViewModel(service: service))
    }

    var body: some View {
        // Content
    }
}
```

## Example 2

```swift
// ✅ 올바른 패턴
@MainActor
enum PreviewData {
    static let sampleItems: [Item] = [
        Item(name: "Sample")
    ]
}

// ❌ 컴파일 에러 — @MainActor 누락
enum PreviewData {
    static let sampleItems: [Item] = [...]  // Swift 6: not concurrency-safe
}
```

## Example 3

```swift
// ✅ 올바른 패턴 — 프로토콜 타입으로 주입
struct ContentView: View {
    let todoService: any TodoServiceProtocol
    let categoryService: any CategoryServiceProtocol

    var body: some View {
        TabView {
            Tab("홈", systemImage: "house.fill") {
                HomeView(service: todoService)
            }
        }
    }
}

// ❌ 잘못된 패턴 — 구체 클래스 직접 참조
struct ContentView: View {
    let todoService: TodoRepository  // stub 교체 불가
}
```
