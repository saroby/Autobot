# 플러그인 평가 후 릴리스 드리프트 수정 — 2026-07-15

목표: 평가에서 확인된 릴리스 메타데이터, README 요구사항, CI 기본 검증 드리프트를 수정하고 재발을 방지한다.

## 수용 조건
- [x] `plugin.json`과 `pyproject.toml`의 버전·설명이 일치하고 자동 검증된다.
- [x] README가 변동 가능한 에이전트 수를 하드코딩하지 않고 Xcode 26+ 요구사항을 정확히 안내한다.
- [x] PR CI가 Python compile과 모든 추적 shell script의 문법을 검사한다.
- [x] 표적 테스트와 전체 회귀 검증이 통과한다.

## 체크리스트
- [x] 기존 드리프트 검증 패턴과 교훈 확인
- [x] 버전·README·CI 계약 최소 수정
- [x] 릴리스 메타데이터 드리프트 회귀 테스트 추가
- [x] Verify: 표적 테스트, spec/docs, 전체 테스트, shell syntax, diff check
- [x] Results 기록

## Working Notes
- `.claude-plugin/plugin.json`을 플러그인 릴리스 메타데이터 SSOT로 사용한다.
- 에이전트 수는 추가·제거 시 다시 낡는 숫자 대신 비수치 표현으로 바꾼다.
- 별도 lint/type 도구는 도입하지 않고 현재 의존성으로 결정적으로 실행 가능한 compileall과 bash 문법 검사만 CI에 추가한다.

## Results
- `pyproject.toml`을 플러그인 매니페스트의 `0.12.2` 버전과 App Store review 설명에 맞췄다.
- README의 변동 가능한 에이전트 숫자 하드코딩을 제거하고 Xcode 최소 요구사항을 26+로 정정했다.
- `verify_spec_docs.py`가 plugin manifest와 pyproject의 버전·설명 불일치를 차단하며, 불일치 두 종류와 현재 정합을 회귀 테스트한다.
- PR CI에 Python compileall과 모든 추적 `.sh` 파일의 `bash -n` 검사를 추가했다.
- 검증: 표적 11 tests PASS, 전체 667 tests PASS, spec/docs 10/10 PASS, compileall·전체 shell syntax·`git diff --check` PASS, Claude plugin validation PASS.

---

# 하네스 핵심 계약 보강 — 2026-07-15

목표: 모델 재량에 맡길 수 없는 동시성, 재개, 산출물 출처, 릴리스 상태를 코드 계약으로 보강한다.

## 수용 조건
- [x] 빌드 잠금이 CLI 종료 뒤에도 유효하며 다른 buildId를 차단한다.
- [x] 병렬 상태 변경이 원자적이고 업데이트 유실 없이 검증된다.
- [x] 재개 해시는 전이적 상류 입력을 포함하고 반복 오류 시 체크포인트 복구가 실행 가능하다.
- [x] 빌드/런타임/아카이브/IPA가 동일한 검증 산출물 identity로 이어진다.
- [x] 이벤트와 run summary가 현재 buildId로 격리된다.
- [x] App Review가 버전된 실행형 상태 머신으로 진행/재개된다.
- [x] 필수 검증 입력 부재는 통과가 아니라 DEGRADED/차단으로 기록된다.
- [x] doctor가 로컬/출하 준비도를 구조화해 보고한다.
- [x] 관련 회귀 테스트와 전체 spec/docs/test 검증이 통과한다.

## 체크리스트
- [x] durable build lock + atomic state mutation
- [x] transitive resume input hash + build-fix checkpoint
- [x] artifact provenance + exact runtime artifact + packaged artifact verification
- [x] buildId event isolation + run summary filtering
- [x] executable App Review controller
- [x] verification fail-closed/degraded contracts
- [x] unified doctor/readiness checks
- [x] Verify: focused tests, full suite, spec/docs, compileall, shell syntax, diff check
- [x] Review findings 처리 및 Results 기록

## Working Notes
- 현재 브랜치는 `main`; 사용자는 전체 구현을 지시했지만 커밋은 요청하지 않았으므로 기존 변경을 보존한 채 작업 트리에만 반영한다.
- 결정적 불변식은 Python/shell 코드와 테스트가 소유하고, command/skill 문서는 해당 실행기를 호출하는 얇은 인터페이스로 유지한다.
- 기존 모델 성능 향상 대응 감사 변경 25개 파일은 같은 승인된 작업의 선행 변경이며 되돌리지 않는다.

## Results
- durable build lease를 generation token/CAS로 완성하고, run-summary를 소유권 증명에서 제외했다. resume과 Phase 7은 획득 시 받은 token만 release에 사용한다.
- state/event mutation을 flock+atomic write로 직렬화하고 buildId 격리, 전이적 input hash, 무결성 검증 checkpoint+rollback을 추가했다.
- xcodebuild 성공 산출물을 attempt-local provenance로 고정하면서 build-scoped DerivedData는 재사용한다. archive/app digest는 한 번의 tree traversal로 계산한다.
- archive→IPA→upload→review-submit이 buildId/bundle/input/archive/artifact digest로 이어지며, ambient checkout·mtime·result 문자열만으로 완료를 재사용하지 않는다.
- App Review를 claimToken 기반 실행형 controller로 바꾸고 모든 phase evidence를 재개 시 다시 검증한다. 중복 command preflight는 제거했다.
- release env는 공용 allowlist parser로 통일하고 shell eval/source 기반 임의 환경 주입을 제거했다. doctor는 local/ship readiness를 구조화한다.
- 프롬프트 다이어트는 model pin, 복제 역할 prompt, 무차별 context 재주입, command-level 중복 gate, raw PID lock을 제거하면서 결정적 gate/spec/검증은 보존했다.
- 검증: `bash tests/run_tests.sh` — 664 tests PASS. `python3 scripts/verify_spec_docs.py` — 9/9 PASS. Python compileall, 변경 shell `bash -n`, `git diff --check` PASS.
- 독립 코드리뷰에서 발견된 archive exit contract, run-summary 호환성, App Review digest, lock generation 우회, checkpoint metadata 변조, nested digest 의미 회귀를 모두 수정했다. 외부 cross-model 리뷰는 두 provider 실행이 실패해 결과 없이 폐기했고 로컬 다중 관점 리뷰로 보완했다.
- 호스트 디스크가 검증 중 138MB까지 내려가 ENOSPC가 발생했으나 공유 Xcode cache는 삭제하지 않았다. production disk gate는 유지하고 hermetic test에서만 명시적 probe skip을 사용했다.

---

# 모델 성능 향상에 따른 하네스 다이어트 감사 — 2026-07-15

목표: 모델 보정용 산문·중복 절차·과잉 검수 중 현재 품질/속도에 해로운 부분을 제거하되,
결정적 상태 전이·보안 경계·산출물 검증·회귀 방지는 유지한다.

## 수용 조건
- [x] 제거 후보마다 실제 호출 경로와 중복/역효과 근거가 있다.
- [x] 모델 재량에 맡겨도 되는 지시와 코드로 강제해야 하는 불변식을 구분한다.
- [x] 명백한 중복만 최소 범위로 제거하고 SSOT/spec 계약을 깨지 않는다.
- [x] 문서 계약 검사와 전체 테스트를 통과하고, 별도 린트/타입 도구가 없음을 확인한다.

## 체크리스트
- [x] 하네스 구조·프롬프트·기능 표면과 기존 교훈 파악
- [x] 재사용성·품질·효율 검수 결과를 직접 증거와 대조
- [x] 제거/보존 결정과 최소 변경 설계
- [x] 안전한 제거 구현 및 관련 테스트 조정
- [x] Verify: spec/docs, tests, compileall, diff check
- [x] Results 기록

## Working Notes
- `spec/pipeline.json`과 `scripts/pipeline.sh` 기반 상태/게이트 집행은 모델 성능과 무관한 안전 계약으로 보존한다.
- 프롬프트 장황함 자체가 제거 근거는 아니다. 같은 정보를 여러 계층에서 반복하거나, 검증 없는 다중 리뷰를 강제하거나, 최신 호스트 기능과 충돌하는 경우를 우선한다.
- 현재 브랜치는 `main`, 시작 시 작업 트리는 clean이었다.
- baseline: `bash tests/run_tests.sh` — 605 tests PASS.
- 즉시 제거: agent model pin, context-pack의 무차별 learning/reference 재주입, 중복 dispatch template/TeamCreate/background 경로, resume raw-PID lock, command-level shipping gate 재실행, generic UI layout 코드 예시.
- 보류: Phase 7 Axiom 제거, 전역 learning publish 폐기, resume 상태머신 전체 재작성, dead UX skill 삭제. 영향 범위가 커 별도 설계/측정이 필요하다.

## Results
- 에이전트 모델 고정과 복제된 역할 프롬프트를 제거해 호스트 기본 모델과 단일 역할 정의를 사용하도록 했다.
- context pack은 단계 계약과 동적 입력만 전달하며, 전역 학습·정적 참조 목록을 다시 주입하지 않는다.
- resume lock을 JSON lock 프로토콜로 통일하고, 출하 Gate 5→6은 archive 직전 `preflight-ship`에서 한 번만 새로 검증한다.
- 품질 에이전트의 고정 재시도 횟수·파일 재작성 휴리스틱과 UI 빌더의 범용 레이아웃 앵커를 제거했다.
- 검증: `bash tests/run_tests.sh` 610 tests PASS, `python3 scripts/verify_spec_docs.py` 9/9 PASS, `python3 -m compileall -q scripts tests` PASS, `git diff --check` PASS.
- 저장소에는 별도 ruff/mypy/pyright 설정이나 설치가 없어 해당 검사는 적용 대상이 아니다.

---

# 전체 감사 → 무인 최고품질 앱 생산 (0.12.0) — 2026-07-12

목적: "인간의 도움 없이 최고의 앱" — ① 무인 자율 완주 ② per-build 품질 ③ 빌드간 학습.
방법: 7렌즈 병렬 감사(적대적 검증: 확정 22 / 반증 0 / 경미 54) → 6 workstream 병렬 구현
(Wave A: WS1~4, Wave B: WS5~6) + 교차 리뷰 2회.

## 체크리스트
- [x] 베이스라인: 533 tests, 2 FAIL (test_app_register — 격리 버그가 노출한 실결함)
- [x] register-app 인증 모델 근본 수정 (--api_key_path 는 허구 → Apple ID 세션)
- [x] WS1 에이전트-게이트 계약 정합 (architect Bash, Liquid Glass API 실컴파일 정정, generic 드리프트 검사)
- [x] WS2 상태머신 복원력 (breaker consecutive 복원, reclaim, backfill)
- [x] WS3 학습 저장소 무결성 (오염 차단+정리, 병합 멱등화, 첫빌드 모순)
- [x] WS4 App Review 체인 (rating config 이원화, SSOT 위임, bounded 재시도)
- [x] WS5 출하 게이트 기계화 (preflight-ship, zero-P0 hard fail, 다크모드, DEGRADED 신설 2종)
- [x] WS6 외부 신호 루프 v1 (/autobot:feedback, 승격 게이트 데이터 집행)
- [x] 교차 리뷰 경미 이슈 수정 (승인 필터, Stub 블록주석, 후보 dedup, resume 문서)
- [x] Verify: 전체 597 tests OK · spec_bundle check OK · verify_spec_docs 9/9 PASS
- [x] CHANGELOG 0.12.0 + plugin.json 버전 + lessons #25~27

## Results
- 테스트 533(2 FAIL) → **597 전부 green**. 실 글로벌 학습 스토어 정화 확인(88 items, 오염 0).
- 무인 완주를 지금 깨던 결함 해소: architect Bash, breaker 영구누적, register 허구 플래그,
  meta→app-review rating config 함정.
- 출하 세탁 차단: preflight-ship(runtime 강제) + zero-P0 hard fail + smoke skip→degraded.
- 학습 루프: 내부(오염/클로버 수정) + 외부(리뷰→학습 v1, Goodhart 천장의 첫 외부 닻).
- 남은 인간 개입(설계상 제거 불가): ① ASC 키 발급(1회) ② 약관 수락(Apple 강제)
  ③ ASC 웹 세션 2FA(~30일 1회) — ③ 은 현재 만료 상태, `fastlane spaceauth -u saroby@naver.com` 필요.

## 후속 (다음 세션 후보)
- [ ] resume.md raw-PID lock ↔ build_lock.py JSON lock 이중 프로토콜 통일 (WS2 가 근거로만 사용)
- [ ] spec `allowExplicitRestartFromTerminal` 키 이름과 확장된 집행 범위 정합 (comment 로 임시 문서화됨)
- [ ] rule_is_quoted_review 패러프레이즈 천장 — 필요 시 유사도 기반 강화
- [ ] icon-only Button 접근성 라벨 휴리스틱 (오탐 위험으로 2차 보류)
- [ ] 외부 신호 루프 v2: ASC 크래시/리텐션 (aso-skills, API Key 필요)
