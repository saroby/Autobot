# Autobot 구조 개선 — 검수 보고서 기반 작업

목적: 검수 리포트에서 식별된 P0~P2 결함 전부 수정. 더이상 수정이 불필요한 상태로 만들기.

## 합의된 설계 결정 (Working Notes)

1. **complete-phase + run-gate 통합 (P0 #1)**: 기존 `complete-phase`를 그대로 두면 호출자 부담이 큼. 새 명령 `advance-phase --phase N`을 만들어 `run-gate` → 통과 시에만 `complete-phase`. fail 시 phase 상태는 `failed`로 자동 마킹. 기존 `complete-phase`는 호환용으로 남겨두되 make.md/resume.md는 `advance-phase`만 사용.

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
