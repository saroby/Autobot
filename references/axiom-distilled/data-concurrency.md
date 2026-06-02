# Data & Concurrency — iOS 26+ / Swift 6 Distilled

> **출처**: axiom-data + axiom-concurrency (MIT, WWDC 2025+) 의 핵심 규칙을 Autobot 자족 형태로 증류. 외부 axiom 없어도 동일하게 작동.
>
> **사용자**: `data-engineer` 에이전트(필수), `ui-builder`(참조 — @MainActor 경계, Sendable 통과 시). Repository / Service 구현 코드는 이 규칙을 만족해야 한다.

---

## 0. 절대 규칙 (위반 시 Phase 5 빌드 실패 또는 런타임 크래시)

1. **Swift 6 strict concurrency 활성 가정.** Sendable 위반, data race 경고는 *전부 에러로 취급*.
2. **`@unchecked Sendable` 신규 사용 금지.** 데이터 레이스를 컴파일러에서 숨기는 것일 뿐.
3. **`nonisolated(unsafe)` 금지.** 동일 사유.
4. **SwiftData 모델은 `class`, `@Model`, `final` 권장. struct 절대 금지** (런타임 즉시 크래시).
5. **`ModelContext` 는 actor-isolated. 백그라운드에서 메인 컨텍스트 접근 금지.** `ModelActor` 또는 `Task { @MainActor in … }`.
6. **`try?` 로 디코딩 에러 삼키기 금지** — 조용한 데이터 손실. `do { try } catch { 로그 + 처리 }`.

---

## 1. SwiftData — iOS 17+ 표준 영속 계층

### 모델 정의 패턴

```swift
import SwiftData

@Model
final class Item {
    @Attribute(.unique) var id: UUID
    var title: String
    var createdAt: Date
    var tags: [String]                              // 단순 값 배열 OK

    @Relationship(deleteRule: .cascade, inverse: \Tag.items)
    var taggedBy: [Tag] = []                        // ← 배열 관계는 반드시 기본값

    init(title: String) {
        self.id = UUID()
        self.title = title
        self.createdAt = .now
        self.tags = []
    }
}
```

**규칙**:
- 모든 `@Model` 클래스는 `final`.
- 모든 `@Relationship(.toMany)` 배열은 *반드시* 기본값 `= []`. 누락 시 런타임 크래시.
- `deleteRule` 명시 (`.cascade`, `.nullify`, `.deny`, `.noAction`). 기본값 의존 금지.
- `inverse:` 명시. 양방향 관계는 양쪽에서 선언.

### Container 설정

```swift
@main
struct MyApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
            .modelContainer(for: [Item.self, Tag.self])
    }
}
```

CloudKit 동기화가 필요하면:
```swift
.modelContainer(for: Schema([Item.self, Tag.self]),
                isUndoEnabled: true,
                isAutosaveEnabled: true,
                cloudKitDatabase: .private("iCloud.com.example.app"))
```

CloudKit 사용 시 *추가 제약*:
- 모든 attribute 는 optional 또는 기본값 있어야 함 (CloudKit 호환).
- `@Attribute(.unique)` 사용 불가 (CloudKit 미지원).
- `@Relationship` 은 모두 optional 또는 배열.

### Migration — VersionedSchema 강제

```swift
enum SchemaV1: VersionedSchema {
    static var versionIdentifier = Schema.Version(1, 0, 0)
    static var models: [any PersistentModel.Type] { [Item.self] }
}

enum SchemaV2: VersionedSchema {
    static var versionIdentifier = Schema.Version(2, 0, 0)
    static var models: [any PersistentModel.Type] { [Item.self] }
}

enum AppMigration: SchemaMigrationPlan {
    static var schemas: [any VersionedSchema.Type] { [SchemaV1.self, SchemaV2.self] }
    static var stages: [MigrationStage] {
        [.lightweight(fromVersion: SchemaV1.self, toVersion: SchemaV2.self)]
    }
}
```

**규칙**:
- 첫 빌드부터 `VersionedSchema` 사용. 마이그레이션이 안 필요해 보여도 *시작이 V1 이어야* 다음 변경이 안전.
- 컬럼 추가 = lightweight. 컬럼 의미 변경 = custom stage + 데이터 변환 로직.
- 절대 schema 변경 후 `VersionedSchema` 도입을 미루지 말 것. 사용자 데이터 손실.

### @Query — 뷰에서 SwiftData 읽기

```swift
struct ItemList: View {
    @Query(sort: \Item.createdAt, order: .reverse) private var items: [Item]
    @Environment(\.modelContext) private var ctx

    var body: some View {
        List(items) { ItemRow(item: $0) }
            .toolbar {
                Button("Add") {
                    ctx.insert(Item(title: "New"))
                }
            }
    }
}
```

- `@Query` 는 메인 액터.
- 프레디케이트는 컴파일타임 검증되는 `#Predicate { ... }` 매크로 사용.
- 자주 변하는 정렬/필터는 동적 `@Query(filter: predicate, sort: ...)` + `init` 에서 주입.

---

## 2. Repository 패턴 — Autobot 표준

Autobot 의 `data-engineer` 는 `architecture.md` 의 ServiceProtocol 을 SwiftData 기반 Repository 로 구현한다. 표준 골격:

```swift
@MainActor
protocol ItemRepository {
    func all() throws -> [Item]
    func add(_ title: String) throws
    func delete(_ id: UUID) throws
}

@MainActor
final class SwiftDataItemRepository: ItemRepository {
    private let context: ModelContext

    init(context: ModelContext) {
        self.context = context
    }

    func all() throws -> [Item] {
        try context.fetch(FetchDescriptor<Item>(sortBy: [SortDescriptor(\.createdAt, order: .reverse)]))
    }

    func add(_ title: String) throws {
        context.insert(Item(title: title))
        try context.save()
    }

    func delete(_ id: UUID) throws {
        let target = try context.fetch(FetchDescriptor<Item>(predicate: #Predicate { $0.id == id }))
        target.forEach { context.delete($0) }
        try context.save()
    }
}
```

**규칙**:
- Repository 는 보통 `@MainActor` (UI 와 같은 격리). 백그라운드 작업은 `ModelActor` 로 명시 분리.
- `try context.save()` 를 반드시 호출. SwiftData 자동 저장 timing 에 의존 금지.
- 에러는 호출자에게 throw. Repository 내부에서 try? 로 삼키지 말 것.

---

## 3. Swift 6 Concurrency — 5규칙

### 규칙 1: @MainActor 는 UI 와 UI 인접 타입만

```swift
@MainActor                      // ✅ View, ViewModel, Router, Repository
final class FeedModel { … }

@MainActor                      // ❌ 순수 데이터 변환 클래스
final class JSONParser { … }    // → 격리 불필요. @MainActor 떼면 백그라운드에서 자유롭게 호출 가능.
```

### 규칙 2: Sendable 명시

```swift
struct User: Sendable {         // ✅ 값 타입 + 모든 필드 Sendable → 자동/명시
    let id: UUID
    let name: String
}

final class Cache: Sendable {   // ⚠️ 참조 타입은 immutable 이거나 actor 또는 lock
    let items: [User]
    init(items: [User]) { self.items = items }
}
```

### 규칙 3: 백그라운드 강제는 @concurrent (Swift 6.2+) 또는 detached Task

```swift
@concurrent                     // 호출 시점의 격리와 무관하게 백그라운드
func heavyComputation() async -> Result { … }

// 또는
Task.detached(priority: .background) {
    let result = await heavyComputation()
    await MainActor.run { model.result = result }
}
```

**주의**: `async` 함수가 *자동으로 백그라운드는 아니다*. 호출자의 actor 에서 suspend 됐다가 같은 actor 에서 resume.

### 규칙 4: 콜백/델리게이트 — **전달 스레드에 따라** 격리를 정한다

시스템 콜백은 두 종류이고, **반대 처방**이 필요하다. 하나로 뭉뚱그리면 크래시한다.

#### (A) 델리게이트 메서드 — API 가 *정해진 큐*(보통 메인)로 전달 → `@MainActor` OK

```swift
final class LocationService: NSObject, CLLocationManagerDelegate {
    // CLLocationManager 를 메인에서 생성했으면 델리게이트도 메인 런루프로 전달된다.
    @MainActor
    func locationManager(_ m: CLLocationManager, didUpdateLocations: [CLLocation]) {
        // 메인에서 처리 OK
    }
}
```

#### (B) Completion-handler closure — 시스템이 *임의 백그라운드 큐*에서 호출 → `@MainActor` 금지, `@Sendable` 사용

`SFSpeechRecognizer.requestAuthorization`, `SFSpeechRecognizer.recognitionTask(with:)`,
TCC 권한 콜백, 구형 `AVAudioSession.requestRecordPermission`, `URLSession` completion handler 등은
**백그라운드 스레드**에서 호출된다. 이때 closure 가 (바깥 타입이 `@MainActor` 라서) `@MainActor` 로
격리 추론되면, 런타임이 closure 진입 시 메인 큐 여부를 단언하다 **`_dispatch_assert_queue_fail` 로 즉사**한다
— closure 본문이 무엇을 하든 상관없다. 격리 *자체*가 원인이다.

```swift
@MainActor
final class SpeechService: SpeechTranscriptionServiceProtocol {
    func requestPermission() async -> CapturePermission {
        await withCheckedContinuation { continuation in
            // ✅ @Sendable = nonisolated. 어느 스레드에서 호출돼도 안전.
            SFSpeechRecognizer.requestAuthorization { @Sendable status in
                continuation.resume(returning: Self.map(status))   // 순수 매핑만
            }
        }
    }

    // 매핑은 nonisolated static — @MainActor 상태를 일절 건드리지 않는다.
    nonisolated private static func map(_ s: SFSpeechRecognizerAuthorizationStatus) -> CapturePermission {
        switch s { case .authorized: .granted; case .notDetermined: .notDetermined; default: .denied }
    }
}
```

`@Sendable` closure 안에서 `@MainActor` 상태를 *써야* 하면 `await MainActor.run { … }` / `Task { @MainActor in … }` 로 **명시적으로 hop** 한다. continuation·NSLock 기반 가드는 백그라운드에서 그대로 호출해도 된다.

> **판별법**: "이 콜백을 누가 어느 스레드에서 부르는가?" 메인 보장이 없으면 (B), 즉 `@Sendable`.
> 가능하면 애초에 completion-handler 대신 **async 버전 API**(`AVAudioApplication.requestRecordPermission()` 등)를 써서 이 함정을 통째로 피한다.

### 규칙 5: Task { } 안에서 self 캡처

```swift
@Observable
final class FeedModel {
    var items: [Item] = []

    func refresh() {
        Task { [weak self] in                   // ✅ 명시 [weak self]
            guard let self else { return }
            let fresh = try await api.fetch()
            await MainActor.run { self.items = fresh }
        }
    }
}
```

`@Observable` 클래스에서 `Task { }` 안 self 캡처는 retain cycle 위험. `[weak self]` 또는 명시적 isolation.

---

## 4. 흔한 런타임 크래시 — 즉시 진단

| 크래시 메시지 | 원인 | 해결 |
|---|---|---|
| `_dispatch_assert_queue_fail` | `@MainActor` 격리 closure/메서드가 백그라운드 큐에서 호출됨 | **전달 스레드로 판별** (규칙 4): 메인 전달 델리게이트면 `@MainActor` 유지 · 백그라운드 전달 completion-handler(`SFSpeechRecognizer.requestAuthorization`/`recognitionTask`, TCC, URLSession 등)면 closure 를 `@Sendable`(nonisolated)로 + 상태는 `MainActor.run` 으로 hop |
| `_swift_task_checkIsolatedSwift` | 시스템 콜백 격리 불일치 (대개 위와 동일 패턴) | 위와 동일 — 백그라운드 전달이면 `@MainActor` 가 *원인*이다. `@Sendable` 로 바꾼다 |
| `Fatal error: ModelContext is not the main context` | 백그라운드에서 메인 ModelContext 사용 | ModelActor 분리 또는 Task { @MainActor in } |
| `... no such column ...` | SwiftData migration 누락 | VersionedSchema + MigrationStage |
| `Failed to load NSManagedObject` (CloudKit) | 필수 필드가 optional 아님 | 모든 필드 optional 또는 기본값 |

---

## 5. Anti-Rationalization 표

| 생각 | 현실 |
|---|---|
| "@unchecked Sendable 로 일단 빠르게" | 데이터 레이스 *숨기기*. 프로덕션에서 무작위 크래시. |
| "SwiftData migration 은 나중에 해도 돼" | V1 도입을 미루면 다음 변경 = 사용자 데이터 손실. |
| "백그라운드에서 ModelContext 그냥 쓰면 되겠지" | 메인 컨텍스트 백그라운드 접근 = 크래시. ModelActor 필수. |
| "try? 로 일단 컴파일은 통과시키자" | 디코딩 실패가 조용히 빈 배열 반환 → 사용자 데이터 사라진 것처럼 보임. |
| "Swift 6 경고는 워닝일 뿐" | Strict concurrency 활성이면 경고는 *런타임 크래시 예고*. |
| "콜백은 그냥 두면 알아서 메인에서 호출되겠지" | iOS 17+ 부터 시스템 콜백 격리 검증. 메인 가정 = 크래시. |
| "ObservableObject 가 익숙해서…" | iOS 17+ 는 @Observable. 업데이트 빈도 차이 = 성능 + 배터리. |

---

## 6. data-engineer Self-Check (Phase 4 완료 직전)

- [ ] 모든 `@Model` 클래스가 `final`
- [ ] 모든 `@Relationship(.toMany)` 배열에 기본값 `= []`
- [ ] 모든 `@Relationship` 에 `deleteRule:` 명시
- [ ] VersionedSchema 도입 (V1 이라도)
- [ ] `try?` 또는 `try!` 0건 (단위 테스트 mock 제외)
- [ ] `@unchecked Sendable` / `nonisolated(unsafe)` 0건
- [ ] Repository 가 `@MainActor` 또는 명시적 actor
- [ ] CloudKit 사용 시: `@Attribute(.unique)` 0건, 모든 필드 optional/기본값
- [ ] 모든 시스템 콜백(CLLocationManager 등) 에 명시적 격리

체크 1개라도 빠지면 Phase 4 완료 보고 금지.
