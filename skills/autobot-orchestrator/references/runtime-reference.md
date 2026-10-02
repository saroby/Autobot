## Agent 디스패치 컨텍스트 전달

에이전트는 파일 경로로 컨텍스트를 받는다 — 전체 본문을 프롬프트에 임베드하지 않는다.

| 파일 | 생성자 | 소비자 |
|------|--------|--------|
| `.autobot/build-state.json` | Phase 0 | 전체 |
| `.autobot/architecture.md` | architect | ux-designer, ui-builder, data-engineer, quality-engineer |
| `.autobot/design-spec.md` (+ `designs/*.png`) | ux-designer | ui-builder |
| `<AppName>/Models/*.swift` (+ `ServiceProtocols.swift`) | architect | 전체 (읽기 전용) |
| `<AppName>/App/ServiceStubs.swift` | ui-builder | quality-engineer (Preview 보존) |
| `<AppName>/Services/*Repository.swift` | data-engineer | quality-engineer |
| `backend/` | backend-engineer | quality-engineer |

전체 ownership 매트릭스는 `spec/pipeline.json` 의 `fileOwnership` 섹션 (SSOT) 과 `references/agent-dispatch.md` 참조.

## Pipeline Engine Quick Reference

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" schema                    # JSON 스키마 검증
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" init-build ...             # build-state.json 생성 + 출력된 lockToken을 실행 컨텍스트에 보관
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" record-environment ...     # detect-* 출력 기록
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase  --phase N --detail "..."
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase N    # outgoing gate + 마킹
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" fail-phase   --phase N --error "..." --increment-retry
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate     --gate "N->M" # gate 만 실행
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" set-flag     --key backend_required --value true --reason "..."
```

`validate-state.sh` 는 read-only 진단. 상태 변경은 모두 `pipeline.sh`. Phase 완료는 `advance-phase`만 사용한다.

`init-build` stdout의 `LOCK_TOKEN=...` 값을 `OWNED_LOCK_TOKEN`으로 실행 컨텍스트에
보관하고 Phase 7 run-summary 생성 뒤 token release에 전달한다. status에서 token을
다시 읽지 않는다. 그 사이 다른 resume가 takeover했다면 새 세대를 해제하면 안 된다.

**진입 플래그** (mvp 호출 인자): 사용자가 `/autobot:mvp --quality=max …` 로 호출했으면 Phase 0 완료 직후 `set-flag --key qualityMax --value true --reason "operator opted into quality-max via /autobot:mvp"` 를 1회 실행한다 (`--allow-visual-drift` → `allowVisualDrift` 와 동일 패턴). 이후 Gate 5→6 의 peer/axiom sidecar 와 Gate 2→3 의 design fallback 체크가 이 플래그를 읽어 미가용 skip 을 PASS 대신 DEGRADED 로 처리한다. peer/Axiom 이 설치됐는데 누락·실패·비감사 가능 결과를 남기면 qualityMax 여부와 무관하게 DEGRADED 로 기록한다. DEGRADED 는 로컬 MVP 완료를 막지 않고 출하 경로를 차단한다.

## 보조 인프라

| 책임 | 스크립트 | 비고 |
|------|----------|------|
| Build lock | `build_lock.py` — `init-build`가 acquire, Phase 7 종료가 token으로 release | lease + compare-and-swap token으로 동시 재개를 차단하고 만료 lease만 자동 재확보. run-summary는 소유권 증명이 아니다. 진단: `pipeline.sh build-lock status` |
| Event log | `scripts/build-log.sh` | `.autobot/build-log.jsonl` append-only |
| Models 체크섬 / Phase 스냅샷 | `scripts/snapshot-contracts.sh` | Phase 4 산출물 복원에 사용 |
| Agent sandbox | `scripts/agent-sandbox.sh before/after` | 위반은 `phases.<N>.sandbox.violations` 자동 기록 |
| 플러그인 감지 | `scripts/detect-{axiom,peer-ai,plugins}.sh` | exit code 와 stdout 기반, 추측 금지 |
| 환경 스냅샷 | `pipeline.sh env-snapshot ensure` (Phase 0) | Xcode/SDK/simulator UDID/credentials. `.autobot/env_snapshot.json` 캐시, stale 시 자동 재캡처 |
| Run summary | `pipeline.sh write-run-summary` (Phase 7 마지막) | `artifacts/<buildId>/run-summary.{json,md}` + `latest` 심볼릭 링크 |
| Learning grade | `pipeline.sh grade-learnings --build-id <id>` (Phase 7) | `learnings.json` 의 effect_score 누적 + 자동 quarantine |
| Idempotent resume | `pipeline.sh input-hash should-skip --phase N [--force]` (resume) | input manifest 미변경 시 phase 재실행 skip |
| Context pack | `pipeline.sh context-pack --phase N --agent <name>` (Agent dispatch 직전) | focused spec/ownership/input-path pack; 8KB 초과 시 warning |

이벤트 유형 전체 목록은 `spec/pipeline.json.logEvents` 가 SSOT.

## Plugin Detection (선택 의존성)

| 플러그인 | 감지 | 활용 | Fallback |
|---------|------|------|----------|
| Axiom | `scripts/detect-axiom.sh` (exit 0 = 설치됨) | Phase 5 critical audit, Phase 7 health-check | `axiom-distilled` references 만으로 진행 |
| Peer AI | `scripts/detect-peer-ai.sh` | Codex-host → Claude review, Claude-host → Codex review | `peerReview.verdict=skipped` 기록 |
| Stitch | `mcp__stitch__list_projects` 도구 존재 | Phase 2 primary 경로 | architecture.md Design Direction → 최소 design-spec.json |
| fastlane | `command -v fastlane` | Phase 6 metadata/upload | Phase 6 보조 도구 누락 경고 |
