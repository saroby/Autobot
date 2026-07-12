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
