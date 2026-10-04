---
name: autobot-orchestrator
user-invocable: false
description: "Run or resume the full Autobot iOS build pipeline and coordinate phase recovery (/autobot:mvp, /autobot:resume)."
---

# Autobot Orchestrator

Phase 0–7 dispatcher. **`spec/pipeline.json`**이 Phase·상태 전이·retry·gate의 SSOT다. 상태 변경·gate·lifecycle 로그는 `scripts/pipeline.sh`만 사용하며 build-state를 직접 편집하지 않는다. 명령/README/이 스킬과 충돌하면 spec을 따른다.

권한: 로컬 생성·수정·빌드·테스트·archive·재시도는 autonomous; 선택 도구(Stitch/fastlane/ASC/Axiom) 미설치는 warn/fallback. 원격 저장소 생성/푸시·외부 비가역 변경은 확인이 필요하며 기본 파이프라인에서 제외한다.

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

세부 검증은 [phase-gates.md](references/phase-gates.md).

## Dispatcher

1. `.autobot/build-state.json`에서 가장 작은 `pending` 또는 `failed (retry < maxRetry)` Phase를 선택한다. `manual:true`는 자율 흐름에서 skip한다: 2.5는 `/autobot:plan`, 6은 `/autobot:testflight` / `/autobot:app-review`만 실행한다. MVP는 2→3, 5→7로 진행한다.
2. Phase 1 직전 self-step **market-brief**: mcp-appstore가 가용하면 `search_app→get_similar_apps→analyze_reviews`로 `.autobot/market-brief.json`을 쓴다: `{generatedAt,source:"mcp-appstore",similarApps:[{name,notableFeatures:[]}],tableStakes:[],complaintThemes:[],opportunityGaps:[],noDirectCompetitors}`. 직접 경쟁앱 없음은 `noDirectCompetitors:true`; 미가용은 파일 작성 soft-skip 후 architect의 WebSearch fallback에 맡긴다(hard fail/DEGRADED 아님).
3. `phases.<id>.agents`가 있으면 `Agent(subagent_type=...)`, 없으면 self로 수행한다. Phase 4 backend-engineer는 `backend_required == true`일 때만 dispatch한다.
4. 각 dispatch 직전에 context-pack을 생성해 프롬프트 **첫 블록**에 그대로 붙인다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" context-pack \
  --phase 4 --agent ui-builder \
  --prompt-tail "$AGENT_SPECIFIC_FREE_TEXT" --format text
```

Phase·agent는 현재 작업에 맞춘다. Pack은 spec slice·output contract·required input 경로를 전달한다. 8KB는 soft budget이며 초과해도 계약을 자르지 않는다. 정적 지시는 `agents/*.md`, 학습은 learning-bootstrap이 소유한다; prompt-tail에는 이번 실패 원인 등 동적 정보만 넣는다.

5. 모델: 빌드당 1회 `detect-peer-ai.sh --format env`의 `runtimeHost`를 캐시한다. Claude host만 [agent-dispatch.md](references/agent-dispatch.md)의 Model Routing 표를 적용한다(architect/quality-engineer=`opus`, coder/보조=`sonnet`). codex/unknown은 `model`을 생략해 호스트 모델을 상속한다. Agent frontmatter에 모델을 고정하지 않는다.
6. Sandbox는 **사전 guard와 사후 snapshot 검증 둘 다** 필요하다:

```bash
# dispatch 직전
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox set-active --agent <name> --phase <N>
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent <name> --app-name <App>
# agent 완료 직후
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent <name> --app-name <App> --phase <N>
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox clear-active
```

`set-active`는 PreToolUse write 차단, `before/after`는 Gate 4→5 `sandbox_clean`의 `agentsVerified` 증거다. `before` 누락 후 사후 snapshot을 만들어 빈 diff/0 violations로 통과시키지 않는다. 누락했다면 Phase 시작 이후 변경을 `fileOwnership`과 독립 대조하고 실제 감사 근거를 보고한다.

7. Two-step Phase: **3**은 self `create-xcode-project.sh` 직후 `design-system` 단일 dispatch; **2**는 `ux-designer` 직후 `.autobot/app-icon-1024.png`가 없으면 self `autobot-app-icon` 실행. Gate 2→3의 `app_icon_source_present`가 필수다. 각 Phase의 두 단계 완료 뒤 advance한다.
8. Phase 4는 **한 메시지에서** ui-builder + data-engineer (+조건부 backend-engineer)를 병렬 dispatch한다. 쓰기 트리는 Views/·Services/·backend/로 분리한다. 공유 marker는 broadAccess `quality-engineer`로 set하고, 각 coder에 `before/after` 검증을 수행한다. Pre-write guard는 모든 coder에 `{appName}/Models/`와 `.autobot` 제어 파일의 forbidden floor를 강제한다. Agent 간 directory overlap은 post-hoc sandbox가 검출한다. 제한적인 단일 coder marker로 다른 coder의 정당한 write를 차단하지 않는다.
9. 완료는 `pipeline.sh advance-phase --phase <N>` 한 호출로 outgoing gate·상태·성공 inputHash를 기록한다. 실패는 spec retry 한도 내 같은 Phase 재실행; 소진하면 failed 처리 후 Phase 7로 인계한다. Circuit breaker(3 연속 phase 실패 / 동일 signature 2회 반복)가 트립하면 Phase 7만 진행한다.

## 학습 (Phase 0 + 각 Phase 시작)

[learning-bootstrap.md](references/learning-bootstrap.md)를 따른다.

- Phase 별 파일 매핑: 1→`architecture.md`, 4→`parallel_coding.md`, 5→`quality.md`, 6→`deploy.md`, 그 외는 `active-learnings.md`
- 적용 직후 `build-log.sh --event learning_applied` 기록. Gate 4→5의 `phase4_agents_consumed_learnings`가 ui-builder/data-engineer 양쪽을 검사한다.
- 회고에서 helped/neutral/hurt 효과를 `effect_score`에 누적하고 hurt 누적 learning을 quarantine한다.

## Reference routing

- [Agent dispatch](references/agent-dispatch.md): dispatch·file ownership·model routing.
- [Runtime commands and context paths](references/runtime-reference.md): 상태/lock 초기화·선택 도구 진단.
- [Scaffold contract](references/scaffold-contract.md): Phase 3. Phase 5 `no_stubs_in_app`는 production wiring을 검증한다.
- [Recovery](references/recovery.md): 실패 진단·복구; retry 한도는 spec 우선.
- [Reporting](references/reporting.md): Phase 7 run summary와 **원래 획득한 lock token** 해제.

현재 단계의 reference만 읽는다. 승인된 Phase와 필수 gate 증거까지 완료하고 결과를 간결하게 보고한다. 사용자 지시가 우선이며, 통과한 검사는 관련 변경/실패가 생긴 경우에만 영향 범위를 재실행한다.
