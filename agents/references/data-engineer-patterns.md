# Optional data-engineer patterns

Use only when a pattern needs clarification. Adapt examples to the actual contracts; these are not additional requirements.

## Example 1

```swift
import SwiftData
import Foundation

@MainActor
enum SampleData {
    // Preview 전용 — #Preview 에서만 사용 (런타임 seed 와 별개)
    static let previewItems: [Item] = [ /* ... */ ]

    /// 런타임 first-launch seed. seedPolicy=="seeded" 앱에서 quality-engineer 가
    /// ModelContainer 생성 직후 1회 호출한다. seed-once 플래그로 멱등.
    static func seedIfNeeded(_ context: ModelContext) {
        let key = "autobot.seeded.v1"
        guard !UserDefaults.standard.bool(forKey: key) else { return }

        // factory: 매 호출 새 인스턴스 생성 (static let 재사용 금지)
        let trips = [
            Trip(title: "Kyoto in Autumn", summary: "Temples, maples, and quiet streets."),
            Trip(title: "Lisbon Food Walk", summary: "Pastéis, tascas, and tram 28."),
            // … 화면을 채울 만큼 (8–12), 도메인 현실적 카피
        ]
        for trip in trips {
            context.insert(trip)
            // @Relationship 도 함께 채운다
            trip.stops = [Stop(name: "Day 1", note: "…"), Stop(name: "Day 2", note: "…")]
        }

        // try? 금지(axiom data-concurrency pre-read) — seed 실패는 곧 빈 화면이라
        // loud fail 이 옳다. save 성공 후에만 플래그를 세워 실패 시 다음 실행에 재시도.
        do {
            try context.save()
            UserDefaults.standard.set(true, forKey: key)
        } catch {
            assertionFailure("seed failed: \(error)")
        }
    }
}
```

## Example 2

```swift
// Repository는 상태를 갖지 않으므로 @Observable 불필요. @MainActor만 사용.
@MainActor
final class ItemRepository: ItemServiceProtocol {
    private let modelContext: ModelContext

    init(modelContext: ModelContext) {
        self.modelContext = modelContext
    }

    func fetchAll() throws -> [Item] {
        let descriptor = FetchDescriptor<Item>(sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
        return try modelContext.fetch(descriptor)
    }

    func add(_ item: Item) {
        modelContext.insert(item)
    }

    func delete(_ item: Item) {
        modelContext.delete(item)
    }

    func save() throws {
        try modelContext.save()
    }

    /// 비-CRUD 파생 메서드 — ServiceProtocols 계약에 선언된 시그니처 그대로 구현한다.
    /// 반환 struct(WeeklySummary)는 architect 가 Models/ 에 정의한 타입 — 여기서 재정의하지 않는다.
    func weeklySummary() throws -> WeeklySummary {
        let weekAgo = Calendar.current.date(byAdding: .day, value: -7, to: .now) ?? .now
        let descriptor = FetchDescriptor<Item>(predicate: #Predicate { $0.createdAt >= weekAgo })
        let recent = try modelContext.fetch(descriptor)
        return WeeklySummary(total: recent.count, completed: recent.filter(\.isCompleted).count)
    }
}
```

## Example 3

```swift
actor NetworkService {
    private let session: URLSession
    private let decoder: JSONDecoder

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
        self.decoder.dateDecodingStrategy = .iso8601
    }

    func fetch<T: Decodable>(_ type: T.Type, from url: URL) async throws -> T {
        let (data, response) = try await session.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw NetworkError.invalidResponse
        }
        return try decoder.decode(T.self, from: data)
    }
}

// ⚠️ architect가 Models/NetworkError.swift를 이미 생성했으면 아래를 정의하지 않는다.
// Models/ 파일을 먼저 읽어 중복 여부를 확인할 것.
enum NetworkError: LocalizedError {
    case invalidResponse
    case decodingFailed

    var errorDescription: String? {
        switch self {
        case .invalidResponse: "서버 응답이 유효하지 않습니다"
        case .decodingFailed: "데이터 디코딩에 실패했습니다"
        }
    }
}
```

## Example 4

```swift
@MainActor
final class APIClient {
    private let session: URLSession
    private let baseURL: URL
    private var authToken: String?

    init(session: URLSession = .shared) {
        self.session = session
        guard let urlString = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
              let url = URL(string: urlString) else {
            fatalError("API_BASE_URL not configured in Info.plist")
        }
        self.baseURL = url
    }

    func setAuthToken(_ token: String) {
        self.authToken = token
    }

    func request<T: Decodable>(_ type: T.Type, path: String, method: String = "GET", body: (any Encodable)? = nil) async throws -> T {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token = authToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.httpBody = try JSONEncoder().encode(body)
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw NetworkError.invalidResponse
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func streamSSE(path: String, body: some Encodable) -> AsyncThrowingStream<ChatStreamChunk, Error> {
        AsyncThrowingStream { continuation in
            Task {
                var request = URLRequest(url: baseURL.appendingPathComponent(path))
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                if let token = authToken {
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                }
                request.httpBody = try JSONEncoder().encode(body)

                let (bytes, _) = try await session.bytes(for: request)
                for try await line in bytes.lines {
                    guard line.hasPrefix("data: ") else { continue }
                    let json = Data(line.dropFirst(6).utf8)
                    let chunk = try JSONDecoder().decode(ChatStreamChunk.self, from: json)
                    continuation.yield(chunk)
                    if chunk.done { break }
                }
                continuation.finish()
            }
        }
    }
}
```

## Example 5

```swift
@MainActor
final class AuthRepository: AuthServiceProtocol {
    private let apiClient: APIClient
    private(set) var currentUser: UserInfo?

    init(apiClient: APIClient) { self.apiClient = apiClient }

    func signInWithApple(identityToken: String) async throws -> AuthResponse {
        struct Body: Encodable { let identityToken: String }
        let response = try await apiClient.request(AuthResponse.self, path: "/auth/apple", method: "POST", body: Body(identityToken: identityToken))
        apiClient.setAuthToken(response.accessToken)
        currentUser = response.user
        return response
    }
    // ... other providers
}
```
