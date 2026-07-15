---
name: autobot-orchestrator
user-invocable: false
description: Use when orchestrating a full iOS app build from an idea, coordinating parallel agents, managing build phases, or when the user invokes "/autobot:mvp" or "/autobot:resume". Also use when a build stalls, needs error recovery, or requires phase-level retry coordination.
---

# Autobot Orchestrator

Phase 0–7 dispatcher. 실제 Phase/Gate/Retry 정의는 **`spec/pipeline.json`** 이 SSOT 이고, 이 스킬은 그 spec 을 읽어 디스패치한다. 절차 prose 는 spec 과 reference 에만 둔다.

## SSOT Rules

- Phase 번호·상태 전이·retry·gate 정의 = `spec/pipeline.json`
- 상태 변경·gate 실행·lifecycle 로그 = `scripts/pipeline.sh` 만 사용 (`build-state.json` 직접 편집 금지)
- `mvp.md` · `resume.md` · 이 스킬 · `README.md` 는 spec 의 설명 문서. 충돌 시 spec 우선.

## Safety Policy

- `autonomous`: 로컬 생성·수정·빌드·테스트·archive·재시도
- `warn`: Stitch·fastlane·ASC·axiom 미설치 — 경고 후 fallback 으로 진행
- `require_confirmation`: 원격 저장소 생성/푸시, 외부 시스템 비가역 변경 — 기본 파이프라인 제외

## Phase Summary (auto-rendered from spec)

<!-- AUTOBOT_PHASE_SUMMARY:START -->
| Phase | Name | Agent | Parallel | Gate | Max Retry |
|-------|------|-------|----------|------|-----------|
| 0 | Pre-flight & 환경 준비 | (self) | No | → 환경/이름 검증 | 1 |
| 1 | 아키텍처 + 계약 | architect | No | → 산출물 존재/구조 검증 | 2 |
| 2 | UX Design (필수) | ux-designer | No | → Stitch 성공 필수(미설치 시 fallback) + app-icon-1024.png 존재 | 1 |
| 2.5 | 기획·디자인 HTML 미리보기 (수동, /autobot:plan) | (self) + autobot-plan-preview | No | → preview HTML 존재 (critique 는 스킬 contract) | 1 |
| 3 | Xcode 프로젝트 + Design System | (self) + design-system | No | → .xcodeproj + Package 존재 + tokens 채워짐 | 1 |
| 4 | 병렬 코드 생성 | ui-builder + data-engineer + (backend-engineer) | **Yes** | → 파일 존재 + Models/ 무결성 + sandbox 위반 0건 | 2 |
| 5 | 통합 + 빌드 검증 | quality-engineer (`autobot-integration-build` 스킬) | No | → xcodebuild 성공 | 2 |
| 6 | TestFlight 배포 (수동, /autobot:testflight) | deployer | No | → 배포 결과 기록 (soft) | 1 |
| 7 | 회고 | (self) | No | — | — |
<!-- AUTOBOT_PHASE_SUMMARY:END -->

상세 게이트 항목은 **`references/phase-gates.md`** 참조.

## Dispatcher 결정 로직

1. `.autobot/build-state.json` 을 읽어 다음 실행할 Phase 를 정한다 (`pending` 또는 `failed (retry < maxRetry)` 중 가장 작은 번호). **단 `manual: true` 인 phase (현재 2.5, 6) 는 자율 흐름에서 자동 skip — 전용 명령이 트리거할 때만 실행한다**:
   - Phase 2.5 → `/autobot:plan` 만 트리거 (코드 생성 전 기획·디자인 HTML 미리보기)
   - Phase 6 → `/autobot:testflight` / `/autobot:app-review` 만 트리거 (TestFlight 배포)
   - mvp 자율 흐름은 manual phase 를 만나면 그 다음 non-manual phase 로 점프 (Phase 2 → 3, Phase 5 → 7)
2. 해당 Phase 의 agent 목록을 spec 의 `phases.<id>.agents` 에서 확인한다. 배열이 없으면 self 단계다.
3. self 단계는 직접 수행한다. agent 목록이 있으면 각 항목을 `Agent(subagent_type=...)` 로 디스패치한다.
4. **Agent 디스패치 직전에 context_pack 을 생성**해 sub-agent 프롬프트의 첫 블록으로 임베드한다 (LOOP 19). context-pack 은 spec 에서 생성한 phase 슬라이스·output contract·required input 경로만 전달한다. 정적 작업 지침은 `agents/*.md`, 학습은 `learning-bootstrap.md` 가 각각 소유한다:

   ```bash
   bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" context-pack \
     --phase 4 --agent ui-builder \
     --prompt-tail "$AGENT_SPECIFIC_FREE_TEXT" \
     --format text
   ```

   출력 (≤ 40KB) 을 그대로 Agent 프롬프트 맨 앞에 붙인다. `--prompt-tail` 은 이전 실패 원인처럼 이번 실행에만 존재하는 동적 정보에만 사용한다.
5. **sandbox guard 활성화 / 해제**: sub-agent dispatch 직전 `pipeline.sh sandbox set-active --agent <name> --phase <N>`, 완료 직후 `pipeline.sh sandbox clear-active`. PreToolUse hook 이 marker 를 보고 사전 차단한다 (LOOP 12).
6. Phase 3 은 **두 단계 dispatch**: (a) `create-xcode-project.sh` 를 self 로 실행, 직후 (b) `design-system` 에이전트를 단일 dispatch. 둘 다 끝난 뒤 `advance-phase --phase 3` 으로 gate 실행.
7. Phase 4 는 **반드시 한 메시지에서** ui-builder + data-engineer (+조건부 backend-engineer) 를 동시 디스패치한다. 세 coder 는 disjoint 트리(Views/ vs Services/ vs backend/)에 쓰므로 construction 상 충돌이 없다. 병렬 중에는 세 agent 가 하나의 marker 를 공유하므로 hook 이 개별 write 를 특정 agent 로 귀속시킬 수 없다 — 따라서 marker 의 `agent` 는 broadAccess 컨텍스트(`quality-engineer`)로 set 한다. pre-write guard 의 Phase 4 역할은 **forbidden floor**(`{appName}/Models/` + `.autobot` 제어 파일)를 세 agent 모두에게 강제하는 것이고(broadAccess 라도 floor 는 뚫지 못한다), **agent 간 디렉토리 OVERLAP 은 Gate 4→5 의 post-hoc `agent-sandbox.sh after` 가 정확히 검출**한다. 가장 제한적인 단일 agent 로 marker 를 set 하면 다른 두 coder 의 정당한 write 가 차단되므로 그렇게 하지 않는다.
8. Phase 완료 후 `pipeline.sh advance-phase --phase <N>` 으로 outgoing gate 실행 + 상태 마킹 + (성공 시) inputHash 자동 기록을 한 호출로 처리한다.
9. Gate 실패 시 `retryCount < maxRetry` 면 같은 Phase 재실행, 아니면 `failed` 마킹 후 Phase 7 로 점프.
10. Circuit breaker (3 연속 phase 실패 또는 에러 시그니처 2회 반복) 트립 시 Phase 7 만 진행.

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

## 학습 적용 (Phase 0 + 각 Phase 시작 시)

학습 로드 SSOT 는 `references/learning-bootstrap.md`. 핵심만 요약:

- Phase 별 파일 매핑: 1→`architecture.md`, 4→`parallel_coding.md`, 5→`quality.md`, 6→`deploy.md`, 그 외는 `active-learnings.md`
- 에이전트는 학습 적용 직후 `build-log.sh --event learning_applied` 호출 — Gate 4→5 의 `phase4_agents_consumed_learnings` 가 ui-builder/data-engineer 양쪽 기록을 강제로 검사한다 (누락 시 gate 거부)
- 회고에서 추출된 learning 의 효과 (helped / neutral / hurt) 는 `effect_score` 로 누적되어 hurt 누적 시 자동 quarantine

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
| Context pack | `pipeline.sh context-pack --phase N --agent <name>` (Agent dispatch 직전) | focused spec/ownership/input-path pack; 40KB 초과 시 warning |

이벤트 유형 전체 목록은 `spec/pipeline.json.logEvents` 가 SSOT.

## Plugin Detection (선택 의존성)

| 플러그인 | 감지 | 활용 | Fallback |
|---------|------|------|----------|
| Axiom | `scripts/detect-axiom.sh` (exit 0 = 설치됨) | Phase 5 critical audit, Phase 7 health-check | `axiom-distilled` references 만으로 진행 |
| Peer AI | `scripts/detect-peer-ai.sh` | Codex-host → Claude review, Claude-host → Codex review | `peerReview.verdict=skipped` 기록 |
| Stitch | `mcp__stitch__list_projects` 도구 존재 | Phase 2 primary 경로 | architecture.md Design Direction → 최소 design-spec.json |
| fastlane | `command -v fastlane` | Phase 6 metadata/upload | Phase 6 보조 도구 누락 경고 |

## Composition Seam (Phase 3 출력)

Phase 3 scaffold 는 다음을 **컴파일 가능한 형태로** 생성한다 — Phase 4 에이전트의 충돌 표면을 최소화하기 위함:

- `<AppName>/App/AppEntry.swift` — `@main` 단일 진입점
- `<AppName>/App/CompositionRoot.swift` — 의존성 주입 위치 (quality-engineer 만 수정)
- `<AppName>/App/ServiceStubs.swift` — Preview 용 mock (ui-builder 가 생성/유지)
- `<AppName>/Models/ServiceProtocols.swift` — 통합 계약 (architect 만 수정)

Phase 4 의 ui-builder/data-engineer 는 protocol 뒤 구현만 작성한다. `@main`, `CompositionRoot`, `Models` 직접 수정 금지 — Gate 4→5 에서 차단.

### Phase 3 two-step dispatch

Phase 3 는 두 단계로 실행된다 (모두 같은 phase 번호 내에서):

1. **scaffold (self)** — `create-xcode-project.sh` 호출. 인자에 `--design-system-module $(jq -r .designSystemModule .autobot/architecture.json)` 를 반드시 전달. Composition seam + `Packages/<Module>/Package.swift` + project.yml wiring + Tokens stub 4개 생성.
2. **design-system 에이전트 dispatch** — context-pack 으로 phase 슬라이스 + fileOwnership.agents.design-system.writes + design-spec.md / architecture.md 입력 경로를 전달. sandbox marker 의 `agent` 는 `design-system`.

두 단계 사이에는 `advance-phase` 를 호출하지 않는다 (같은 phase). step 1 실패 시 step 2 는 생략. step 2 실패 시 retryCount 가 phase 3 의 maxRetry (1) 안이면 step 2 만 재실행.

## Error Recovery

| 실패 유형 | 대응 | 한도 |
|----------|------|------|
| 에이전트 산출물 누락 | 같은 에이전트 재실행 | spec `phases.<N>.maxRetry` |
| 컴파일 에러 | Phase 5 build-fix loop | spec `policies.buildFixLoop.maxAttempts` |
| 동일 에러 시그니처 반복 | Circuit breaker | spec `policies.circuitBreaker.errorSignatureRepeat` |
| Phase 5 가 Phase 4 산출물 손상 | `snapshot-contracts.sh restore-phase --phase 4` | 2회 실패 시 자동 |
| 외부 시스템 (ASC, fastlane) 실패 | fallback 경로 또는 사용자 안내 | 1 |

복구 기준점은 git 이 아니라 build artifact snapshot — 설계상 git 상태에 의존하지 않는다.

## 보고 / 회고

Phase 7 은 두 산출물을 순서대로 생성:

1. **`build-report.md`** — `autobot-build-report` 스킬 사용. 플러그인 수준 문제를 구조화.
2. **`learnings.json`** — `autobot-retrospective` 스킬 사용. 누적 학습 + `effect_score` 갱신.

Phase 7 직후 `run-summary.json` / `run-summary.md` 가 모든 run (성공/실패) 에 대해 생성된다 — phase duration, gate 결과, build attempts, runtime smoke 결과, visual contract 점수, applied learnings, **capability coverage** (미지원 카테고리·P2 stub·backend pending·검증 prereq 설치 안내·검증 깊이 caveat — `scripts/capability_coverage.py`) 포함. 완료 보고는 coverage 의 격차를 침묵하지 않고 화면에 표면화한다.

## Additional Resources

| Reference | 내용 |
|-----------|------|
| `references/phase-gates.md` | Phase 별 검증 항목, 통과 조건, 실패 시 동작 |
| `references/learning-bootstrap.md` | 학습 로드 프로토콜 SSOT |
| `references/architecture-template.md` | architecture.md 템플릿 |
| `references/planning-patterns.md` | 아이디어 분석, 기능 추출, 복잡도 추정 |
| `references/agent-dispatch.md` | 병렬 에이전트 프롬프트, 전체 fileOwnership 매트릭스 |
| `references/troubleshooting.md` | 증상별 진단 + 해결법 |
| `autobot-integration-build` 스킬 | Phase 5 Build-Fix Loop, Wiring 패턴, 에러 카탈로그 |
