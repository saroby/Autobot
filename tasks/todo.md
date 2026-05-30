# Autobot 구조 개선 — 검수 보고서 기반 작업

목적: 검수 리포트에서 식별된 P0~P2 결함 전부 수정. 더이상 수정이 불필요한 상태로 만들기.

## 합의된 설계 결정 (Working Notes)

1. **complete-phase + run-gate 통합 (P0 #1)**: 기존 `complete-phase`를 그대로 두면 호출자 부담이 큼. 새 명령 `advance-phase --phase N`을 만들어 `run-gate` → 통과 시에만 `complete-phase`. fail 시 phase 상태는 `failed`로 자동 마킹. 기존 `complete-phase`는 호환용으로 남겨두되 mvp.md/resume.md는 `advance-phase`만 사용.

2. **gate 경로 통합 (P0 #2)**: `validate-state.sh run-gate`를 제거(BC 깨뜨림 명시). `pipeline.sh run-gate`만 정설. `validate-state.sh`는 schema/transition validate처럼 read-only 기능만.

3. **build_succeeded SSOT (P0 #3 + P1 #4)**: integration-build/SKILL.md가 phase 5 metadata.build_succeeded=true를 명시 기록. gate_runner.py의 build-log fallback 완전 제거. truth source는 phase metadata 단 하나.

4. **이벤트 스키마 (P1 #5)**: `spec/log-events.json` 신설. event 이름 → required/optional 필드. runtime.py와 build-log.sh가 같은 검증 로직 공유. unknown event는 거부.

5. **declarative gate (P1 #6)**: `spec/pipeline.json`의 gate.checks가 단순 string에서 descriptor 객체로 진화. 기존 string 형식은 BC 유지 (procedural hook으로 fallback). 새 primitive: file_exists, dir_exists, dir_has_swift, file_grep, file_grep_negative, command_success. when 조건: backend_required, phase_status_eq, phase_not_fallback.

6. **fileOwnership SSOT (P1 #7 + #8)**: `spec/pipeline.json`의 phases.<id>.fileOwnership 추가. agent-sandbox.sh가 spec 읽어 enforce + 위반을 phases.<id>.sandbox.violations에 state 기록. Gate 4→5 checks에 sandbox_clean 추가.

7. **circuit breaker (P2 #9)**: runtime의 transition validator가 maxConsecutivePhaseFailures 검사. 임계 도달 시 in_progress 진입 거부. circuit_open 이벤트 기록.

8. **backend_required CLI (P2 #10)**: runtime.py에 `set-flag --key backend_required --value true` 추가. flag_changed 이벤트.

9. **learning_applied 추적 (P2 #12)**: agents/*.md에 학습 적용 후 build-log.sh 호출 의무. event=learning_applied. agents가 자율로 기록. state.learnings_consumed[phase] 누적.

10. **runtime.py 모듈 분리 (P2 #11)**: 정규화된 모듈 — `state_store.py`, `transitions.py`, `event_log.py`, `gate_persistence.py`, `cli.py`. runtime.py는 thin entry. 동작 변경 없음.

## 작업 순서 (loop budget 10)

- [x] Loop 1: 1차 진단 + codex 검토 + 통합 리포트
- [x] Loop 2: P0 #1 (advance-phase) + P0 #2 (gate path) + P0 #3 + P1 #4
- [x] Loop 3: P1 #5 (logEvents in spec, runtime+sh 공통 검증)
- [x] Loop 4: P1 #6 (declarative gate) + P1 #7 (fileOwnership in spec)
- [x] Loop 5: P1 #8 (sandbox_runner.py + state 기록 + sandbox_clean check)
- [x] Loop 6: P2 #9 (circuit breaker enforcement) + P2 #10 (set-flag) + P2 #12 (learning_applied 이벤트 + agent 인스트럭션)
- [x] Loop 7: P2 #11 (runtime.py 분리) — 1225L → 66L facade + 6개 모듈. 회귀 없음 검증.
- [x] Loop 8: 검증 통과 (verify_spec_docs all PASS, smoke test 정상)
- [x] Loop 9: README + orchestrator/SKILL.md 산문 갱신
- [x] Loop 10: lessons.md + 최종 점검

## 성공 기준 (DoD) — 결과

- [x] complete-phase 후 gate 실패가 비일관 상태를 만들지 않는다 → advance-phase가 gate 실패 시 phase를 `failed`로 마킹 (smoke 검증)
- [x] gate 실행 경로 1개 → `pipeline.sh run-gate`만 mutating, `validate-state.sh run-gate`는 명시적 ERROR 메시지로 차단
- [x] Phase 5 build_succeeded는 `phases.5.metadata.build_succeeded`만으로 판정 → build-log fallback 0줄 (smoke로 missing/false/true 케이스 모두 검증)
- [x] `spec.logEvents`가 SSOT, runtime/build-log.sh가 공통 검증 (unknown event 거부, required field 거부 동작 확인)
- [x] `spec.fileOwnership` 선언, sandbox_runner.py가 spec 읽음 → 새 agent 추가 시 spec만 갱신하면 enforcement 따라옴
- [x] Gate 4→5에 sandbox_clean 체크 포함 → 위반이 `phases.4.sandbox.violations`에 자동 기록 + gate가 잡아냄
- [x] circuit breaker가 runtime의 transition validator에서 enforce (global scope)
- [x] runtime.py 분리 완료. 1225L → 66L facade + 6개 모듈 (spec_loader/state_store/event_log/transitions/gate_persistence/cli). BC 호환을 위해 runtime.py가 외부 import 표면을 re-export
- [x] verify_spec_docs.py 모든 카테고리 PASS, render_pipeline_docs.py --check 통과

---

# v0.5.0 사이클 — declarative gate + axiom/peer bridge 정착

목적: Phase 5/Gate 5→6 에서 빌드는 통과하지만 런타임에서 깨지는 결함(Swift 6 data race, SwiftData 손실, 누수, SwiftUI 구조) 을 차단. 자기개선 루프의 마지막 마디(학습 효과 점수화 + 컨텍스트 팩) 도입.

## 작업 결과 (커밋 분할)

- [x] C1 — `feat(env)`: record-environment 에 runtimeHost / peerAi / peerReviewAvailable 3 필드 추가 (cli/state_store/conftest)
- [x] C2 — `feat(tools)`: 신규 헬퍼 모듈 14개 + 회귀 테스트 9종 + hooks/sandbox-pre-write.sh
- [x] C3 — `feat(bridge)`: detect-axiom.sh / detect-peer-ai.sh + autobot-axiom-bridge / autobot-peer-review-bridge SKILL.md
- [x] C4 — `feat(v0.5.0)`: declarative gate 확장(+620 in gate_runner) + spec(+290) + agent/command/orchestrator/integration/scaffold/retrospective SSOT 위임 + test_peer_review_bridge / test_axiom_and_peer_strict
- [x] C5 — `chore`: CHANGELOG [0.5.0] + plugin.json 0.4.0→0.5.0
- [x] C6 — `feat(hooks)`: PreToolUse sandbox-pre-write 정식 등록

## 성공 기준 (DoD)

- [x] 회귀 슈트 148/148 PASS — 각 토픽 커밋 직후 stash 격리로 검증
- [x] CHANGELOG [0.5.0] — 신규 모듈 14개, 회귀 테스트 11종, 거대 리팩토링, 핵심 변경 7항목 모두 기록
- [x] plugin.json version 0.5.0 으로 bump
- [x] hooks/sandbox-pre-write.sh 활성화 — 마커 없을 때 no-op + 마커 있을 때 broad-access 동작 검증
- [ ] smoke e2e 도입 — 단위로 못 잡는 회귀(실제 simulator 부팅, xclog 캡처, ASC 자격 검증) 보호
- [ ] Pillow API: getdata() → get_flattened_data() — visual_contract.py:89 DeprecationWarning 제거 (Pillow 14 / 2027-10-15 제거 예정)

## 후속 사이클 후보

1. **smoke e2e CI** — nightly 로 "Hello World 앱 1개 build + simulator boot + xclog capture" 시나리오 자동 실행. 회귀 슈트가 잡지 못하는 Xcode 26 / iOS 26 시뮬레이터 회귀 보호.
2. **declarative gate primitive 일반화** — gate_runner.py lazy import 라우팅을 spec 의 `gate.primitives` 등록표로 외부화하면 신규 primitive 추가 시 코드 변경 0.
3. **learning effect_score 자동 회귀** — `learning_impact.py` 가 5빌드 이상 누적될 때 effect_score 분포를 기반으로 한 학습 제거 추천 기능.
4. **peer-review verdict 캐싱** — 동일 input_hash 의 phase 재실행 시 peer-review 재호출 절약 (API/요금 비용 절감).

---

# 계약 동결 (frozen-by-default contracts) — resume drift 차단

목적: 검증된 약점 #4 수정. `/autobot:resume 1`(또는 `--force`/구 빌드)이 비결정적 architect 를 재실행해 타입 계약(Models/ServiceProtocols)을 갈아끼우면, 이미 작성된 downstream Views/Services 가 옛 심볼명을 참조한 채 조용히 컴파일이 깨진다. snapshot 까지 덮어써 되돌릴 수도 없다.

## 설계 결정 (Working Notes)

1. **input_hash 와 직교.** input_hash 는 "입력 불변 → phase skip"(architect 안 돔). 동결은 architect 가 *실제로 재실행될* 상황(force/입력변경/hash 미저장)에서 downstream 보호. 둘은 겹치지 않음.
2. **결정은 결정적 스크립트에.** 정책(frozen 판정)은 `contract_freeze.py`, resume.md 는 호출만 (lessons #5 — 정책은 산문이 아니라 엔진에).
3. **downstream 탐지는 spec.fileOwnership SSOT 에서 도출** — Phase-4 agent writes 의 dir 중 .swift 보유. backend/·Assets 는 .swift 없어 자동 제외 (하드코딩 0).
4. **frozen-by-default + opt-in.** 위험한 재생성은 `--regenerate-contracts` 명시할 때만. git `--force` 패턴.
5. **복원 실패 → halt.** 동결해야 하는데 snapshot 복원 실패 시 silent regenerate 금지 (`action: error`). 막으려던 drift 를 fallback 으로 일으키지 않음.
6. **재생성은 forward pass 로 cascade.** `--regenerate-contracts` 시 Models 체크섬 변경 → 이후 phase input_hash miss → Phase 4 가 새 계약에 맞춰 재생성. 추가 코드 불필요.

## 작업

- [x] `scripts/contract_freeze.py` — decide/apply + CLI
- [x] `spec/pipeline.json` logEvents.contracts_frozen
- [x] `scripts/pipeline.sh` freeze-contracts passthrough + USAGE/comment
- [x] `commands/resume.md` Phase 1 재개 freeze-aware + --regenerate-contracts 파싱
- [x] `CHANGELOG.md` [Unreleased]
- [x] `tests/test_contract_freeze.py` — decide matrix + apply 복원/로그 + pipeline.sh passthrough
- [x] Verify: contract_freeze 8/8 PASS, verify_spec_docs 전부 PASS (prose drift 포함)
- [x] adversarial review (advisor) 2건 반영: `--regenerate-contracts` 가 skip 루프보다 먼저 평가돼 조용한 no-op 되는 버그 → force 동일 취급으로 수정 / 동결 분기에 `completed→in_progress`(allow-terminal-restart) 명시

## 성공 기준 (DoD) — 결과

- [x] snapshot+downstream+¬regen → frozen=true, Models 가 snapshot 으로 복원 (drift 된 내용 사라짐) — `test_apply_restores_models_from_snapshot`
- [x] --regenerate-contracts → frozen=false, Models 손대지 않음 — `test_apply_leaves_models_untouched_when_regenerate` + skip 루프가 force 로 phase 1 재실행 보장 (building block: should_skip force=True → skip=False)
- [x] downstream 없음 / snapshot 없음 → frozen=false — `test_no_downstream_not_frozen` / `test_no_snapshot_not_frozen`
- [x] 동결 시 검증된 `contracts_frozen` 이벤트 1건 append — apply 테스트 + event_log 검증(detail 누락 시 거부)
- [x] 회귀 슈트 + verify_spec_docs PASS — 신규 8/8, 전체 385 중 2 실패는 **pre-existing**(phase 2.5, stash 격리 확인, 내 변경 무관)

## 후속 (이번 범위 밖)

- 더 강한 enforcement: architect sandbox 가 resume-with-downstream 에서 Models/ 쓰기를 거부 (현재는 resume.md 호출 의존). v1 은 결정 로직만 엔진화.
- feature-spec.json drift (현재 Models snapshot 만 동결; feature-spec 은 functional gate 영향, 컴파일 아님).
- **별건 pre-existing red (main @ 0.7.2)**: `test_phase_advance_fallback_timing` 2건 실패 + verify_spec_docs 경고 1건 (orchestrator SKILL.md phase 표 8행 vs spec 9 phase). 전부 phase 2.5 도입 부산물, 이 변경과 무관 — 빠른 후속으로 분리 처리 권장.
