# Lessons — Autobot 구조 개선 (2026-04-27)

## 2026-08-16 RemoteXPC 관리자 background launch

- **실패 모드**: macOS 관리자 `do shell script` 안에서 `/usr/bin/nohup ... &`를 실행하자 `nohup: can't detach from console`로 종료되어, 인증은 성공했지만 tunnel 프로세스가 시작되지 않았다.
- **검출 신호**: `doctor`의 나머지 gate는 통과하고 `remotexpc-tunnel.log`에는 해당 한 줄만 반복되며 포트 42314 listener와 target UDID registry가 없다.
- **방지 규칙**: 완전 리다이렉트한 비대화형 background shell은 별도 `nohup`에 의존하지 않는다. 회귀 fixture는 PATH의 `nohup`이 실패하더라도 Appium tunnel launch가 실행되고 target registry readiness까지 확인해야 한다.

## 2026-08-16 관리형 Appium은 호출 shell보다 오래 살아야 한다

- **실패 모드**: `session` 명령 안에서 `nohup appium server ... &`로 시작한 서버가 WDA session 생성까지는 살아 있었지만 shell tool 종료와 함께 사라져, 다음 `screen` 명령이 포트 4723 연결 실패로 중지됐다.
- **검출 신호**: session 응답과 WDA build는 성공했는데 저장된 PID는 즉시 stale이고 Appium 로그에는 정상 종료 기록 없이 마지막 POST `/session`만 남았다.
- **방지 규칙**: 여러 skill 명령 사이에서 재사용할 관리형 서버는 호출 shell의 process group이 아니라 launchd가 소유하게 한다. PID뿐 아니라 launchctl label을 기록하고 `stop-server`가 그 job을 명시적으로 제거한다.

## 2026-08-15 장시간 전체 테스트 추적

- **실패 모드**: `tests/run_tests.sh`가 출력 없이 계속 실행 중인데 완료 여부를 확인하려고 같은 전체 suite를 두 번 더 시작했다.
- **검출 신호**: `ps`에서 같은 worktree의 `python3 -m unittest discover`가 서로 다른 PID로 3개 동시에 실행 중이었다.
- **방지 규칙**: 장시간 검증은 최초 `exec_command`가 반환한 session ID 하나만 `write_stdin`으로 추적한다. 요약 출력이 필요해도 새 suite를 시작하지 말고 기존 프로세스 상태를 먼저 조회한다.

## 2026-08-15 clone target app listing

- **실패 모드**: `devicectl device info apps`의 기본 목록을 전체 설치 앱 목록으로 해석하고, 다른 릴리스에서 본 Threads bundle ID를 고정해 WDA 대상 앱을 잘못 지정했다.
- **검출 신호**: 같은 UDID의 프로세스에는 `/Threads.app/Threads`가 있었지만 기본 앱 목록에는 없었고, `--include-all-apps --search Threads`에서 `com.burbn.barcelona`가 확인됐다. `com.instagram.barcelona` 세션은 `unknown`으로 거부됐다.
- **방지 규칙**: 항상 target UDID를 먼저 고정하고 그 UDID에서 `--include-all-apps`로 정확한 bundle ID를 조회한다. 대상 앱은 Release/App Store 설치여도 되며, Debug 서명이 필요한 것은 WDA runner뿐이다.

## 2026-08-15 WDA runner signature diagnosis

- **실패 모드**: Appium의 `xcodebuild code 65`를 대상 Threads 앱의 Debug/Release 제약으로 오인했다.
- **검출 신호**: 기기 상태·Developer Mode·provisioning profile은 유효했지만, WDA runner에 `codesign --verify --deep --strict`를 실행하면 `invalid Info.plist`가 났고, WDA scheme post-action의 재서명 단계에서 같은 이름의 개발 인증서가 2개 발견됐다. SHA-1 인증서를 명시해 생성된 WDA 앱을 재서명하면 설치는 통과했다.
- **방지 규칙**: 대상 앱 바인딩과 WDA helper 서명 진단을 분리한다. `0xe8008001`이면 Appium 로그와 WDA 산출물 서명을 먼저 검사하고, 원본 앱에 Debug 빌드를 요구하지 않는다.

## 2026-08-15 clone swipe fixture

- **실패 모드**: `device_wda.sh`를 임시 디렉터리에 복사해 swipe 테스트를 만들었지만, 스크립트가 `_HERE/device_a11y.py`를 실행하므로 settle 시그니처/노드키 계산이 조용히 실패했다.
- **검출 신호**: HTTP fixture와 명령은 성공했는데 flow 이벤트가 `from=?`, `to=?`, `changed=false`로 기록되고 stderr에 임시 경로의 `device_a11y.py` 미존재가 남는다.
- **방지 규칙**: 스크립트를 임시 경로에서 source하는 테스트는 인접 helper 스크립트·상대 경로·환경 변수를 함께 재현하고, 액션 성공뿐 아니라 flow 이벤트의 식별자/changed 값까지 assertion한다.

## 2026-08-15 clone workspace test file

- **실패 모드**: 패치 결과가 성공으로 반환됐지만 새 회귀 테스트 파일이 worktree에 존재하지 않아 테스트 수집 단계에서 import 오류가 났다.
- **검출 신호**: `ModuleNotFoundError: No module named 'tests.test_clone_workspace'` 및 `git status --short`에 테스트 파일이 나타나지 않음.
- **방지 규칙**: 새 파일을 추가한 뒤 대상 경로·git status를 즉시 확인하고, 테스트 실행 전 import 가능한지 확인한다.

## 2026-07-24 리뷰 수정

### 표준 테스트 러너 우선
- **실패 모드**: `pytest`를 직접 호출하면 테스트가 `from conftest import ...`를 해석하지 못해 수집 단계에서 실패한다.
- **검출 신호**: `ModuleNotFoundError: No module named 'conftest'`.
- **방지 규칙**: 이 저장소의 회귀 검증은 `bash tests/run_tests.sh`를 우선 사용하고, 대상 테스트만 실행할 때도 `PYTHONPATH=tests python3 -m unittest ...`를 사용한다.

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
- **실패 모드**: `mvp.md`/`resume.md`의 일반 호출은 `--increment-retry` 없이 `advance-phase --phase N`. gate fail 시 phase status는 `failed`로 가지만 retryCount는 0 유지 → maxRetry/circuitBreaker 둘 다 무력화.
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

## dogfood에서 발견 (2026-05-31)

### 23. agent `tools:` allowlist가 본문 지시와 모순 → 조용한 CLI fallback 강제
- **실패 모드**: `ux-designer.md` 본문은 `mcp__stitch__*` MCP 도구를 primary, `npx @_davideast/stitch-mcp` 를 "MCP 불가 시 fallback" 으로 지시. 그러나 frontmatter `tools: Read, Write, Bash, Glob, Grep` 가 MCP 도구를 미부여 → 에이전트가 MCP를 *한 번도* 호출 못 하고 매 빌드 Bash→npx 로 강제. Stitch MCP 서버가 연결돼 있어도 동일. 사용자가 "왜 npx 로 도느냐" 로 발견.
- **검출 신호**: "primary 경로가 한 번도 안 잡히고 항상 fallback". 도구 목록(`tools:`)에 본문이 부르는 도구가 없음.
- **방지 규칙**: 에이전트 본문이 호출하라고 지시하는 모든 도구는 `tools:` 에 부여돼야 한다. MCP 도구는 `mcp__<server>__<tool>` **전체 이름**으로 나열(와일드카드 미지원). `tools:` 생략 시 전체 상속이지만 최소권한이 깨지므로 명시 부여 선호. 플러그인 에이전트는 `mcpServers`/`hooks`/`permissionMode` frontmatter 무시됨 — `tools:` 만이 MCP grant 경로.
- **회귀 가드**: `tests/test_agent_mcp_tool_grants.py` — `tools:` 선언 에이전트는 본문 참조 `mcp__…` 도구를 전부 grant (일반 규칙, 미래 에이전트도 보호).

### 24. 품질 강화 제안이 기본 자율 완주 경로를 깨는 프레이밍 오류
- **실패 모드**: Autobot 평가에서 비결정적 critique / visual judge / P1 warning 을 기본 `/autobot:mvp` 경로의 hard-fail 또는 자동 재작업 루프로 올리자고 제안하면, "질문 없이 끝까지 빌드"라는 시스템 정체성과 충돌한다. 과거 visual judge 는 false-positive 가 circuit breaker 를 태우지 않도록 hard-fail 에서 DEGRADED-only 로 이미 후퇴했다.
- **검출 신호**: `scripts/gate_checks/build.py` 의 visual judge 주석처럼, hard-fail 이 Phase 5 retryCount 증가와 global circuit breaker trip 으로 이어져 자율 빌드를 멈춘다는 명시적 설계 근거가 있는데도 이를 무시한 우선순위 제안.
- **방지 규칙**: 기본 경로는 자율 완주를 보존한다. 비결정적·미보정 품질 신호는 기본 경로에서 DEGRADED/reporting 으로 제한하고, 엄격화는 `--quality=max` 같은 opt-in 모드에 격리한다. 자동 재실행은 quality-max 에서도 1회 제한 + DEGRADED fallback 으로 circuit breaker 를 보호한다.

## 전체 감사에서 발견 (2026-07-12)

### 25. 존재한 적 없는 CLI 플래그가 "성공 연극"에 가려짐
- **실패 모드**: `register-app.sh` 의 `fastlane produce create --api_key_path` 는 produce 에 존재한 적 없는 옵션 (produce 는 Apple ID 세션 전용 — 앱 생성은 공개 ASC API 에 endpoint 자체가 없음). 결정론적 경로는 항상 exit 4 로 죽었지만, 에이전트의 임기응변 + 과거 사람이 만든 spaceship 세션 잔광으로 전체 실행은 "성공"해 보였다. status JSON 스키마가 스크립트의 write_status 와 다른 것(에이전트 수기 작성)이 결정적 증거였다.
- **검출 신호**: (a) 결정적 스크립트가 항상 실패하는데 상위 플로우는 성공 (b) 산출물 스키마가 스크립트 출력과 불일치 (c) 성공 시각과 인간 로그인 아티팩트(쿠키 mtime)의 일치.
- **방지 규칙**: 외부 도구 호출 스크립트는 dry-run 이 아니라 **실제 플래그 집합을 도구의 --help/소스에 대조**하는 스모크를 갖춘다. 단계가 성공하면 "의도된 경로로 성공했는지"(스크립트가 쓴 status 파일인지)까지 확인한다.

### 26. env 변수 strip 만으로는 테스트 격리가 안 됨 — 스크립트가 사용자 전역 설정을 재로드
- **실패 모드**: `test_app_register.py` 가 ASC env 3종을 지웠지만 스크립트가 `~/.autobot/.env` 를 소스해 실 자격증명으로 진짜 fastlane 을 호출. 같은 클래스로 테스트 스위트가 실 `~/.config/autobot/learnings.json` 을 오염시킨 사례도 이번 감사에서 확인 (WS3).
- **방지 규칙**: 사용자 전역 설정을 self-load 하는 스크립트의 테스트는 env strip 이 아니라 **로드 경로 자체를 샌드박스** (`AUTOBOT_CONFIG_DIR`/`XDG_CONFIG_HOME`/`HOME`/cwd 를 임시 디렉토리로). 이중 방어선: 스크립트 쪽에도 publish 차단 env 가드.

### 27. 레퍼런스 스니펫의 비컴파일 API 는 매 빌드 build-fix 예산을 태움
- **실패 모드**: `references/ios-ux-style.md` 등 권위 레퍼런스가 실존하지 않는 Liquid Glass API(`.buttonStyle(.liquidGlass)`, `.glassEffect(tint:)`)를 예시로 제공 → 에이전트가 그대로 생성 → 매 빌드 컴파일 에러 → buildFixLoop 소모.
- **방지 규칙**: 레퍼런스에 넣는 코드 스니펫은 `swiftc -typecheck` (실제 SDK 대상) 로 컴파일 검증 후 수록한다. good/bad 쌍으로 검증해 정정 방향도 확인 (0.11.3 에서 `.buttonStyle(.glass)` / `.glassEffect(.regular.tint(...))` 로 정정, 실컴파일 확인 완료).

## 모델 성능 향상 대응 감사에서 발견 (2026-07-15)

### 28. 같은 lock 파일에 서로 다른 포맷을 쓰면 잠금이 아니라 clobber 프로토콜이 됨
- **실패 모드**: `build_lock.py`는 `.autobot/build.lock`에 JSON을 atomic write하지만 `resume.md`는 같은 파일을 raw PID로 읽고 썼다. 양쪽이 상대 형식을 stale로 판단해 살아 있는 잠금을 삭제할 수 있었다.
- **검출 신호**: 하나의 상태 파일을 읽고 쓰는 구현이 둘 이상이고 serialization 형식이 다름. `transitions.py` 주석에도 우회 사유가 새어 나옴.
- **방지 규칙**: 잠금의 acquire/status/release는 `pipeline.sh build-lock`만 사용한다. command/skill prose에서 lock 파일을 직접 `cat`, `echo`, `rm`하지 않는다.

### 29. 모델 핀과 복제 프롬프트는 시간이 지나면 품질 상한과 충돌 지시가 됨
- **실패 모드**: agent frontmatter의 `opus`/`sonnet`, 별도 dispatch 문서의 버전 고정 모델, Team/background 경로, agent 본문을 복제한 prompt template가 동시에 존재했다. 최신 host 기본 모델을 상속하지 못하고 어느 절차가 우선인지 흔들렸다.
- **검출 신호**: 같은 agent의 모델/도구/절차가 두 파일 이상에 선언되거나, allowed-tools에 없는 orchestration primitive가 예시로 등장함.
- **방지 규칙**: 모델은 측정된 중앙 정책이 없으면 host를 상속한다. 정적 역할은 `agents/*.md`, 실행 제약은 spec/context-pack, 학습은 learning-bootstrap 한 곳씩만 소유한다.

### 30. 출하 gate는 command마다 미리 돌리지 말고 비가역 경계에서 한 번 fresh 검증
- **실패 모드**: testflight/app-review command가 Gate 5→6을 실행한 뒤 persisted state를 다시 읽고, archive가 곧바로 `preflight-ship`으로 같은 고비용 gate를 재실행했다. 느리고 첫 판정 경로는 stale evidence 해석 위험도 있었다.
- **검출 신호**: 동일 gate id가 하나의 출하 흐름에서 여러 진입점에 직접 호출되고, 뒤쪽 경계에 이미 더 강한 fresh-result 판정이 있음.
- **방지 규칙**: anti-laundering은 실제 artifact 생성 직전의 archive boundary가 `preflight-ship`으로 한 번 집행한다. 상위 command는 그 실패를 전파만 한다.

### 31. 짧은 CLI PID와 buildId만으로는 장기 실행 lock 소유자를 식별할 수 없음
- **실패 모드**: one-shot CLI PID는 획득 직후 죽고, 같은 buildId를 무조건 허용하면 동시에 실행된 두 resume가 서로를 정상 재개로 오인한다.
- **검출 신호**: acquire 직후 별도 status가 stale이거나, 살아 있는 같은-build lock을 별도 의사표시 없이 덮어쓸 수 있음.
- **방지 규칙**: lock은 CLI 수명과 독립적인 lease를 사용하고, 같은 buildId도 기본 차단한다. resume만 명시적 takeover를 요청하며 내부 병렬 writer는 별도 state flock으로 직렬화한다.

### 32. 재개 스킵과 릴리스 스킵은 timestamp가 아니라 동일 artifact identity로 판정
- **실패 모드**: Swift 파일 mtime보다 upload-status가 최신이라는 이유로 resource/project/version이 바뀐 바이너리를 이미 업로드됐다고 오인한다.
- **검출 신호**: status에 buildId, bundle/version/build, 입력 hash, archive/IPA digest가 없거나 producer/consumer 키 이름이 다름.
- **방지 규칙**: build→runtime→archive→IPA→upload 전체가 canonical identity와 digest를 기록하고, controller는 모든 값이 현재 build와 일치할 때만 완료를 재사용한다.

### 33. spec의 복구 정책 필드는 실행기가 각 분기를 실제로 소비해야 함
- **실패 모드**: `saveBeforeFirstAttempt`, `saveAfterEachAttempt`, `rollbackOnSignatureRepeat`를 선언했지만 실행 코드가 없어 반복 오류에서 오래된 phase snapshot으로만 복원한다.
- **검출 신호**: 정책 키 검색 결과가 spec과 문서에만 있고 runtime consumer/test가 없음.
- **방지 규칙**: 선언된 각 boolean과 maxAttempts를 checkpoint save/restore 실행기가 검증하고, disabled 분기와 signature-repeat 복원을 회귀 테스트한다.

### 34. 표적 unittest도 저장소의 import bootstrap을 그대로 사용해야 함
- **실패 모드**: `python3 -m unittest tests.test_*`로 표적 검증을 실행했지만 테스트가 기대하는 `tests/conftest.py`가 import 경로에 없어 9개 모듈이 수집 단계에서 실패했다.
- **검출 신호**: 테스트 본문 실행 전 `ModuleNotFoundError: conftest`가 반복되고 실제 assertion은 하나도 수행되지 않음.
- **방지 규칙**: 이 저장소의 개별 unittest는 `PYTHONPATH=tests:scripts python3 -m unittest test_<name>`로 실행하고, 최종 검증은 canonical `bash tests/run_tests.sh`를 사용한다.

### 35. lease 소유권은 buildId가 아니라 세대 token으로 증명
- **실패 모드**: 같은 buildId의 이전 실행이 release하면 뒤에 takeover한 새 실행의 lock까지 지울 수 있다.
- **검출 신호**: acquire/takeover는 가능하지만 release가 현재 lock 세대를 비교하지 않거나 buildId만 비교한다.
- **방지 규칙**: acquire마다 불투명 token을 발급하고 takeover와 release를 CAS로 집행한다. run-summary 같은 build-scoped 파일은 세대 소유권 증명이 아니며, token 없는 release는 만료 또는 명시적 force에만 허용한다.

### 36. 재개 가능한 외부 워크플로는 claim과 산출물 재검증이 함께 필요
- **실패 모드**: 병렬 App Review 실행이 같은 phase를 동시에 수행하고, 과거 완료 status가 현재 빌드·현재 파일과 달라도 재사용된다.
- **검출 신호**: `next`가 읽기만 하거나 완료 근거가 result 문자열뿐이고 build/artifact/content identity가 없다.
- **방지 규칙**: controller가 원자적으로 lease+claimToken을 발급하고 command는 `next → complete|fail → next` 순서를 지키며 token을 전달한다. 완료 evidence는 재개 때마다 현재 build와 content digest에 대조한다.

### 37. dotenv는 shell code가 아니라 제한된 설정 데이터
- **실패 모드**: `source`/`eval` 기반 loader가 임의 키와 command substitution을 받아 PATH, Python startup, shell option을 바꾸거나 명령을 실행한다.
- **검출 신호**: env 파일 한 줄이 quoting 없이 shell 평가되거나 허용 키 목록 없이 process environment에 주입된다.
- **방지 규칙**: 공용 parser가 명시적 release credential allowlist만 읽고 literal 값으로 반환한다. shell/Python 소비자는 같은 parser를 사용하며 악성 행 회귀 테스트를 둔다.

### 38. host 용량 probe는 CI 테스트의 숨은 전제면 안 됨
- **실패 모드**: 기능과 무관한 호스트 여유 공간이 1GB 아래로 내려가자 Phase 0 fixture가 실패해 수십 개 테스트가 연쇄 실패했다.
- **검출 신호**: 같은 assertion 이전의 공통 fixture에서 실제 디스크·장치·네트워크 probe가 실패한다.
- **방지 규칙**: production 기본 fail-fast는 유지하되 테스트 환경은 명시적 skip flag로 host-capacity probe를 격리하고 DEGRADED evidence를 남긴다.

### 39. 새 CLI 출력 분기는 성공 경로를 직접 실행해야 함
- **실패 모드**: build-lock JSON 출력 옵션과 테스트를 함께 추가했지만 구현 모듈의 `json` import가 빠져 전체 스위트에서만 NameError가 났다.
- **검출 신호**: parser/문자열 계약 테스트는 통과하지만 새 옵션을 실제 호출하는 최초 회귀 테스트가 빈 stdout과 traceback을 낸다.
- **방지 규칙**: CLI 옵션 추가 시 subprocess로 그 옵션의 성공 경로를 직접 실행하고 stdout을 실제 소비자와 같은 방식으로 파싱한다.

### 40. 로컬에서 통과해도 GitHub Actions에서 3주+ 상시 적색일 수 있다 — 푸시 후 CI 결과를 확인해야 함
- **실패 모드**: `ci.yml`의 첫 스텝이 `from scripts import spec_loader` 절대 임포트를 시도했는데, `scripts/`가 `__init__.py` 없는 네임스페이스 패키지라 GitHub 실행 환경(레포 루트 cwd)에서는 `ModuleNotFoundError`로 즉사했다. 로컬에서 `python3 scripts/verify_spec_docs.py`처럼 스크립트를 직접 실행하면 `scripts/`가 `sys.path[0]`에 올라 문제가 재현되지 않아, 이 스텝은 도입 커밋부터 9회 연속(3주+) 실패하면서도 아무도 눈치채지 못했다.
- **검출 신호**: `gh run list --workflow=<name>` 최근 실행이 전부 실패, 특히 소요 시간이 균일하게 짧으면(같은 스텝에서 매번 즉사) 강한 신호.
- **방지 규칙**: CI 워크플로를 새로 추가하거나 수정해 푸시/PR을 올렸으면 로컬 통과만으로 끝내지 말고 `gh run list`/`gh run view`로 실제 GitHub 실행 결과(특히 스텝별 소요 시간과 로그)를 최소 1회 확인한다. 로컬 재현 명령은 CI의 cwd·sys.path·환경변수와 다를 수 있다는 전제를 깔고, 가능하면 CI가 실제로 실행하는 명령 그대로(`python3 scripts/foo.py`, `python3 -c "..."` 등)를 회귀 테스트로 subprocess 실행해 고정한다.

## 2026-07-17 — screen-interview 독푸딩: 헤딩 중복 생성
- 실패 모드: 라운드 기록을 Edit 로 append 하다가 "미결/후속" 섹션을 두 번 생성 (편집 앵커가 결정 로그 끝이어서 기존 섹션 위치를 지나침).
- 감지 신호: 템플릿 계약("섹션 이름은 계약이다") 위반 — 같은 H2 가 파일에 2개.
- 예방 규칙: SKILL 철칙 2 에 "같은 헤딩을 두 번 만들지 않는다 — 기존 섹션에 항목 추가" 명문화 (반영 완료).

## 2026-07-25 — clone 자율 탐험: 가정한 데이터 형태로 만든 가드는 실제 덤프에 뚫린다
- 실패 모드: `candidates` 의 모달 감지를 "요소 role 에 alert/sheet 포함"이라는 *가정*으로 구현하고 문서에 "기계적으로 강제됨"으로 못박았다. 실제 `idb ui describe-all` 이 뱉은 ATT 권한 다이얼로그는 빈 라벨 `AXApplication` 아래 `AXStaticText`/`AXButton` 만 있는 평평한 트리로, `AXAlert` 가 없다 → 가드가 침묵하고 "Allow" 가 정상 탭 후보로 출력됐다.
- 검출 신호: 자체 fixture 테스트는 전부 green 인데 **도구의 실제 출력 1건**에 처음 돌려보자 즉시 뚫림. fixture 를 내가 만든 스키마 가정으로 썼다는 게 근본 원인.
- 예방 규칙: 외부 도구 출력을 파싱하는 가드/파서는 **문서에 "강제된다"고 쓰기 전에 실제 덤프 1건 이상으로 검증**하고, 그 실물 형태를 fixture 로 회귀에 고정한다. 감지 신호는 구조(role)보다 어휘(라벨)가 안정적일 때가 많다 — 오탐이 안전한 방향(중지)이면 어휘 매칭을 1급으로 둔다.

## 2026-07-25 — fb-idb 의 UI 조작·접근성은 시뮬레이터 전용 (실기기 자율 탐험 불가)
- 실패 모드: `/autobot:clone` 문서가 작성 시점부터 "연결된 iPhone 에서 `idb ui describe-all` 로 구조 캡처, `ui tap` 으로 이동"을 1급 경로로 규정했으나, 실기기에서 실행하면 `Target doesn't conform to FBAccessibilityCommands protocol` / `...FBSimulatorLifecycleCommands protocol` 로 거부된다. 즉 문서가 존재하지 않는 능력을 전제로 쓰여 있었다.
- 검출 신호: 실기기 udid 로 `idb ui describe-all` → 프로토콜 미준수 메시지. `idb screenshot` 도 iOS 26 기기에서 `SecureStartService of com.apple.mobile.screenshotr Failed with 0xe8000022`. 같은 명령이 시뮬레이터 udid 에서는 정상 동작(대조군이 결정적). companion 을 새로 띄워 붙여도 동일 — 설정 문제가 아니다.
- 예방 규칙: 외부 CLI 의 능력을 SKILL 에 1급 경로로 규정하기 전에 **대상 환경(실기기/시뮬레이터)에서 그 서브커맨드를 1회 실행**해 확인한다. 실기기 스크린샷은 `xcrun devicectl device screenshot`(= `device_capture.sh shot`)로 가능하지만 **탭은 불가** — 실기기 자율 조작은 WebDriverAgent/XCUITest 러너 설치가 전제다.

## 2026-07-25 — 실기기 자율 조작의 유일 경로는 WebDriverAgent (+ UI 자동화 토글)
- 실패 모드: fb-idb 로 실기기를 조작할 수 없다는 걸 확인한 뒤 Appium/WDA 로 갈아탔으나, WDA 가 서명·빌드·설치·실행까지 모두 성공하고도 `Timed out while enabling automation mode` 로 죽어 `xcodebuild failed with code 65` 라는 **엉뚱한 상위 에러**만 노출됐다. 서명 문제로 오진하기 쉽다.
- 검출 신호: appium 을 `--log-level debug` + `appium:showXcodeLog=true` 로 직접 띄워야 원인 줄이 보인다. 상위 에러(code 65)만 보고 서명을 파면 시간을 버린다.
- 예방 규칙: 실기기 XCUITest 자동화는 **설정 > 개발자 > UI 자동화(Enable UI Automation)** 가 켜져 있어야 한다 — 개발자 모드·Trust 와 별개의 세 번째 토글이다. 그리고 외부 도구 실패를 진단할 때는 **로그를 내가 제어하는 인스턴스**에서 재현한다(남이 띄운 서버의 상위 에러 문자열로는 원인을 못 본다).

## 2026-07-25 — 에이전트 규율은 산문으로 두면 뚫린다 (실행 중 자기 위반)
- 실패 모드: `/autobot:clone` 자율 루프를 실기기에서 돌리다가, 뒤로가기 후 화면 서명이 기대값과 달랐는데도 **낡은 트리의 좌표로 다음 탭을 이어 쳤다.** SKILL 의 "예상과 다른 화면이면 멈춘다" STOP 규칙을 스스로 위반했고, 탐험이 대상 앱 밖으로 나가 다른 앱의 ATT 다이얼로그 앞까지 갔다.
- 검출 신호: 캡처한 sig 가 기대한 sig 와 불일치. 단, 이 신호를 **읽고도 무시**할 수 있다는 게 문제의 핵심 — 문서 규칙은 위반해도 아무 일이 일어나지 않는다.
- 예방 규칙: 안전 규율은 **실행 경로에 강제 장치를 둔다.** 좌표 탭은 그 좌표가 나온 트리를 필수 인자로 받고, ①후보 여부 ②라이브 화면 서명 일치를 검사해 불일치면 거부한다. 같은 사건에서 **코드로 만든 가드(모달 시 후보 0개)는 버텼고 문서로 만든 가드(STOP 조건)는 뚫렸다** — 이 대비가 규칙이 어디에 있어야 하는지를 말해준다.

## 2026-07-25 — 스킬이 약속한 능력은 스크립트에 실재해야 한다 (두 번째 재발)
- 실패 모드: 신규 `/autobot:clone` SKILL 이 "요소 계층에서 스택 방향과 정렬을 추론한다"고 썼는데, 측정 스크립트는 접근성 트리를 **평평한 리스트로 flatten** 해 계층을 버리고 있었다. 같은 세션에서 "문서가 존재하지 않는 능력을 전제" 하는 실패를 fb-idb 건으로 이미 겪고도 재발했다.
- 검출 신호: 스킬을 실제로 완주해보니 산출 JSON 에 `layout` 이 없었다. 문서만 읽으면 있는 것처럼 보인다.
- 예방 규칙: SKILL 에 능력을 쓸 때는 **그 문장을 만족하는 스크립트 출력이 실재하는지 한 번 실행해 확인**한다. 특히 새 스킬을 쓸 때는 참조하는 스크립트를 문서와 같은 커밋에서 만들고, 산출물 예시를 실제 데이터로 한 번 뽑아본다.

## 2026-07-25 — 2점 색 샘플링은 컨트롤의 fill 을 놓친다
- 실패 모드: 요소 색을 모서리(background)와 중심(center) 두 점으로만 샘플링해, 원형 FAB 의 실제 파란색을 놓쳤다 — 모서리는 뒤에 깔린 캡슐, 중심은 흰 `+` 글리프였고 정작 fill 은 그 사이 링에 있었다. 재현본의 버튼이 회색으로 나왔다.
- 검출 신호: 대조 이미지에서 색이 다름. 측정 JSON 만 보면 "색을 측정했다"고 착각한다.
- 예방 규칙: 컨트롤은 **내부 격자의 최빈값**을 fill 로 쓴다(텍스트는 반대로 배경 대비 최대값이 ink). 2점 샘플링은 단색 사각형에만 맞는 가정이다.

## 2026-07-25 — 화면 크롬을 안 걸러낸 레이아웃 추론은 숫자만 그럴듯하다
- 실패 모드: `/autobot:clone` 을 실기기(Apple 저널)에서 완주하니 루트 레이아웃이 `vstack spacing 147` 로 나왔다. 실제 화면은 카드 4장이 16pt·10pt 간격인 단순 세로 스택이다. 오염원 셋: ①스크롤 막대(라벨 있음, 전체 높이) ②그 자식인 3pt 인디케이터(라벨 없음) ③WDA 가 창을 둘로 보고해 생긴 모든 요소의 완전 중복. 여기에 카드 자신의 배경이 형제로 잡혀 한 줄의 간격이 `-343` 으로 나왔다.
- 검출 신호: 산출 JSON 의 `gaps` 에 화면 높이급 음수(-664, -395)가 섞임. 스크립트는 성공(exit 0)하고 fixture 테스트도 전부 green — **실기기 1회 실행**에서만 드러났다.
- 예방 규칙: 접근성 트리를 재현에 쓰기 전에 크롬을 걸러낸다. 걸러내는 가드에는 **순서가 있다** — 중복 제거를 크롬 제거보다 먼저 두면, 중복된 스크롤 막대가 "중복" 으로 처리되며 그 자식이 루트로 승격돼 가드가 침묵한다. 크롬은 자식까지 함께 버리고(래퍼와 반대다: 래퍼의 자식은 살아남은 조상에 재부착), 스택 축은 양수 간격 합이 아니라 **겹침**으로 판정한다(6pt 겹친 두 줄은 zstack 이 아니다).

## 2026-07-25 — 검증 단계에 실행 경로가 없으면 그 철칙은 장식이다
- 실패 모드: `autobot-clone-app` SKILL 은 "대조 이미지 없이 완료 선언 금지"를 철칙 4 로 두고 Step 6 에서 "생성한 SwiftUI 를 시뮬레이터에서 렌더" 하라고 했지만, Step 5 산출물은 앱 진입점도 프로젝트 파일도 없는 낱개 `.swift` 였다. 낱개 뷰를 시뮬레이터 스크린샷까지 가져갈 경로가 레포에 없었다 — 즉 철칙을 지킬 방법이 없었다.
- 검출 신호: 스킬을 완주하려다 Step 6 에서 멈춤. 문서만 읽으면 "렌더하면 된다"로 보인다.
- 예방 규칙: 완료를 막는 철칙(gate)을 쓸 때는 **그 게이트를 통과시키는 실행 경로가 레포에 실재하는지** 같은 커밋에서 확인한다. 여기서는 `scripts/device_render.sh` 로 닫았다 — 프로젝트 파일 없이 `swiftc` → `.app` → `simctl install/launch/screenshot`. 새 의존성 0.

## 2026-07-25 — clone 의 지배적 실패 모드는 우리가 안 보던 쪽이었다 (외부 선행연구 대조)
- 배경: `/autobot:clone` 을 실기기에서 완주한 뒤 같은 문제를 푸는 외부 사례를 조사했다. 학계에는 10년 넘은 계보가 있다 — REMAUI(ASE 2015, 스크린샷만으로 CV+OCR 역공학), Screen Parsing(UIST 2021, 계층 예측), DCGen(arXiv 2406.16386), LayoutCoder(arXiv 2506.10376).
- 배움 1 (검증 대상이 틀렸다): DCGen 이 분류한 실패 1,699건 중 **요소 누락 85.3%**, 배치 오류 12.7%, 왜곡(색·크기) 2.6%. 우리 SKILL 의 검증은 색·간격 정확도(=2.6% 구간)에 집중돼 있었고, 정작 지배적인 누락을 세는 절차가 없었다. Step 6 에 "요소 표를 하나씩 짚어 센다"를 추가했다. 크롬을 걸러내는 우리 측정 단계는 콘텐츠를 함께 버릴 위험이 있어 더 그렇다.
- 배움 2 (평가 지표): 이 분야는 픽셀 동일이 아니라 **인지적 유사도**(CLIP score)로 평가한다. 사용자가 같은 날 내린 재정의("픽셀 단위 복제 불필요, 레이아웃·룩앤필·기능")와 정확히 같은 방향이다. 우리 `device_compare.py` 는 나란히 붙이기만 하고 정량 지표가 없다 — 후속.
- 배움 3 (우리 강점): 이들은 전부 **비트맵만** 갖고 시작해 텍스트·컨테이너 경계를 추론하느라 OCR 오탐과 싸운다. 우리는 접근성 트리로 프레임을 실측한다 — 그들이 가장 어려워하는 부분이 우리에겐 공짜다. 반대로 그들이 쓰는 **시각적 분할선(projection) 기반 분해**는 우리가 안 쓰는 신호이고, 접근성 트리의 계층이 시각적 계층과 어긋날 때(오늘 겪은 카드 배경·스크롤 막대가 형제로 잡히는 문제) 보완 신호가 된다.
- Claude Code 생태계: 시뮬레이터 조작 스킬(`conorluddy/ios-simulator-skill`)과 SwiftUI 작성 스킬은 여럿 있으나 **실기기 앱을 측정해 재현하는 스킬은 찾지 못했다.** 그 스킬의 "스크린샷을 리사이즈·압축하고 기본 출력을 3~5줄로 줄여 토큰을 아낀다"는 규약은 참고할 만하다.

## 2026-07-25 — 같은 "화면 정체성"을 두 목적에 겸용하면 한쪽이 반드시 깨진다
- 실패 모드(설계 단계에서 차단): flow 그래프의 노드를 기존 `sig`(라벨 집합 해시)로 세려 했다. `sig` 는 탭 가드용이라 라벨이 하나만 바뀌어도 달라진다 → 목록을 한 줄 스크롤할 때마다 새 노드가 생기고 **미방문 큐가 영원히 마르지 않는다.** 전수 탐험이 원리적으로 종료 불가가 된다.
- 검출 신호: "이 값을 다른 목적에도 쓰자"고 생각한 순간, 두 목적이 **민감도를 반대로 요구**하는지 본다. 탭 가드는 민감해야 하고(조금만 바뀌어도 낡은 좌표 거부), 그래프 노드는 둔감해야 한다(데이터가 바뀌어도 같은 화면). 반대 요구는 한 함수로 겸할 수 없다.
- 예방 규칙: 시그니처를 목적별로 나눈다 — `sig`(민감, 가드용) / `nodekey`(둔감, 구조 해시). 둔감함의 폭은 **무엇이 같은 화면이고 무엇이 다른 화면인지**를 기준으로 정한다: 스크롤은 흡수하되 빈 상태와 채워진 상태는 분리(재현할 레이아웃이 다르므로). 임계값은 실기기 캡처로 검증한다.

## 2026-07-25 — 비동기 UI 전이를 즉시 읽으면 모든 엣지가 "제자리"로 기록된다
- 실패 모드: `tap` 은 즉시 반환하고 화면은 애니메이션 중이다. 탭 직후 화면 서명을 읽어 도착지로 기록하면 **출발 화면이 도착지가 된다** — flow 그래프의 모든 엣지가 자기 자신을 가리킨다. 첫 독푸딩에서 수동으로 `sleep 1.5` 를 넣어야 했던 그 지연이 원인이었고, 자동화할 때 그 사실을 잊으면 그래프가 통째로 무의미해진다.
- 검출 신호: 수동 실행에서 `sleep` 을 넣어야 동작했던 지점. 그 sleep 은 임시방편이 아니라 **비동기 경계의 신호**다 — 자동화 코드에는 폴링으로 들어가야 한다.
- 예방 규칙: 외부 UI 상태 전이는 기대 조건이 만족될 때까지 폴링하고, 타임아웃 시 "변화 없음"을 **1급 데이터로 기록**한다(에러가 아니다 — "이 버튼은 아무 데도 안 간다"는 사실이다). 손으로 넣었던 sleep 은 전부 폴링 후보로 본다.

## 2026-07-25 — 스킬을 만들고 그 스킬을 완주하지 않은 채 "완료"를 보고했다
- 실패 모드: `/autobot:clone` 에 전수 탐험을 신설하고, 정작 나는 후보 25개 중 2개만 탭한 뒤 "3화면 완주"로 보고했다. 사용자가 flow 맵을 열고 **"일기 생성화면은 없는데, 왜 놓친거야?"** 로 즉시 잡아냈다. 생성 화면 후보 2개(`새로운 일기`, `입력 항목 생성`)는 미탐험 큐에 그대로 있었다 — 도구가 놓친 게 아니라 내가 가지 않았다.
- 검출 신호: 내가 "파이프라인이 동작하는지 확인했다"고 말하는 순간. 그건 **도구 검증**이고 스킬 완주가 아니다. 커버리지 지표(2/25)를 함께 보고했지만, 지표를 냈다는 사실이 "규정대로 했다"를 대체하지 못한다.
- 예방 규칙: 새 절차를 만든 커밋에서는 **그 절차를 끝까지 한 번 돌린다.** 도구 단위 검증으로 끝내면, 절차가 요구하는 것과 내가 한 것의 차이가 산출물에 그대로 남는다. 부분 실행으로 멈춰야 한다면 "파이프라인 검증만 했고 전수 탐험은 하지 않았다"를 결론 첫 줄에 쓴다 — 커버리지 숫자를 본문에 묻어두는 것으로 대체하지 않는다.
- 부수 성과: 이어서 실제로 탐험하니 역기획 해석 하나가 **뒤집혔다** — 홈의 목록 행을 "항목 목록 진입점"으로 읽었는데, 전이를 따라가니 그건 **저널(컨테이너)** 이고 계층이 홈 → 저널 → 항목 3단이었다. 전수 탐험이 왜 재현보다 먼저인지를 실증한 사례.

## 2026-07-25 — 구조 시그니처에 컨테이너를 세면 래퍼 요동으로 노드가 분열한다
- 실패 모드: 같은 빈 목록 화면을 몇 분 간격으로 두 번 캡처했더니 `nodekey` 가 갈렸다. 한 덤프는 생성 버튼을 `AXToolbar` 아래에, 다른 덤프는 `AXOther` 아래에 뒀다 — 콘텐츠는 동일한데 래퍼만 달랐다. flow 그래프에 유령 노드가 생기고 커버리지 분모가 부풀었다(82 → 실제 5화면).
- 검출 신호: 같은 화면을 다시 캡처했을 때 키가 다름. shape 문자열을 나란히 놓으면 차이가 컨테이너 role 하나뿐인 게 보인다.
- 예방 규칙: 구조 해시는 **콘텐츠 role 만** 센다 — 컨테이너(`CONTAINERS`)와 `AXOther`·`AXKey`(키보드는 애니메이션으로 들락거린다)를 제외한다. 접근성 트리의 계층은 같은 화면에서도 재구성되므로 "무엇이 담겨 있나"는 안정적이고 "무엇이 감싸고 있나"는 아니다.

## 2026-07-26 — SessionStart 훅은 "모든 디렉토리"에서 돈다 — 쓰기는 프로젝트 판별 뒤에
- 실패 모드: `load-learnings.sh` 가 전역 학습을 시딩하며 `.autobot/` 을 무조건 mkdir 했다. 훅은 사용자가 여는 **모든 레포의 모든 세션**에서 실행되므로, Autobot 과 무관한 `AXI-Homepage` 등 14곳에 껍데기 폴더가 남았다. 사용자가 "왜 이런 폴더를 남기냐"로 발견.
- 검출 신호: 훅(또는 어떤 전역 자동 실행 경로)에서 **파일을 쓰는 코드**를 볼 때. "이 디렉토리가 우리 프로젝트인가"를 먼저 묻지 않으면, 쓰기 자체가 그 판별을 참으로 만들어 버린다(`mkdir` 이 곧 "Autobot 프로젝트임"의 증거가 됨).
- 예방 규칙: 훅의 쓰기는 **이미 존재하는 프로젝트 마커**로 게이트하고, 마커를 처음 만드는 일(최초 시딩)은 마커를 만드는 명령(`init-build`)에 둔다. 읽기는 자유, 쓰기는 게이트.
- 부수 교훈(advisor 지적으로 잡음): 시딩을 옮길 때 **그 산출물을 소비 가능한 형태로 만드는 단계(렌더)** 를 같이 옮겨야 한다. `learnings.json` 만 옮기고 `active-learnings.md` 렌더를 훅에 남겨두면, 훅은 `.autobot/` 이 없던 SessionStart 에 이미 지나갔으므로 **첫 빌드 전체가 학습 없이** 돈다. "데이터를 옮겼다"와 "그 데이터가 읽히는 경로를 옮겼다"는 다르다.

## 2026-08-15 — clone 개선 전에 복제 목표를 일반 flow 감사로 좁혀버렸다
- 실패 모드: 사용자가 말한 `clone`을 Appium 기반 타깃 앱 복제라는 제품 목표로 먼저 고정하지 않고, flow 로그의 완료 판정과 커버리지 집계 개선을 주된 작업으로 착수했다.
- 검출 신호: 사용자가 "목표는 Appium을 이용해 타겟이 되는 앱을 그대로 복사"라고 다시 범위를 명시했다.
- 예방 규칙: 스킬 개선에서는 먼저 대상 도구(Appium), 복제 대상(타깃 앱), 결과물(동일 화면·상태·전이)을 한 문장으로 고정하고, 보조 검증 개선은 그 계약을 닫는 범위 안에서만 진행한다.

## 2026-08-15 — clone의 중심 도구를 Appium으로 계속 고정한다
- 실패 모드: 온라인 자동화 사례를 조사하면서 일반 모바일 자동화·시각 검증 패턴이 목표처럼 보일 수 있었다.
- 검출 신호: 사용자가 "목표는 Appium"이라고 다시 강조했다.
- 예방 규칙: `/autobot:clone`의 모든 실행 절차와 acceptance evidence는 Appium 세션, WDA 접근성 트리, Appium 입력/전이 결과를 기준으로 설명하고, 다른 도구는 보조 아이디어로만 취급한다.

## 2026-08-15 — WDA의 서명 후 post-action은 전역 Appium 설치와 분리한다
- 실패 모드: 대상 Threads bundle ID는 정확했지만 WDA 설치가 `0xe8008001`/`invalid Info.plist`로 실패했다. Appium WDA scheme의 icon post-action이 이미 서명된 Runner.app을 다시 서명했고, 키체인에 같은 표시명의 개발 인증서가 2개라 `codesign --sign "Apple Development"`가 모호해졌다.
- 검출 신호: `xcodebuild code 65`만으로는 원인이 숨겨졌고, `CLONE_WDA_DEBUG=1` 로그와 `codesign --verify --deep --strict --verbose=4`에서만 Runner.app 산출물 변조·서명 상태를 분리해 볼 수 있었다. 대상 앱의 Debug/Release 상태를 바꿔도 해결되지 않았다.
- 예방 규칙: clone 세션은 Appium 패키지의 WDA를 `.autobot/clone/wda`에 복사하고 서명 후 bundle을 변형하는 선택적 post-action을 no-op으로 격리한다. 전역 `~/.appium` 패키지를 패치하지 말고, 격리 경로·갱신 플래그·원본 비변경을 회귀 테스트로 고정한다.

## 2026-08-15 — 실측 좌표는 SwiftUI의 가변 레이아웃 오작동을 바로 드러낸다
- 실패 모드: 추천 화면의 콘텐츠를 intrinsic-height `VStack`으로 감싼 뒤 중앙 정렬해, 원본의 상단 시트가 생성본에서 화면 중앙에 떠 버렸다. 빌드와 렌더는 성공했지만 구조가 달랐다.
- 검출 신호: 원본 접근성 트리의 절대 프레임(`손잡이 y45`, 헤더 `y94`, 검색 `y168`, 행 `y214`, 하단 버튼 `y728`)과 대조 이미지의 시트 시작 위치가 달랐다.
- 예방 규칙: measured frame을 색·폰트에만 쓰지 말고 시트의 상단 고정점과 하단 여백에도 적용한다. 먼저 구조 차이를 없앤 뒤 색·모서리 같은 광택을 조정하고, 원본/생성본 대조 이미지를 남긴다.

## 2026-08-15 — clone 전용 빌드는 공통 scaffold의 불필요한 패키지를 의심한다
- 실패 모드: clone workspace를 기본 scaffold 그대로 빌드하자 사용하지 않는 로컬 디자인 시스템 패키지의 Swift 모듈 그래프가 디스크 압박(최종 0바이트) 상황에서 `Unable to resolve module dependency`와 `database or disk is full`을 연쇄시켰다. 최초 메시지만 보면 SwiftUI 코드 오류처럼 보였다.
- 검출 신호: `df -h`가 여유 117MiB였고, 로그 끝에 `No space left on device`가 있었다. 화면 소스에는 해당 패키지 import가 없었다.
- 예방 규칙: clone 산출물은 실제 생성 화면이 사용하는 의존성만 남긴다. 빌드 실패 시 마지막 오류보다 저장공간·패키지 그래프를 먼저 확인하고, 생성된 실패 DerivedData만 정리한 뒤 최소 타깃으로 재빌드한다.

## 2026-08-15 — 타사 자산 정책은 연구용과 배포용을 분리한다

- 실패 모드: 타사 앱의 원본 자산 사용을 일괄적으로 금지해, 사용자가 명시한 연구용 clone 범위까지 자리표시자로 제한했다.
- 검출 신호: 사용자가 연구용이며 자산 사용 책임을 부담한다고 범위를 다시 명시했다. 이때 정책 판단과 실제 기기에서 원본 번들에 접근할 수 있는 기술적 사실을 같은 문제로 취급하고 있었다.
- 예방 규칙: Step 0에서 `본인 앱`, `타사 연구 전용`, `타사 외부 공유·배포`를 분리한다. 연구 전용은 사용자 승인과 provenance manifest를 전제로 접근 가능한 파일·payload/export·공개 원본·화면 crop을 허용하되, 샌드박스·암호화·서명 경계는 우회하지 않는다. 배포 분기는 원본 자산 승계를 다시 심사한다.

## 2026-08-15 — tappable 후보 수는 안전성도 커버리지도 아니었다

- 실패 모드: clone 문서는 파괴적 라벨이 후보에서 제외된다고 했지만 실제 Threads frontier에는 `팔로우`, `모두 팔로우`, `추천 무시` 같은 계정 변경 동작과 키보드 키·FAQ 설명문이 함께 들어갔다. `6/59`의 분모는 실제 사용자 행동 수가 아니라 접근성 트리의 라벨 노이즈에 가까웠다.
- 검출 신호: `device_flow.py next`의 후보를 역할·부작용 기준으로 읽자 키보드와 정적 문구가 탐험 대상으로 출력됐고, 한국어 follow 계열은 `DESTRUCTIVE` 정규식에 없었다.
- 예방 규칙: 후보 생성은 `enabled + label`이 아니라 actionability metadata·키보드 조상·역할·부작용 분류를 함께 사용한다. raw target coverage와 반복 행을 정규화한 behavior-class coverage를 별도로 보고하고, 실기기 캡처 fixture에 계정 변경 동작이 withheld 되는 회귀를 둔다.
- 추가 검출: iOS 키보드의 globe/dictation 버튼은 `AXKeyboard` 자식이 아닌 형제 `AXButton`으로 나오고 중앙점도 키보드 프레임 밖이라, 조상·기하 검사만으로는 후보에 남았다.
- 추가 예방: WDA의 `KeyboardKey` trait도 키보드 판정 근거로 사용하고 실제 sibling 구조를 회귀 fixture로 고정한다.

## 2026-08-15 — CoreDevice connected와 Appium RemoteXPC ready는 다른 게이트다

- 실패 모드: Xcode 자동 복구 뒤 `devicectl`과 doctor는 물리 iPhone을 connected로 확인했지만 Appium 3/xcuitest 11은 `Available real devices: {}`와 `Unknown device UDID`로 세션 생성을 거부했다.
- 검출 신호: Appium 로그에 `Tunnel registry at 127.0.0.1:42314 is not reachable`가 먼저 나오고, `appium driver run xcuitest list-real-devices -- --devicectl`에는 같은 기기가 정상 표시됐다.
- 예방 규칙: iOS 18+ 실기기는 CoreDevice 연결과 별도로 RemoteXPC registry에 대상 UDID가 있는지 preflight한다. tunnel 생성은 macOS TUN 권한 때문에 sudo가 필요하므로 비대화형 스크립트가 암묵 실행하지 않고, 정확한 공식 명령을 제시한 뒤 세션 전에 중지한다.

## 2026-08-15 — 프로세스 시작 회귀 테스트는 스케줄링 지연을 readiness 실패와 혼동하지 않는다

- 실패 모드: 관리형 Appium의 bounded-start 테스트가 0.25초 안에 fake 프로세스의 첫 줄 기록까지 요구해, 여러 Xcode MCP가 함께 도는 호스트에서 프로세스가 스케줄되기 전에 종료되어 한 번 실패했다. 같은 테스트를 단독 실행하면 통과해 기능 결함과 구분됐다.
- 검출 신호: 스크립트는 pid와 bounded-poll 오류를 정상 기록했지만 fake Appium의 side-effect 파일과 stdout log만 비어 있었고, 단독 재실행은 green이었다.
- 예방 규칙: 비동기 프로세스 시작 테스트는 전체 timeout을 짧게 유지하되, CI/개발 호스트 스케줄링 지연을 흡수할 최소 wall-time을 준다. readiness의 엄격함과 첫 프로세스 instruction이 실행될 시간은 별도 계약으로 본다.

## 2026-08-15 — lock directory 생성과 owner 기록은 하나의 atomic 연산이 아니다

- 실패 모드: RemoteXPC 시작 lock을 `mkdir`로 획득한 직후 owner 파일을 썼는데, 동시 프로세스가 그 사이의 빈 directory를 stale lock으로 지우고 두 번째 tunnel을 시작했다.
- 검출 신호: 단독 테스트는 통과했지만 전체 suite의 동시 세션 테스트에서 Appium start log가 2줄이 됐고, 짧은 반복 실행으로 경쟁 조건을 재현했다.
- 예방 규칙: `mkdir` 성공 자체를 소유권 경계로 본다. contender가 owner 파일이 없거나 비어 있는 lock을 관찰하면 초기화 중인 활성 lock으로 취급하고, 유효한 owner PID가 확인된 경우에만 생존 여부를 판단해 stale cleanup한다.

## 2026-08-15 — zsh에서 변수 뒤 Git refspec을 붙일 때 변수 경계를 명시한다

- 실패 모드: SHA 변수로 두 ref를 원자 push하면서 `$source_sha:refs/heads/main`을 사용하자 zsh가 콜론 뒤를 변수 modifier처럼 해석해 refspec이 `<sha>efs/heads/main`으로 훼손됐다. 원격은 두 ref를 모두 거부해 변경은 없었다.
- 검출 신호: push 오류의 src refspec에 원래 있어야 할 `:r`이 사라졌고, push 전 출력한 live ref는 그대로였다.
- 예방 규칙: 변수와 refspec을 연결할 때는 항상 `${source_sha}:refs/heads/<branch>`처럼 중괄호로 변수 경계를 고정한다. 실패 후에는 원격이 일부라도 바뀌었다고 추정하지 말고 `ls-remote`로 두 ref를 다시 읽는다.
- 2026-08-16: XCUITest 텍스트 필드는 `findElement`가 포커스/레이아웃 변화를 유발해 바로 다음 `setValue`에서 stale이 될 수 있다. 입력 명령은 Appium 오류 본문을 보존하고 `stale element reference`에 한해 동일 semantic locator를 한 번만 재조회한다. 임의 입력 오류를 무제한 재시도하지 않는다.
- 2026-08-16: 단일 unittest를 실행할 때 클래스 소속과 메서드 이름을 추정해 `_FailedTest`가 반복됐다. `rg -n '^class |def test_'` 결과에서 정확한 두 이름을 복사한 뒤 fully qualified test name을 구성한다.
- 2026-08-16: flow parser만 공식 `statekey` 계약을 검사하고 이벤트 생산자의 실제 필드명을 통합 테스트하지 않아, 실기기 로그가 생성되지만 즉시 읽을 수 없는 상태가 배포됐다. 생산자 회귀는 이벤트 키 assertion에 더해 동일 로그를 `device_flow.py stats`에 실제 전달해 소비자 수용까지 검증한다.
- 2026-08-16: 종료 테스트에서 Python이 소유한 child를 shell이 kill하면 부모가 reap하기 전 zombie에도 `kill -0`이 성공해 bounded stop이 실패했다. launchd의 즉시 reaping을 재현하도록 fixture 부모에 wait thread를 두고, 제품 종료 로직과 테스트 소유권 차이를 혼동하지 않는다.
- 2026-08-16: role count와 AXNavigationBar 제목만으로 화면 identity를 만들면 커스텀 top bar의 Threads 메시지/설정처럼 구조가 같은 별도 route가 충돌한다. 셀 밖의 Header/Heading trait은 안정적인 화면 landmark로 포함하고, 동적 목록 행 안의 Header는 제외해 데이터 churn 흡수 규칙을 유지한다.
- 2026-08-16: AXCell은 항상 반복 데이터 row가 아니다. Threads처럼 전체 viewport를 감싸는 collection cell도 있으므로, 크기와 viewport 비율로 structural wrapper를 제외한 뒤에만 cell-descendant를 동적 데이터로 취급한다.
- 2026-08-16: JSONL 일회성 rekey 명령에서 shell/Python 이중 escaping으로 줄바꿈 대신 문자 `\\n`을 기록해 `Extra data`가 났다. 변환 전 원본을 백업하고 원자 교체하며, inline Python에서는 `chr(10)`처럼 escaping 경계가 없는 줄 구분자를 사용한 뒤 reader로 즉시 재검증한다.
