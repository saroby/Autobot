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
