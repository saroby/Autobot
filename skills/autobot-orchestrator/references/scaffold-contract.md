## Composition Seam (Phase 3 출력)

Phase 3 scaffold 는 다음을 **컴파일 가능한 형태로** 생성한다 — Phase 4 에이전트의 충돌 표면을 최소화하기 위함:

- `<AppName>/App/AppEntry.swift` — `@main` 단일 진입점
- `<AppName>/App/CompositionRoot.swift` — 의존성 주입 위치 (quality-engineer 만 수정)
- `<AppName>/App/ServiceStubs.swift` — Preview 용 mock (ui-builder 가 생성/유지)
- `<AppName>/Models/ServiceProtocols.swift` — 통합 계약 (architect 만 수정)

Phase 4 의 ui-builder/data-engineer 는 protocol 뒤 구현만 작성한다. `@main`, `CompositionRoot`, `Models` 직접 수정 금지 — Gate 4→5 는 `@main` 단일성·ServiceStubs 보존만 검사하고, CompositionRoot 의 stub 오염은 Gate 5→6 `no_stubs_in_app` 이 차단한다.

### Phase 3 two-step dispatch

Phase 3 는 두 단계로 실행된다 (모두 같은 phase 번호 내에서):

1. **scaffold (self)** — `create-xcode-project.sh` 호출. 인자에 `--design-system-module $(jq -r .designSystemModule .autobot/architecture.json)` 를 반드시 전달. Composition seam + `Packages/<Module>/Package.swift` + project.yml wiring + Tokens stub 4개 생성.
2. **design-system 에이전트 dispatch** — context-pack 으로 phase 슬라이스 + fileOwnership.agents.design-system.writes + design-spec.md / architecture.md 입력 경로를 전달. sandbox marker 의 `agent` 는 `design-system`.

두 단계 사이에는 `advance-phase` 를 호출하지 않는다 (같은 phase). step 1 실패 시 step 2 는 생략. step 2 실패 시 retryCount 가 phase 3 의 maxRetry (1) 안이면 step 2 만 재실행.
