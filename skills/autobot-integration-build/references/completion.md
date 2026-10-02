## Gate 5→6 통과 조건

검증의 SSOT는 `spec/pipeline.json.gates["5->6"]`와 실행 엔진이다. 별도 grep 목록을 복제해 같은 검사를 다시 돌리지 않는다.

- 실제 build/test 결과를 보존한다. Authored 테스트의 컴파일·통과와 각 P0 functional acceptance의 postcondition 증거가 필요하다 (`logic_tests_pass`, `functional_flows_pass`).
- Production `CompositionRoot.swift`에 실제 Repository/ModelContainer를 배선하고 Preview용 `ServiceStubs.swift`를 보존한다. Privacy manifest와 조건부 backend 검증을 완료한다.
- Step 7–9의 Axiom/peer/visual 결과와 미가용 사유를 metadata로 전달한다. 누락·실패·DEGRADED 결과를 성공으로 바꾸지 않는다.
- 오케스트레이터가 `pipeline.sh advance-phase --phase 5`로 outgoing gate와 상태 기록을 처리한다. 독립적인 완료 상태를 직접 기록하지 않는다.
- 통과 뒤에는 관련 코드가 바뀌거나 새 실패가 생긴 경우에만 영향을 받는 검사를 다시 수행한다. 출하는 기존 `preflight-ship` 경로를 통과해야 한다.

## Phase 4 재생성 판단 기준

spec의 build-fix 한도를 소진하면 무한 수정을 멈추고 증거를 보존한 채 상위 phase로 인계한다.

| 조건 | 액션 |
|------|------|
| 동일 에러 signature가 정책 임계치에 도달 | Phase 4 snapshot 복원 후 오류 증거와 함께 중단·인계 |
| 여러 파일의 구조적 불일치가 build-fix 한도까지 지속 | Phase 4 전체 재생성을 운영자에게 권고 (`/autobot:resume 4`) |
| Models/의 타입과 사용 코드가 구조적 불일치 | Phase 1(architect) 재검토 권고 |

**Phase 4 스냅샷 복원 (Phase 5에서만):**
quality-engineer의 수정이 코드를 악화시킨 경우, Phase 4 완료 시점의 깨끗한 상태로 되돌린다:
```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/snapshot-contracts.sh" restore-phase --phase 4 --app-name "<AppName>"
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event snapshot_restore --detail "Restoring phase-4 snapshot"
```

## Additional Resources

| Reference | 내용 |
|-----------|------|
| **`references/build-error-catalog.md`** | 카테고리별 빌드 에러 패턴 + 수정 레시피 |
| **`references/wiring-patterns.md`** | Integration Wiring 아키텍처별 상세 패턴 |
