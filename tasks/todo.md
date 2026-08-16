# clone 속도·정확도 개선 (2026-08-16)

승인된 순서: ① 캡 튜닝 → ③ 배치 explore → 정확도 ①(미커버 영역) → 정확도 ②(구조 diff)

## ① WDA 세션 성능 튜닝 — 완료
- [x] `device_wda.sh _tune_session`: 세션 생성/재사용 직후 settings API로 `waitForIdleTimeout=0`, `animationCoolOffTimeout=0`
- [x] 노브: `CLONE_WDA_IDLE_TIMEOUT`, `CLONE_WDA_ANIM_COOLOFF`, `CLONE_WDA_SNAPSHOT_MAX_DEPTH`(기본 미전송), `CLONE_WDA_TUNE=0`
- [x] 실패 시 경고만 (advisory)
- [x] 테스트 4개 + 재사용 경로 재튜닝 단언
- [x] SKILL.md / commands/clone.md 반영

## 번외 — flow 로그 계약 버그 수정 (진행 중 발견)
- [x] producer(`state=`/`from_state=`) ↔ reader(`statekey` 강제) 불일치 수정: shell이 공식 필드명 emit
- [x] 경계 회귀 테스트: step 산출 로그를 `device_flow.py stats`에 통과
- [x] lessons.md 기록
- [x] flake 2건 안정화 (appium auto-start 테스트 race)

## ③ 배치 explore — 완료
- [x] `device_flow.py todo <flow> <tree>`: 현재 캡처 기준 미탐험 안전 후보 (behavior-class, withheld 제외)
- [x] `device_wda.sh explore <sid> <outdir> [max_steps]`: frontier 기계 소진, step 가드 공유, 소진/한도/가드에서 정지
- [x] 테스트 (drain 2-step, max_steps, withheld 미탭, todo 4케이스)
- [x] SKILL.md Step 2 / clone.md 기본 경로 갱신

## 정확도 ① 미커버 영역 검출 — 완료
- [x] `device_measure.py uncoveredRegions`: 16px 블록 스캔, 시스템 크롬 밴드 제외, 전체화면 컨테이너 커버리지 제외
- [x] `clone_postprocess.py` 스펙 md에 "Uncovered regions" 섹션
- [x] 테스트 4개, SKILL.md Step 3 반영

## 정확도 ② 구조 diff — 완료
- [x] `device_render.sh`: AXe 있으면 `<out>.tree.json` 덤프 (best-effort)
- [x] `clone_structural_diff.py`: 라벨→프레임 매칭, 누락 exit 1, 이탈 WARN, 잉여 INFO
- [x] 테스트 7개, SKILL.md Step 6-4 / clone.md 반영

## Results
- 다음 실런 확인 사항: `CLONE_METRICS=1`로 http-metrics.jsonl 수집해 튜닝 효과 실측. idle 대기 제거가 문제 일으키면 `CLONE_WDA_IDLE_TIMEOUT`로 되돌림.
- snapshotMaxDepth 기본값은 유지 (측정 정확도 보존).
