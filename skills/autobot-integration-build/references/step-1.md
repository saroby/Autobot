## Step 1: Integration Wiring

ui-builder가 프로토콜 타입(`any XxxServiceProtocol`)과 Stub으로 작성한 코드를, data-engineer의 실제 Repository로 연결한다.

**배선 위치**: `App/CompositionRoot.swift`에 ModelContainer와 실제 Repository를 조립한다. App 엔트리는 이 composition을 사용하고 기존 `@main`을 유지한다. View/ViewModel은 서비스 프로토콜에 의존한다.

구체적인 배선 패턴이 필요할 때만 [wiring-patterns.md](wiring-patterns.md)를 읽는다.

### 핵심 원칙

1. **ServiceStubs.swift는 절대 삭제하지 않는다** — Preview와 테스트에서 계속 사용. 삭제하면 모든 `#Preview` 블록이 컴파일 에러.
2. **ModelContainer를 stored property로 생성** — `.modelContainer(for:)` modifier는 Environment에 주입하지만, `body` 안에서 `@Environment(\.modelContext)`를 사용할 수 없다. Repository init에 modelContext를 전달하려면 직접 생성해야 한다.
3. **교체 전 init 시그니처 확인**:
   ```bash
   grep -n 'init(' <AppName>/Services/*Repository.swift <AppName>/Services/*Service.swift 2>/dev/null
   ```

### Backend Integration (backend_required == true)

- APIClient가 `Bundle.main`의 `API_BASE_URL`을 사용하는지 확인
- Auth 헤더 주입 로직 존재 확인
- SSE 파싱 코드 존재 확인 (LLM 스트리밍 엔드포인트가 있을 때)
- `backend/.env`가 `.gitignore`에 포함 확인
- `backend/.env.example`에 모든 필수 키 나열 확인
