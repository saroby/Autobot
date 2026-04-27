# Lessons — Autobot 구조 개선 (2026-04-27)

## 발견 → 수정 정리

### 1. "complete-then-gate" 시퀀싱 버그
- **실패 모드**: `complete-phase` → `run-gate` 순서로 호출되면 gate 실패 시 phase가 `completed` 상태로 박제됨. 이후 retry 시도는 `completed → in_progress`가 transitions에 없어서 `allowExplicitRestartFromTerminal` 우회에 의존.
- **검출 신호**: state가 `phase=completed + gate=failed`로 모순됨. resume 흐름에서 "이미 완료된 phase"를 또 돌려야 하는 상황.
- **방지 규칙**: phase 완료는 그 phase의 outgoing gate 통과를 전제로 한다. `runtime.advance_phase`만 호출하고 `complete-phase` + 별개 `run-gate`를 외부 스크립트에서 조합하지 않는다.

### 2. 같은 명령의 두 실행 경로
- **실패 모드**: `pipeline.sh run-gate` (state 기록함)와 `validate-state.sh run-gate` (gate_runner.py 직접, 기록 안 함)가 공존. 디버깅 중 후자를 호출하면 "통과했는데 흔적 없음".
- **방지 규칙**: 외부 사용자가 부르는 명령은 단 하나의 경로로 수렴. validate-state.sh는 read-only(`schema/transition/list-checks/verify-docs/render-docs`)만 노출. 이전에 받던 mutating 명령은 명시적 에러 메시지 + 대체 명령 안내.

### 3. silent failure: detail에 `succeeded` 없는 build_attempt
- **실패 모드**: `gate_runner.py`가 `phases.5.metadata.build_succeeded` 미기록 시 build-log를 fallback으로 스캔. `integration-build/SKILL.md`는 `{"attempt":N,"errors":COUNT}`만 기록 → 어떤 입력에도 false 평가. 즉 metadata를 명시적으로 set하지 않으면 영원히 gate fail.
- **방지 규칙**: gate 결정 입력은 단 한 곳(state 필드)에서만 읽는다. 로그는 audit-only이며 gate가 절대 참조하지 않는다. silent fallback은 좋은 의도라도 truth source 이중화를 만들기 쉬워 금지.

### 4. 이벤트 스키마 미정의
- **실패 모드**: `build-log.jsonl`이 회고/디버깅의 1차 데이터 소스인데 event 이름과 필드가 코드 곳곳에서 임의로 결정. 같은 event를 string detail로 쓰는 곳과 dict로 쓰는 곳이 공존.
- **방지 규칙**: SSOT 한 곳(`spec/pipeline.json`의 `logEvents`)에 event 이름 + required/optional 필드를 선언. runtime의 `validate_log_event`가 모든 append를 검증. `build-log.sh`는 thin wrapper로 같은 검증을 거치게 강제.

### 5. 정책이 산문으로 분산되면 일관성 보장 불가
- **실패 모드**: 파일 소유권(ui-builder = Views/...)이 `agents/*.md` + `agent-sandbox.sh` 하드코드 + `snapshot-contracts.sh`에 분산. 한 곳 바꿔도 나머지가 stale.
- **방지 규칙**: 행위 정책은 spec에 데이터로 기록한다. agent 시스템 프롬프트는 정책을 "참조"하되 정책의 권위 위치가 아니다. 새 agent 추가 시 spec.fileOwnership.agents 항목을 안 만들면 enforcement 자동 거부.

### 6. circuit breaker가 spec엔 있는데 enforcement는 없었음
- **실패 모드**: `policies.circuitBreaker.maxConsecutivePhaseFailures: 3`가 spec에 있지만 runtime.transition validator는 phase별 maxRetry만 봄. 누적 실패 임계 초과를 막지 않음.
- **방지 규칙**: spec에 정책 필드 추가 시 runtime에서 enforcement 코드를 같은 PR에 추가한다. 안 그러면 데드 정책이 "동작하는 것처럼 보이는" 위험.

### 7. 데이터 토글의 CLI surface 부재
- **실패 모드**: `backend_required`를 architect 사후 review가 변경해야 하는데 runtime에 set 명령 없음. JSON 직접 편집 권유는 검증 우회.
- **방지 규칙**: state 필드는 어디서든 직접 편집되지 않는다. 매 mutation은 정의된 CLI 명령(`set-flag` 등)을 거쳐 검증 + 로그 1쌍을 만든다.

## codex 2차 리뷰에서 추가로 잡힌 결함 (이 PR에서 수정)

### 8. advance-phase 호출자가 --increment-retry를 빠뜨리면 retryCount 안 늘어남
- **실패 모드**: `make.md`/`resume.md`의 일반 호출은 `--increment-retry` 없이 `advance-phase --phase N`. gate fail 시 phase status는 `failed`로 가지만 retryCount는 0 유지 → maxRetry/circuitBreaker 둘 다 무력화.
- **방지 규칙**: failure path는 호출자 플래그에 의존하지 않는다. `args.retry_count`가 명시적으로 지정된 경우만 그 값을 쓰고, 아니면 자동 증가. 책임은 runtime이 진다.

### 9. circuit breaker onTrip 정책 enforce 부재
- **실패 모드**: `policies.circuitBreaker.onTrip: skipToRetrospective`가 spec에 선언만 있고 실제 동작 없음. trip 후 사용자 개입 필요.
- **방지 규칙**: spec에 정책을 선언했으면 같은 PR에서 enforcement 코드도 작성. trip 시 alwaysRun phase(여기선 7)를 자동으로 `in_progress`로 강제 + `circuit_open` 이벤트 기록.

### 10. snapshot-contracts.sh가 fileOwnership SSOT 무시
- **실패 모드**: phase별 snapshot 대상 디렉토리가 shell `case` 하드코드. spec의 `agents.<>.writes`를 바꿔도 snapshot 대상은 그대로 → `Assets.xcassets` 전체 변경이 colorset만 백업되고 나머지는 복원 시 사라지는 등 SSOT 어긋남.
- **방지 규칙**: 모든 phase ↔ 디렉토리 매핑은 `spec.fileOwnership.agents.<>.writes` 한 곳에서. 새 `snapshot_runner.py`가 phase의 `agents` 목록을 읽어 자동 도출.

### 11. sandbox unknown agent 통과
- **실패 모드**: spec에 등록되지 않은 agent로 `agent-sandbox.sh after`를 호출하면 `allowed=[]` 분기에서 OWNERSHIP 검사 skip. forbidden 외에는 무엇이든 통과.
- **방지 규칙**: `_ensure_known_agent`가 sandbox 시작 시 spec에 등록된 agent만 받게 화이트리스트 검사 + `evaluate_violations`의 "allowed가 비면 skip" 분기를 "allowed가 비면 어떤 쓰기도 violation"으로 교체.

### 12. atomic gate+phase mutation, soft gate 흔적
- **실패 모드**: `_execute_and_record_gate`가 gate 결과를 먼저 쓰고, 별개 호출로 phase status를 바꿈 → 두 mutation 사이 transition 거부 시 partial state. soft gate 실패는 phase status가 `completed`가 되어 resume이 인지 못 함.
- **방지 규칙**: advance_phase가 단일 `mutate_state_with_validation`로 gate 결과 + phase status + (soft fail이면) `gate_evidence.softFailure` 마커까지 한 번에 기록.

### 13. snapshot 파일 atomic write
- **실패 모드**: sandbox snapshot이 직접 overwrite. 중간에 프로세스 죽으면 partial JSON.
- **방지 규칙**: `write_snapshot`을 tmp + rename 패턴으로 변경.

### 14. spec 깨졌을 때 log validation silent 우회
- **실패 모드**: `append_build_log`가 `try/except SystemExit`로 spec load 실패를 삼키고 `{}`로 fallback → 깨진 spec 상태에서 unknown event도 통과.
- **방지 규칙**: spec load 실패는 fail-loud. validation을 절대 silent 우회하지 않는다.

## codex 3차 리뷰에서 잡은 추가 결함 (이 PR에서 수정)

### 15. advance_phase의 partial-write 회귀 (HIGH)
- **실패 모드**: 분리 직전 advance_phase 구현이 mutate 함수 안에서 transition 검증 후 flag만 세우고 그대로 mutate_state_with_validation으로 save → transition 실패해도 gate 결과는 state에 기록. atomic 주장 위반.
- **방지 규칙**: mutate 호출 전에 `validate_transition_request`로 pre-validate. 실패하면 mutate / 로그 emission 모두 abort. mutate가 실행되면 gate evidence + phase status가 동시에 final.
- **검증**: smoke로 retry 한도 초과 시 advance-phase 호출 → state.gates 변경 없음, build-log에 새 entry 없음 확인.

### 16. advance_phase의 잘못된 옵션 표면
- **실패 모드**: `--increment-retry`/`--retry-count`를 advance-phase argparse에 노출. 그러나 자동 증가가 표준 → 옵션 자체가 의미 없는 잡음.
- **방지 규칙**: 자동화된 동작은 옵션으로 노출하지 않는다. 호출자가 미세 제어가 필요하면 `set-phase-status` 또는 `fail-phase`를 명시적으로 사용.

### 17. cli.py의 advance_phase 코드 위치
- **실패 모드**: argparse handler 옆에 200L 가까이 차지하는 advance_phase 본문. cli.py의 700L 대부분이 이것.
- **방지 규칙**: argparse handler는 args 변환 + 핵심 함수 호출만. 복잡한 atomic composition은 자체 모듈(`phase_advance.py`)로.

### 18. 잠재 순환 import 위험
- **실패 모드**: state_store ↔ event_log가 한쪽 방향. 누군가 state_store에 logging을 추가하면 즉시 순환.
- **방지 규칙**: 두 모듈 docstring에 "state_store는 event_log를 import 하지 않는다" 명시. 추가 logging 필요시 콜백 주입.

### 19. `_circuit_breaker_tripped` BC alias 잡음
- **실패 모드**: 외부 호출자가 없는데 alias 유지. 코드 읽는 사람에게 "어떤 호환을 위한 것인가?" 의문 남김.
- **방지 규칙**: BC alias는 실제 외부 호출자가 있을 때만 둔다. 추측성 alias 금지.

### 20. in-tree runner들의 facade 우회
- **실패 모드**: sandbox_runner / snapshot_runner가 `from runtime import …` → cli.py 전체가 이미터로 로드. 불필요한 import 비용.
- **방지 규칙**: in-tree 코드는 facade를 사용하지 않는다. 직접 모듈 import. facade는 외부 호환 전용.

### 21. callable injection이 가짜 추상화
- **실패 모드**: gate_persistence가 `execute_gate`를 인자로 받음. 순환 회피 명분이었지만 gate_runner는 stdlib만 의존하여 직접 import해도 안전.
- **방지 규칙**: 회피할 의존이 실제로 없는데 추상화하지 않는다.

### 22. facade 호환 검증 부재
- **실패 모드**: `from runtime import X`가 깨져도 shell smoke에 안 잡힘.
- **방지 규칙**: `verify_spec_docs.py`의 `check_facade_exports()`가 모든 BC export를 import + identity 비교로 검증. CI/일상 검증에 포함.

## 다음 PR로 미룬 항목

### P2 #11 — runtime.py 모듈 분리 (완료)
- 1225L → 66L facade. 6개 모듈로 책임 분리:
  - `spec_loader.py` (80L) — pipeline.json load + 구조 검증
  - `state_store.py` (155L) — build-state.json I/O + atomic mutation + schema check
  - `event_log.py` (75L) — build-log.jsonl 이벤트 검증 + append
  - `transitions.py` (182L) — 전이 검증 + retry + circuit breaker (`circuit_breaker_tripped` 공개)
  - `gate_persistence.py` (99L) — gate 실행 결과 기록 + 자동 복구 helpers
  - `cli.py` (713L) — argparse + 모든 command handler + advance_phase
- runtime.py는 BC 호환을 위한 re-export facade로 축소. `from runtime import …` 그대로 동작 (sandbox_runner.py / snapshot_runner.py 영향 없음).
- 회귀 검증: verify_spec_docs PASS, smoke test로 init/advance/sandbox/snapshot/log/set-flag 모두 동일 동작 확인. circuit breaker trip 시나리오도 동일하게 거부.

## 교차 적용 규칙

- 새 gate check를 추가할 때:
  - 단순 파일/디렉토리/grep/state-eq 체크는 spec descriptor로 표현 (`type: file_exists` 등)
  - 절차적 체크(외부 명령 + 결과 파싱, checksum 등)만 gate_runner.GATE_CHECKS 등록
  - 새 procedural 추가 시 verify_spec_docs.py가 자동으로 누락 감지
- 새 build-log 이벤트를 추가할 때:
  - `spec/pipeline.json`의 `logEvents`에 먼저 등록 (required/optional 필드)
  - 이후 호출하는 코드를 작성. 잘못된 호출은 runtime이 거부.
- 새 phase agent를 추가할 때:
  - `spec/pipeline.json`의 `phases.<id>.agents` 배열에 등록
  - `fileOwnership.agents.<name>.writes` 선언
  - agent-sandbox.sh가 자동으로 enforce
