# Changelog

이 파일은 Autobot 플러그인의 주요 변경을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)을 따르고, 버전은 [Semantic Versioning](https://semver.org/)을 사용한다.

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
