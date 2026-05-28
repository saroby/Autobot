# Changelog

이 파일은 Autobot 플러그인의 주요 변경을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)을 따르고, 버전은 [Semantic Versioning](https://semver.org/)을 사용한다.

## [Unreleased]

### Added
- **Design System SPM**: 매 MVP 빌드마다 in-tree 로컬 패키지 `Packages/<Name>DS/` 를 자동 생성. architect 가 `architecture.json.designSystemModule` 로 이름 결정 (관례: `<AppName>DS`), Phase 3 scaffold 가 골격 + project.yml wiring, 새 `design-system` 서브 에이전트가 Tokens/Components 채움.
- 새 게이트: `design_system_package_exists`, `design_system_tokens_exist` (Gate 3→4).
- `create-xcode-project.sh --design-system-module` 플래그.

### Changed
- ui-builder 는 더 이상 `Utilities/Theme.swift` 를 생성하지 않는다. 대신 `import <Name>DS` 후 패키지 토큰을 사용한다.
- Phase 3 가 (self scaffold → design-system 에이전트) 2 단계 dispatch 로 변경.
- `fileOwnership.agents` 에 `design-system` 추가, `ui-builder.writes` 에서 `Theme.swift` 제거.

## [0.5.0] — 2026-05-26

자기개선 루프의 마지막 마디를 닫고, Phase 5/Gate 5→6 에서 빌드는 통과하지만 런타임에서 깨지는 결함을 차단하는 릴리스. 신규 헬퍼 모듈 14개 + 회귀 테스트 11종 + declarative gate 확장 + agent/command/orchestrator 거대 리팩토링.

### Added
- **신규 헬퍼 모듈 14개** (`scripts/`) — gate descriptor 가 직접 호출하는 단일 책임 도구:
  - `sandbox_guard.py` — agent file ownership 사전 차단
  - `visual_contract.py` — 디자인 룩앤필 픽셀 비교 (Pillow)
  - `sim_runtime.py` — 시뮬레이터 부팅 + smoke 실행
  - `xcodebuild_runner.py` — xcodebuild 호출 + 에러 시그니처 추출
  - `intent_spec.py` — 앱 의도 manifest 로드 + 미사용 앵커 탐지
  - `input_hash.py` — 입력 해시 + phase skip 판정 (`/autobot:resume` 의존)
  - `error_signature.py` — 빌드 에러 정규화 + 누적 (Build-Fix Loop 학습 입력)
  - `metadata_validator.py` — App Store 메타데이터 길이/형식 검증
  - `design_spec_validator.py` — design-spec 룩앤필 계약 검증/합성
  - `learning_impact.py` — 학습 적용 효과 점수화 (effect_score 자동 갱신)
  - `run_summary.py` — `artifacts/<buildId>/run-summary.{json,md}` 생성
  - `context_pack.py` — phase/agent 별 컨텍스트 팩 빌드 (토큰 예산 인식)
  - `env_snapshot.py` — capture/load/ensure/is-stale 환경 스냅샷
  - `verify-phase7-axiom.py` — Phase 7 axiom health-check 결과 검증
- **회귀 테스트 11종** — `test_sandbox_guard`, `test_visual_contract`, `test_intent_spec`, `test_input_hash`, `test_error_signature`, `test_design_spec_validator`, `test_learning_impact`, `test_run_summary`, `test_peer_review_bridge`, `test_axiom_and_peer_strict`. 회귀 슈트 148 → 148 통과 (이전 39 → 신규 109).
- **Axiom / Peer Review Bridge SSOT** — `skills/autobot-axiom-bridge/SKILL.md` + `skills/autobot-peer-review-bridge/SKILL.md`. 호출 규칙·프롬프트·결과 기록 위치를 한 곳에 정리. 감지는 `scripts/detect-axiom.sh` / `scripts/detect-peer-ai.sh` (exit code 기반, silent skip 보장).
- **record-environment 필드 확장** — `runtimeHost`, `peerAi`, `peerReviewAvailable` 3개 추가. peer-review 가용성을 build-state 에 명시 기록해 Gate 5→6 verdict 검증의 근거로 사용.
- **`pipeline.sh` 신규 서브커맨드 8개** — `env-snapshot`, `write-run-summary`, `grade-learnings`, `input-hash`, `context-pack`, `error-signature`, `design-spec`, `sandbox`. 모든 신규 도구를 단일 진입점으로 노출.
- **`hooks/sandbox-pre-write.sh`** — PreToolUse 활성화 후보. payload schema 검증 전까지는 hooks.json 미등록 (메모 보존).

### Changed
- **agent/command/orchestrator 거대 리팩토링 — SSOT 위임** — drift 표면 6→1:
  - `agents/architect.md` -330 줄 (Design Direction 체크리스트 → references 위임)
  - `commands/mvp.md` -450 줄 (Phase 단계 설명 → orchestrator SKILL 위임)
  - `skills/autobot-orchestrator/SKILL.md` -380 줄 (spec/pipeline.json 으로 위임)
  - `agents/quality-engineer.md` / `agents/ui-builder.md` — 신규 헬퍼 사용 의무 명시
- **Gate 5→6 강화** — axiom critical-audit 통과 + peer-review verdict ∈ {PASS, skipped} 강제. 코드 변경: `spec/pipeline.json` (+290), `scripts/gate_runner.py` (+620 lazy import 라우팅), `scripts/phase_advance.py`.
- **Phase 1 codex review verdict 강화** (`scripts/codex-architecture-review.sh`) — skipped 명시 기록, hardViolations 적재, max 2회 재실행.
- **Phase 5 통합 빌드 SKILL** (`skills/autobot-integration-build/SKILL.md`) — error_signature 호출 + Build-Fix Loop 환경 우선 체크리스트 5항목 선행.
- **Phase 7 회고 — axiom health-check 흡수** (`skills/autobot-retrospective/SKILL.md`) — `verify-phase7-axiom.py` 결과를 build-report.md / learnings.json 에 누적.
- **Xcode 프로젝트 생성 강화** (`skills/autobot-ios-scaffold/scripts/create-xcode-project.sh`) — Export Compliance 자동 처리, privacy/entitlements 기본값 보정.
- **README** — Axiom / Peer Review Bridge 섹션 신설, Phase 표 갱신.

### Notes
- 모든 신규 헬퍼는 lazy import — gate 미사용 경로에서 import 오버헤드 0.
- 회귀 슈트는 stdlib only (`python3 -m unittest`) — pytest 의존성 없음.

## [0.4.0] — 2026-05-22

### Added
- **axiom-distilled 지식 베이스** — `references/axiom-distilled/` 디렉토리 신설. axiom 플러그인(MIT)의 iOS 26+ 핵심 규칙을 Autobot 자족 형태로 증류한 4개 문서:
  - `design.md` (172줄) — Liquid Glass Regular/Clear 결정 트리, HIG 빠른 결정, SF Symbols 렌더링 모드, App Composition (@main + @Observable + Root 분기), 6항목 자가 체크리스트
  - `swiftui.md` (197줄) — @State private 강제, @Observable 소유권 4가지 도구 결정 트리, NavigationStack 라우터, 성능 7항목 점검, iOS 26 신기능, 8항목 자가 체크리스트
  - `data-concurrency.md` (284줄) — SwiftData @Model 규칙(final, @Relationship 배열 기본값, deleteRule), VersionedSchema 강제, Repository @MainActor 패턴, Swift 6 Sendable 5규칙, 런타임 크래시 진단표, 9항목 자가 체크리스트
  - `build-testing.md` (245줄) — 환경 우선 빌드 실패 분류, 에러 메시지→도메인 매핑표, Swift Testing 표준(@Test/#expect), sleep 금지 패턴, .xcresult 추출 명령, 9항목 자가 체크리스트
- 각 파일은 axiom MIT 출처 명시 + WWDC 2025+ 갱신 정책 명시 + Anti-Rationalization 표 포함.

### Changed
- **에이전트 4개의 Pre-read 의무 추가** — Autobot 이 외부 axiom 플러그인 없이도 iOS 26+ 코드 품질을 보장하도록 4개 에이전트 헤더에 "Pre-read (필수, 순서대로)" 섹션 삽입:
  - `agents/architect.md` (+4줄) — design.md, data-concurrency.md 의무 참조. Design Direction 작성 시 6항목 체크리스트 충족.
  - `agents/ui-builder.md` (+7줄) — swiftui.md, design.md, data-concurrency.md 의무 참조. Phase 4 완료 직전 8항목 grep 검증.
  - `agents/data-engineer.md` (+6줄) — data-concurrency.md, build-testing.md 의무 참조. Repository 구현이 9항목 체크리스트 통과.
  - `agents/quality-engineer.md` (+7줄) — build-testing.md, data-concurrency.md, swiftui.md 의무 참조. Build-Fix Loop 시 *코드 수정 전* 환경 체크리스트 5항목 선행.

### Notes
- 외부 axiom 플러그인 의존성 0건 (감지 코드 `scripts/detect-plugins.sh` 의 `axiom` 필드는 호환성 유지 위해 보존).
- distilled 파일이 SSOT — WWDC 또는 iOS 메이저 릴리스 후 본 파일만 갱신하면 4개 에이전트가 즉시 신지식을 받는다.
- 별도 인프라(훅, CLI) 변경 0건 — 순수 프롬프트/지식 변경으로 재시작 없이 다음 빌드부터 효과.

## [0.3.2] — 2026-05-19

### Added
- **학습 로드 프로토콜 SSOT** — `skills/autobot-orchestrator/references/learning-bootstrap.md` 신설. phase-learnings/active-learnings 2단계 fallback 순서, phase→파일 매핑, `build-log.sh` 호출 규약, `phases.<N>.learningsConsumed[]` 누적 메커니즘을 한 곳에 정리. architect, quality-engineer, deployer, data-engineer, ui-builder, backend-engineer 6개 에이전트의 중복 preamble(각 7-16줄)을 위임 + 에이전트별 필터로 축소해 드리프트 표면을 6→1.

### Changed
- **스킬 디렉토리 작명 통일** — 모든 스킬 디렉토리에 `autobot-` prefix 적용. 기존 8개 디렉토리(`app-icon`, `build-report`, `integration-build`, `ios-scaffold`, `orchestrator`, `retrospective`, `setup`, `ux-design`)가 각각 `autobot-app-icon`/`autobot-build-report`/`autobot-integration-build`/`autobot-ios-scaffold`/`autobot-orchestrator`/`autobot-retrospective`/`autobot-setup`/`autobot-ux-design`로 이동. frontmatter `name:` 필드와 일치하므로 grep/문서 참조가 한 번에 잡힌다.
- `agents/quality-engineer.md`, `agents/deployer.md`, `commands/mvp.md`, `commands/meta.md`, `commands/setup.md`, 일부 skill SKILL.md/스크립트가 새 경로로 일괄 업데이트.
- `scripts/verify_spec_docs.py`, `scripts/render_pipeline_docs.py`가 `autobot-orchestrator` 경로를 가리키도록 갱신. `DOCS_TO_CHECK`에서 사라진 `commands/make.md` 제거하고 `mvp.md`/`testflight.md`로 교체.
- README "구성 요소" 트리가 실제 디렉토리(agents 7개, skills 14개)와 일치하도록 재작성. 누락되어 있던 `backend-engineer`, `ux-designer` 에이전트와 `autobot-app-icon`, `autobot-build-report`, `autobot-integration-build`, `autobot-setup`, `autobot-ux-design` 스킬을 트리에 명시.

### Fixed
- CHANGELOG 0.3.1 항목의 스킬 이름 오타 정정 — `autobot-app-register` → `autobot-register-app`.

## [0.3.1] — 2026-05-19

### Added
- **Phase 6 단일책임 스킬 분해** — 기존 `testflight-deploy` 단일 스킬을 4개로 분리: `autobot-archive-build`(아카이브), `autobot-upload-build`(업로드), `autobot-generate-metadata`/`autobot-upload-metadata`(메타데이터), `autobot-invite-testers`(테스터 초대). 각 스킬은 독립 실행 가능한 `scripts/*.sh`를 동봉.
- **ASC 앱 등록 전용 스킬** `autobot-register-app` 추가. `scripts/register-app.sh`로 App Store Connect 신규 앱 레코드 생성을 분리. 회귀 테스트 `tests/test_app_register.py` 동봉.
- **명령 분리** — `make` 단일 명령을 목적별로 분해: `/autobot:mvp`(MVP 빌드), `/autobot:testflight`(TestFlight 전체 흐름), `/autobot:meta`(메타데이터 작업). `resume`, `setup` 명령도 새 레이아웃에 맞춰 정비.
- **design-spec 룩앤필 계약 의무화** — 디자인 사양에 룩앤필 필드를 강제하고 Stitch 사용 불가 시 fallback 경로를 강화.

### Changed
- `agents/deployer.md`, `skills/orchestrator/SKILL.md`, `spec/pipeline.json`이 새 Phase 6 스킬 구조에 맞춰 갱신.
- README, troubleshooting, build-report 문서가 분리된 스킬/명령 체계 기준으로 정리.
- 검증 표면(validation surfaces) 정합성 보강 — 누락 조건 차단과 디버그 가시성 향상.

### Removed
- `skills/testflight-deploy/` — 4개 단일책임 스킬로 대체.

## [0.3.0] — 2026-04-30

### Changed
- **플러그인 레이아웃 평탄화** — 저장소 루트 자체가 Claude Code 플러그인 디렉토리가 되도록 재배치. `plugins/autobot/` 중첩 트리를 해체하고 `agents/`, `commands/`, `hooks/`, `skills/`, `spec/`, `scripts/`, `tests/`, `references/`, `.claude-plugin/plugin.json`이 모두 루트 직속에 위치한다.
- 설치 명령이 `claude --plugin-dir /path/to/Autobot/plugins/autobot` → `claude --plugin-dir /path/to/Autobot`으로 단축됨.
- 문서 내 `plugins/autobot/...` 경로 참조와 README 디렉토리 트리를 새 레이아웃 기준으로 정리.
- `verify_spec_docs.py` / `render_pipeline_docs.py`의 `PLUGIN_DIR` 상수가 곧바로 저장소 루트를 가리키도록 단순화.

### Notes
- `$CLAUDE_PLUGIN_ROOT`(플러그인 위치)와 `$CLAUDE_PROJECT_DIR`(빌드 대상 앱 디렉토리)은 의미가 다르다. `scripts/*.sh`의 `CLAUDE_PROJECT_DIR` 참조는 빌드 중 사용자 앱 디렉토리를 가리키므로 그대로 유지된다.

## [0.2.1] — 2026-04-28

### Added
- **Phase 1 codex architecture review 게이트**. architect 산출물을 Gate 1→2 전에 codex가 컴파일 영향 이슈로 사전 검증. Phase 5 빌드에서 발견되는 Swift 6 strict concurrency / SwiftData / AVFoundation lifecycle 문제 중 architect 결정에서 비롯된 것을 architect 재실행 단계에서 차단. PASS / FAIL / skipped 세 verdict 모두 처리 — codex 미설치 시 skipped로 진행 보장, FAIL 시 hardViolations를 state에 적재 후 architect 재디스패치(max 2회), `excludeFromCircuitBreaker`로 orchestrator-side 재시도가 breaker를 트립하지 않음.
- 신규 스크립트 `scripts/codex-architecture-review.sh` (334 LoC).

### Removed
- `marketplace.json` — 마켓플레이스 등록 경로 폐기.
- README의 `.env` 언급 및 `.env.example` 자동 복사 기능.

## [0.2.0] — 2026-04-27

플러그인 골격 정합성 — 단일 기준(SSOT) 강화 + atomic semantics + 회귀 보호.

### Added
- **자동 회귀 테스트 슈트** (`tests/`, stdlib unittest, 19개 케이스). `tests/run_tests.sh`로 실행.
- **advance-phase** 명령. `scripts/pipeline.sh advance-phase --phase N` — 해당 phase의 outgoing gate 실행 + 통과 시에만 phase 완료 마킹. 실패 시 자동 retryCount 증가. 호출자가 `--increment-retry`를 빠뜨리는 회귀 차단.
- **set-flag** 명령. `pipeline.sh set-flag --key backend_required --value true`. 화이트리스트는 `spec.policies.allowedFlags`.
- **Circuit breaker auto-recovery**. global retryCount 합이 `policies.circuitBreaker.maxConsecutivePhaseFailures`에 도달하면 retro phase가 자동으로 `in_progress`, 미완료 phase는 `skipped`(`skipReason` 기록).
- **Sandbox enforcement**. `spec.fileOwnership.agents.<>.writes`가 SSOT. 위반은 `phases.<id>.sandbox.violations`에 기록되고 Gate 4→5의 `sandbox_clean` 체크가 평가. Unknown agent는 즉시 거부.
- **Phase-level snapshot SSOT**. `snapshot_runner.py`가 `fileOwnership.agents.<phase 담당>.writes`에서 디렉토리 자동 도출. shell case-hardcode 제거.
- **logEvents 스키마**. `spec.logEvents`에 event 이름 + required/optional 필드 + per-event `detailSchema`. `build-log.sh`/`runtime append-log`가 검증. 알 수 없는 event 또는 누락 필드는 fail-loud.
- **learning_applied 추적**. agent가 학습 적용 시 이벤트 기록 → `phases.<id>.learningsConsumed` 누적 → Gate 1/4/5의 `state_field_contains` 체크가 강제.
- **Declarative gate descriptors**. spec에 `file_exists`, `dir_exists`, `dir_has_swift`, `file_grep`, `command_success`, `state_field_eq`, `state_field_contains`, `all` primitive. 절차적 체크는 `procedural` 디스크립터로 명시 등록.
- **CONVENTIONS.md** — 출력 prefix 정책, atomicity 규칙, 모듈 의존 그래프, SSOT 위치를 한 곳에 정리.

### Changed
- `runtime.py` 1225L → 66L facade. 6개 모듈로 책임 분리: `spec_loader.py`, `state_store.py`, `event_log.py`, `transitions.py`, `gate_persistence.py`, `phase_advance.py`. 호환을 위해 `from runtime import X`는 그대로 동작 (각 모듈의 `__all__`이 facade의 source-of-truth).
- `validate-state.sh`는 read-only 진단 전용으로 축소 (schema/transition/list-checks/verify-docs/render-docs). mutating 명령은 모두 `pipeline.sh`로 일원화.
- `phases.<5>.metadata.build_succeeded`가 Gate 5→6의 단독 truth source. build-log fallback 제거.
- `gate_runner` procedural 함수가 `spec.fileOwnership`에서 경로 도출. hard-code 제거.
- `phase_advance.advance_phase`가 `AdvanceResult`를 반환하고 CLI wrapper가 출력 — testability 향상.
- spec `schemaVersion`을 1 → 2로 bump. build-state에 `schemaVersion` 기록 + 호환성 검사 (구버전은 WARN, 신버전은 ERROR).

### Fixed
- "complete-phase → run-gate" 순서 뒤집힘으로 phase가 `completed` 상태에서 gate fail이 발생해 비일관 상태로 박제되던 회귀.
- `build_attempt` 이벤트의 `succeeded` 필드 부재로 Gate 5→6의 build-log fallback이 항상 false 반환하던 silent failure.
- Sandbox enforcement가 `allowed=[]` 분기에서 OWNERSHIP 검사를 silent skip하던 결함.
- `advance_phase`가 transition 거부 시 gate evidence와 build-log 행을 기록하던 partial-write 회귀 (codex Q6).
- soft gate 실패가 phase status에 흔적을 남기지 않아 resume이 놓치던 결함 → `phases.<id>.gate_evidence.softFailure`로 기록.
- Sandbox snapshot 파일이 직접 overwrite되어 partial JSON 가능성이 있던 결함 → tmp + rename atomic write.
- `append_build_log`가 spec load 실패를 silent fallback으로 삼키던 결함 → fail-loud.

### Removed
- `validate-state.sh`의 mutating 서브커맨드 (`init-state`, `set-phase-status`, `record-environment`, `record-gate-result`, `run-gate`). 명시적 ERROR + 대체 명령 안내.
- `advance-phase`의 `--increment-retry`/`--retry-count` 옵션 — 자동 증가가 표준이라 잡음.
- `_circuit_breaker_tripped` BC alias.

## [0.1.11] — 2026-04 이전

이전 릴리스. 본 changelog 도입 전이라 git log를 참조한다.
