---
name: autobot-orchestrator
user-invocable: false
description: "Run or resume the full Autobot iOS build pipeline and coordinate phase recovery (/autobot:mvp, /autobot:resume)."
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
1a. **Phase 1 (architect) dispatch 직전 self-step "market-brief"**: mcp-appstore(`search_app` → `get_similar_apps` → `analyze_reviews`)가 가용하면 유사 카테고리 앱을 조사해 `.autobot/market-brief.json` 을 작성한다 — `{generatedAt, source: "mcp-appstore", similarApps:[{name, notableFeatures:[]}], tableStakes:[], complaintThemes:[], opportunityGaps:[], noDirectCompetitors}`. 직접 경쟁앱이 없으면 fail 이 아니라 `noDirectCompetitors: true` 로 기록한다. mcp-appstore 가 미설치·미가용이면 이 파일 작성을 **건너뛰고** architect 가 이미 보유한 WebSearch fallback 에 맡긴다(soft-skip — hard fail 금지, DEGRADED 도 아님. 존재하면 활용, 없어도 자율 빌드는 그대로 진행).
2. 해당 Phase 의 agent 목록을 spec 의 `phases.<id>.agents` 에서 확인한다. 배열이 없으면 self 단계다. Phase 4 의 backend-engineer 는 `backend_required == true` 일 때만 디스패치한다 — `references/agent-dispatch.md` 참조.
3. self 단계는 직접 수행한다. agent 목록이 있으면 각 항목을 `Agent(subagent_type=...)` 로 디스패치한다.
4. **Agent 디스패치 직전에 context_pack 을 생성**해 sub-agent 프롬프트의 첫 블록으로 임베드한다 (LOOP 19). context-pack 은 spec 에서 생성한 phase 슬라이스·output contract·required input 경로만 전달한다. 정적 작업 지침은 `agents/*.md`, 학습은 `learning-bootstrap.md` 가 각각 소유한다:

   ```bash
   bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" context-pack \
     --phase 4 --agent ui-builder \
     --prompt-tail "$AGENT_SPECIFIC_FREE_TEXT" \
     --format text
   ```

   출력 (8KB soft budget; 초과 시 warning, 계약은 생략하지 않음) 을 그대로 Agent 프롬프트 맨 앞에 붙인다. `--prompt-tail` 은 이전 실패 원인처럼 이번 실행에만 존재하는 동적 정보에만 사용한다.
4a. **모델 라우팅 (host-gated)**: Claude Code 호스트면 Agent dispatch 시 `references/agent-dispatch.md` 의 **Model Routing** 표대로 `Agent(model=<tier>)` 를 지정한다 (architect·quality-engineer=`opus`, 나머지 coder/보조 에이전트=`sonnet`). 그 외 호스트(codex/unknown)는 `model` 을 생략해 호스트 기본 모델을 상속한다. host 판별은 빌드당 1회 — `bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-peer-ai.sh" --format env` 의 `runtimeHost` 값을 캐시해 모든 dispatch 에 재사용한다. **frontmatter 에는 model 을 박지 않는다** (provider 중립 불변식 — `test_agents_inherit_the_host_model` 이 강제). tier 표는 agent-dispatch.md 가 SSOT.
5. **sandbox — 두 개를 모두 건다. 하나만 걸면 게이트가 막힌다.**

   ```bash
   # dispatch 직전 (둘 다)
   bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox set-active --agent <name> --phase <N>
   bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent <name> --app-name <App>
   # (agent 실행)
   # 완료 직후 (둘 다)
   bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent <name> --app-name <App> --phase <N>
   bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox clear-active
   ```

   - `sandbox set-active` / `clear-active` 는 **사전 차단** — PreToolUse hook 이 marker 를 보고 write 를 막는다 (LOOP 12).
   - `agent-sandbox.sh before` / `after` 는 **사후 검증** — Gate 4→5 의 `sandbox_clean` 이 `phases.<N>.sandbox.agentsVerified` 를 hard 검사한다.

   **`before` 를 빠뜨리면 `after` 가 `ERROR: missing 'before' snapshot` 으로 죽고 게이트가 막힌다.** 그때 사후에 `before` 를 찍어 `after` 를 돌리면 diff 가 비어 "0 violations" 가 기록되는데, 그건 검증이 아니라 **빈 통과**다. 그렇게 기록하지 마라 — 세탁이다. 이미 놓쳤다면 소유권을 독립적으로 확인한 뒤(phase 시작 시각 이후 변경된 파일을 `fileOwnership` 과 대조) 그 근거를 보고서에 쓰고, 도구가 낸 0건이 아니라 그 감사 결과를 진술한다.
6. Phase 3 은 **두 단계 dispatch**: (a) `create-xcode-project.sh` 를 self 로 실행, 직후 (b) `design-system` 에이전트를 단일 dispatch. 둘 다 끝난 뒤 `advance-phase --phase 3` 으로 gate 실행.
6a. Phase 2 도 같은 two-step 패턴: (a) `ux-designer` 를 dispatch, 직후 (b) `.autobot/app-icon-1024.png` 가 없으면 `autobot-app-icon` 스킬을 self 로 실행. gate 2→3 의 `app_icon_source_present` 가 이 파일을 hard 검사하므로 (b) 를 건너뛰면 재시도도 같은 이유로 실패한다. 둘 다 끝난 뒤 `advance-phase --phase 2`.
7. Phase 4 는 **반드시 한 메시지에서** ui-builder + data-engineer (+조건부 backend-engineer) 를 동시 디스패치한다. 세 coder 는 disjoint 트리(Views/ vs Services/ vs backend/)에 쓰므로 construction 상 충돌이 없다. 병렬 중에는 세 agent 가 하나의 marker 를 공유하므로 hook 이 개별 write 를 특정 agent 로 귀속시킬 수 없다 — 따라서 marker 의 `agent` 는 broadAccess 컨텍스트(`quality-engineer`)로 set 한다. pre-write guard 의 Phase 4 역할은 **forbidden floor**(`{appName}/Models/` + `.autobot` 제어 파일)를 세 agent 모두에게 강제하는 것이고(broadAccess 라도 floor 는 뚫지 못한다), **agent 간 디렉토리 OVERLAP 은 Gate 4→5 의 post-hoc `agent-sandbox.sh after` 가 정확히 검출**한다. 가장 제한적인 단일 agent 로 marker 를 set 하면 다른 두 coder 의 정당한 write 가 차단되므로 그렇게 하지 않는다.
8. Phase 완료 후 `pipeline.sh advance-phase --phase <N>` 으로 outgoing gate 실행 + 상태 마킹 + (성공 시) inputHash 자동 기록을 한 호출로 처리한다.
9. Gate 실패 시 `retryCount < maxRetry` 면 같은 Phase 재실행, 아니면 `failed` 마킹 후 Phase 7 로 점프.
10. Circuit breaker (3 연속 phase 실패 또는 에러 시그니처 2회 반복) 트립 시 Phase 7 만 진행.

## 학습 적용 (Phase 0 + 각 Phase 시작 시)

학습 로드 SSOT 는 `references/learning-bootstrap.md`. 핵심만 요약:

- Phase 별 파일 매핑: 1→`architecture.md`, 4→`parallel_coding.md`, 5→`quality.md`, 6→`deploy.md`, 그 외는 `active-learnings.md`
- 에이전트는 학습 적용 직후 `build-log.sh --event learning_applied` 호출 — Gate 4→5 의 `phase4_agents_consumed_learnings` 가 ui-builder/data-engineer 양쪽 기록을 강제로 검사한다 (누락 시 gate 거부)
- 회고에서 추출된 learning 의 효과 (helped / neutral / hurt) 는 `effect_score` 로 누적되어 hurt 누적 시 자동 quarantine

## Reference routing

- Use [Agent dispatch](references/agent-dispatch.md) when dispatching; avoid copying role instructions into prompt-tail.
- Use [Runtime commands and context paths](references/runtime-reference.md) when initializing state/locks or diagnosing optional tools.
- Use [Scaffold contract](references/scaffold-contract.md) in Phase 3. Phase 5 `no_stubs_in_app` protects production wiring.
- Use [Recovery](references/recovery.md) after a failure; spec retry limits remain authoritative.
- Use [Reporting](references/reporting.md) in Phase 7; write the current run summary and release with the originally owned lock token.

Keep status updates brief and outcome-based. Finish authorized phases through their required gate evidence; load later-phase references when reached. User instructions take precedence over skill guidelines. Run required checks, then repeat only affected checks after relevant changes or failures.
