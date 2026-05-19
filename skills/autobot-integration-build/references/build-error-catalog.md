# Build Error Catalog

빌드 에러를 카테고리별로 분류하고, 각 에러에 대한 진단법과 수정 레시피를 제공한다.
이 카탈로그는 빌드마다 새로운 패턴이 발견되면 추가한다.

> **사용법**: Step 3의 진단 의사결정 트리에서 에러를 분류한 후, 해당 카테고리의 패턴을 찾아 수정한다.

## [A] Import / Module 에러

가장 흔하고, 가장 연쇄 효과가 큰 에러 카테고리. 하나의 import 누락이 10개 이상의 에러를 유발할 수 있다.

| 에러 메시지 | 근본 원인 | 수정 |
|------------|----------|------|
| `Cannot find type 'ModelContext' in scope` | `import SwiftData` 누락 | 파일 상단에 `import SwiftData` 추가 |
| `Cannot find type 'Color' in scope` | `import SwiftUI` 누락 | 파일 상단에 `import SwiftUI` 추가 |
| `Cannot find type 'URL' in scope` | `import Foundation` 누락 | 파일 상단에 `import Foundation` 추가 |
| `No such module 'PackageName'` | SPM 패키지 미등록 | `xcodebuild -resolvePackageDependencies` 또는 project.yml에 패키지 추가 |
| `Cannot find 'XxxView' in scope` | 다른 모듈/파일의 타입 참조 | 파일이 프로젝트에 포함되었는지 확인 (Step 0 재실행) |

### 진단 팁

```bash
# 어떤 import가 누락되었는지 빠르게 확인
grep -rn "Cannot find" build_output.log | sed 's/.*Cannot find type//' | sort -u

# 특정 타입이 어디서 정의되었는지 찾기
grep -rn "class ModelName\|struct ModelName\|enum ModelName\|protocol ModelName" <AppName>/
```

### 연쇄 해결 패턴

`import SwiftData` 하나를 추가하면 다음 에러들이 동시에 해결된다:
- `Cannot find type 'ModelContext'`
- `Cannot find type 'ModelContainer'`
- `Cannot find macro 'Model'`
- `Cannot find type 'FetchDescriptor'`
- `Cannot find type 'SortDescriptor'`

따라서 에러 10개가 모두 SwiftData 관련이면 **import 1줄 추가로 전부 해결**된다.

## 함정 에러: Models/ 수정이 필요해 보이지만 아닌 경우

이 패턴들은 Models/를 수정하고 싶은 유혹이 크지만, 실제로는 사용 코드에서 해결해야 한다. Models/는 architect의 타입 계약이므로 절대 수정하지 않는다.

### "does not conform to Identifiable" (ForEach)

`ForEach(viewModel.items)` → `Identifiable` 미충족 에러.

- **잘못된 수정**: Models/의 `@Model class Item`에 `: Identifiable` 추가
- **올바른 수정**: `ForEach(viewModel.items, id: \.persistentModelID)` — `@Model` 클래스는 `PersistentModel` 프로토콜을 통해 `persistentModelID`를 이미 가지고 있다
- **또는**: View 파일에 extension 추가 (Models/ 밖에서):
  ```swift
  extension Item: Identifiable {
      var id: PersistentIdentifier { persistentModelID }
  }
  ```

### "does not conform to Hashable" (NavigationLink)

`NavigationLink(value: item)` → `Hashable` 미충족 에러.

- **잘못된 수정**: Models/의 `@Model class Item`에 `Hashable` conformance 추가
- **올바른 수정**: `NavigationLink(value: item.persistentModelID)` + `.navigationDestination(for: PersistentIdentifier.self)`
- **또는**: View 파일에 extension 추가 (Models/ 밖에서):
  ```swift
  extension Item: Hashable {
      static func == (lhs: Item, rhs: Item) -> Bool { lhs.persistentModelID == rhs.persistentModelID }
      func hash(into hasher: inout Hasher) { hasher.combine(persistentModelID) }
  }
  ```

### "Cannot find type 'X'" in ServiceProtocols.swift

ServiceProtocols.swift에서 `Cannot find type 'Item'` 에러가 보인다.

- **잘못된 수정**: ServiceProtocols.swift에 `import SwiftData` 추가 (이 파일은 Models/ 안에 있으므로 수정 금지)
- **올바른 수정**: 이 에러는 **다른 파일의 import 문제에서 연쇄 발생**한 것이다. ServiceProtocols.swift 자체를 수정하지 말고, 이 프로토콜을 사용하는 파일들(ViewModels/, Services/)의 import를 먼저 수정한다. 연쇄 에러가 해결되면 이 에러도 자연히 사라진다.

> **원칙**: "Cannot find type" 에러가 Models/ 파일에서 나왔더라도, 수정은 Models/ 밖에서 한다.

## [B] Type / Signature 에러

에이전트 간 타입 시그니처 불일치에서 발생한다. Models/가 "정답"이고, 사용 코드를 수정해야 한다.

| 에러 메시지 | 근본 원인 | 수정 |
|------------|----------|------|
| `Missing argument for parameter 'x' in call` | init 시그니처 불일치 | Models/의 실제 init 확인 후 호출부 수정 |
| `Extra argument 'x' in call` | 존재하지 않는 파라미터 사용 | Models/의 실제 init 확인 후 호출부에서 제거 |
| `Cannot convert value of type 'X' to expected argument type 'Y'` | 타입 불일치 | 실제 타입 확인 후 변환 또는 호출부 수정 |
| `Value of type 'X' has no member 'y'` | 존재하지 않는 프로퍼티/메서드 참조 | Models/의 실제 멤버 확인 후 올바른 이름으로 수정 |
| `Ambiguous reference to member 'x'` | 같은 이름의 멤버가 여러 곳에 존재 | 명시적 타입 어노테이션 추가 |
| `Cannot use optional chaining on non-optional value` | optional/non-optional 혼동 | Models/의 실제 타입 확인 후 `?` 제거 또는 추가 |
| `Value of optional type 'X?' must be unwrapped` | non-optional로 예상했으나 실제는 optional | `if let` 또는 `guard let`으로 안전하게 unwrap |

### 진단 팁

```bash
# Models/의 실제 init 시그니처 모두 확인
grep -n 'init(' <AppName>/Models/*.swift

# 특정 타입의 프로퍼티 목록 확인
grep -A 20 'class ModelName' <AppName>/Models/ModelName.swift | grep 'var \|let '

# ServiceProtocols의 메서드 시그니처 확인
grep -n 'func ' <AppName>/Models/ServiceProtocols.swift
```

### 수정 원칙

1. **Models/는 절대 수정하지 않는다** — architect가 정의한 타입 계약이 SSOT (Single Source of Truth)
2. **호출부(Views, ViewModels, Services)를 수정**한다
3. 시그니처를 맞출 때는 Models/의 실제 코드를 **반드시 읽고** 수정한다 (추측으로 수정하면 2차 에러 발생)

## [C] Concurrency 에러

Swift 6 strict concurrency에서 발생. 정확한 이해 없이 수정하면 런타임 크래시로 이어질 수 있다.

| 에러 메시지 | 근본 원인 | 수정 |
|------------|----------|------|
| `Main actor-isolated property 'x' can not be referenced from a non-isolated context` | @MainActor 누락 | ViewModel/View에 `@MainActor` 추가, 또는 `await MainActor.run { }` 사용 |
| `Sending 'x' risks causing data races` | non-Sendable 타입을 Task boundary 넘김 | 타입에 `Sendable` conformance 추가, 또는 `@MainActor`로 격리 |
| `Non-sendable type 'X' returned by implicitly asynchronous call` | async 호출의 반환값이 non-Sendable | `@MainActor` 격리 또는 `nonisolated` 키워드 사용 |
| `Actor-isolated property 'x' can not be mutated from a non-isolated context` | actor 격리 위반 | `await` 추가 또는 메서드를 `nonisolated`로 변경 |

### 수정 패턴

```swift
// 패턴 1: ViewModel은 항상 @MainActor
@Observable @MainActor
final class ItemViewModel {
    // ...
}

// 패턴 2: ServiceProtocol은 @MainActor
@MainActor protocol ItemServiceProtocol {
    func fetchAll() async throws -> [Item]
}

// 패턴 3: Task에서 MainActor 작업
Task { @MainActor in
    self.items = try await service.fetchAll()
}
```

## [D] SwiftData 에러

SwiftData 모델 정의와 사용에서 발생하는 에러.

| 에러 메시지 | 근본 원인 | 수정 |
|------------|----------|------|
| `@Model requires class` | struct에 @Model 사용 | `struct` → `class`로 변경 (Models/에서 이미 class여야 함 — 사용측에서 struct로 재정의한 경우) |
| `Ambiguous use of 'init'` | @Model의 memberwise init 충돌 | 명시적 init 작성 |
| `Cannot find type 'Schema' in scope` | SwiftData import 누락 (카테고리 [A]) | `import SwiftData` 추가 |
| `Type 'X' does not conform to protocol 'PersistentModel'` | @Model 매크로 누락 | class 정의에 `@Model` 추가 (Models/에 이미 있어야 함) |
| `Referencing initializer 'init(for:)' requires that 'X' conform to 'PersistentModel'` | .modelContainer(for:)에 non-@Model 타입 전달 | @Model 타입만 전달하도록 수정 |
| `Relationship 설정 에러` | @Relationship 매크로 파라미터 오류 | deleteRule, inverse 확인 |

### 진단 팁

```bash
# @Model이 올바르게 적용되었는지 확인
grep -n '@Model' <AppName>/Models/*.swift

# .modelContainer(for:)에 등록된 타입 확인
grep -n 'modelContainer' <AppName>/App/<AppName>App.swift
```

## [E] 프로젝트 설정 에러

Xcode 프로젝트 설정, 빌드 환경, 시뮬레이터 관련 에러.

| 에러 메시지 | 근본 원인 | 수정 |
|------------|----------|------|
| `Unable to find a destination matching the provided destination specifier` | 시뮬레이터 미설치/미사용 | Step 3의 동적 시뮬레이터 탐색 사용 |
| `Multiple commands produce` | 중복 파일이 빌드에 포함 | 중복 파일 제거 또는 pbxproj 재생성 |
| `No such file or directory: '.../X.swift'` | pbxproj에 등록되었지만 실제 파일 없음 | 파일 생성 또는 pbxproj 재생성 (Step 0) |
| `Command PhaseScriptExecution failed` | 빌드 스크립트 에러 | 스크립트 내용 확인, 권한 확인 |
| `Signing for "X" requires a development team` | 코드 서명 팀 미설정 | 빌드 커맨드에 `CODE_SIGN_IDENTITY="-"` 추가 (시뮬레이터용) |
| `The compiler is unable to type-check this expression` | 과도한 타입 추론 | 명시적 타입 어노테이션 추가, 복잡한 표현식을 분리 |

### 시뮬레이터 없이 빌드하기

테스트가 필요 없고 컴파일만 확인할 때:
```bash
xcodebuild -project *.xcodeproj -scheme <scheme> \
  -destination 'generic/platform=iOS Simulator' \
  build 2>&1 | tail -50
```

## 에러 우선순위

여러 카테고리 에러가 혼재할 때 이 순서로 수정한다:

```
[E] 프로젝트 설정 → [A] Import → [D] SwiftData → [B] 타입 → [C] 동시성
```

이유:
1. **[E]** 프로젝트 설정이 잘못되면 다른 모든 에러가 발생할 수 있다
2. **[A]** Import 누락은 가장 많은 연쇄 에러를 유발한다
3. **[D]** SwiftData 에러는 모델 구조와 관련되어 타입 에러를 유발한다
4. **[B]** 타입 에러는 개별 수정이 필요하다
5. **[C]** 동시성 에러는 다른 에러가 모두 해결된 후에 수정하는 것이 효율적이다

## 빌드 히스토리에서 자주 발견된 패턴

> 이 섹션은 `learnings.json`의 `common_build_errors`에서 가져와 보강한다. 빌드마다 새 패턴이 발견되면 여기에 추가한다.

| 패턴 | 빈도 | 예방법 |
|------|------|--------|
| `Cannot find type 'ModelContext'` | 높음 | ViewModel 파일에 항상 `import SwiftData` 포함 |
| `@Model requires class` | 중간 | architect가 모델을 class로 정의하면 다른 에이전트도 class로 유지 |
| `Missing argument for parameter` | 높음 | Models/의 init 시그니처를 반드시 읽고 사용 |
| optional chaining on non-optional | 중간 | Models/의 optional/non-optional을 정확히 확인 |
