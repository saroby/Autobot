---
name: plan
description: "앱 아이디어를 입력하면 Phase 0–2 (기획 + UX 디자인 + 아이콘) 까지만 빌드하고 Phase 2.5 에서 정지. designs/preview/index.html 을 브라우저로 자동 열어 코드 생성 전에 기획·디자인을 검토하게 한다. 만족하면 /autobot:resume 으로 Phase 3 부터 이어갈 수 있다."
argument-hint: "<앱 아이디어 설명>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
  - TaskCreate
  - TaskUpdate
  - TaskList
  - WebSearch
  - WebFetch
---

# Autobot Plan — 한 줄 아이디어 → 기획·디자인 HTML 미리보기

> **이 문서는 진입점이다. 실행하지 않는다.**
> Phase 정의·상태 전이·Gate·Retry 의 SSOT 는 **`spec/pipeline.json`**, 실행 절차는 **`autobot-orchestrator` 스킬**과 **`autobot-plan-preview` 스킬**이 소유한다.

- **입력** — 앱 아이디어 한 줄
- **결과물** — `.autobot/designs/preview/index.html` (모바일 프레임 갤러리 + 기획 요약 + nav flow + 토큰 swatch + 아이콘 + **LLM critique**) + 브라우저 자동 표면화

`/autobot:plan <아이디어>` 는 **Phase 0 → 1 → 2 → 2.5** 까지만 실행하고 정지한다. Phase 3 이후 (코드 생성, 통합 빌드, TestFlight) 는 사용자가 검토 후 `/autobot:resume` 또는 `/autobot:mvp` 로 명시 트리거.

## 왜 이 명령이 있는가

mvp 자율 흐름의 약점은 architect / ux-designer 의 **첫 패스** 결과를 사람 검토 없이 Phase 3–5 가 그대로 코드로 변환하는 것이다. 잘못된 기획·디자인 위에 5분간 코드를 만들고 나서야 발견하면 모두 폐기. preview HTML 은 코드 생성 전 검토 가능한 가장 빠른 surface — Xcode + 시뮬레이터 + Run 의 사람 개입 없이도, 비기술 stakeholder 까지도, 화면 단위로 평가할 수 있다.

이 명령이 잡으려는 두 실패 모드:
1. **컨셉 오해** — architect 가 사용자 아이디어를 잘못 해석 → critique 의 "기획" 축이 잡음
2. **시각 / HIG 실패** — Stitch 가 generic / 접근성 미달 / iOS 답지 않은 디자인 생성 → critique 의 "디자인" 축이 잡음

## CRITICAL RULES

1. **자율 실행**: 로컬 파일 생성·수정·빌드·재시도 는 묻지 않고 진행한다 (mvp 와 동일).
2. **Phase 2.5 정지**: Phase 2.5 의 HTML 빌드 + 브라우저 열기까지 마치면 멈춘다. Phase 3 자동 진입 금지.
3. **상태는 runtime 으로만 기록**: `.autobot/build-state.json` 직접 편집 금지. `scripts/pipeline.sh` 경로만 사용한다.
4. **CWD 고정**: Phase 0 에서 생성한 프로젝트 디렉토리가 CWD. 에이전트/스크립트는 모두 상대 경로.

## Safety Policy

mvp 와 동일한 3 tier (`autonomous` / `warn` / `require_confirmation`).

## 실행 흐름

`autobot-orchestrator` 스킬을 invoke 한다. Phase 2.5 는 spec 에서 `manual: true` 라 dispatcher 가 자동 흐름에서는 skip 한다. 이 명령은 그 skip 을 prose 가 아닌 **명시적 step enumeration** 으로 override 한다 — 아래 7 step 을 그대로 실행한다.

| # | Step | 비고 |
|---|------|------|
| 1 | orchestrator 의 dispatcher 로 Phase 0 → 1 → 2 를 표준 흐름대로 진행 | 각 phase 의 `start-phase` / `advance-phase` 자동 |
| 2 | Phase 2 가 `completed` 또는 `fallback` 으로 마킹 확인 | `build-state.json` 검사 |
| 3 | `bash scripts/pipeline.sh start-phase --phase 2.5 --detail "Plan preview"` | dispatcher 의 manual-skip 을 우회하는 **명시적** 진입 |
| 4 | `autobot-plan-preview` 스킬 invoke | 스킬이 `build-preview.sh` + 멀티모달 critique + HTML 주입 + `open` 모두 수행 |
| 5 | `bash scripts/pipeline.sh advance-phase --phase 2.5 --metadata preview_html_path=.autobot/designs/preview/index.html` | gate 2.5→3 (file_exists) 검증 + 상태 마킹 |
| 6 | `bash scripts/pipeline.sh build-lock release` | Phase 7 의 `write-run-summary` 에 도달하지 않으므로 명시적 release 필요. 생략 시 다음 세션의 PID-liveness 가 reclaim 하지만 첫 명령에서 "build in progress" 경고 가능 |
| 7 | **STOP** — Phase 3 자동 진입 금지. 완료 보고 출력 후 사용자 결정 대기 |

각 phase 의 gate 실행, error recovery, retry 정책은 spec 과 orchestrator 가 소유한다.

## /autobot:plan 이 트리거하지 않는 것

| 하지 않는 것 | 트리거 |
|---|---|
| Phase 3–5 (Xcode scaffold + 병렬 코드 + 통합 빌드) | `/autobot:resume` 또는 `/autobot:mvp` |
| Phase 6 (TestFlight) | `/autobot:testflight` |
| Phase 7 (회고) | mvp 흐름의 마지막에 자동 |
| App Store 메타데이터 / 심사 제출 | `/autobot:meta` / `/autobot:app-review` |

## 검토 후 다음 액션

사용자가 brower 에서 `designs/preview/index.html` 을 본 뒤 다음 중 하나로 결정을 표현한다:

| 결정 | 다음 명령 |
|---|---|
| 기획·디자인 OK → 코드 생성 진입 | `/autobot:resume` (input-hash 가 Phase 1·2 자동 skip → Phase 3 부터) |
| 디자인만 다시 받기 | `/autobot:resume 2 --force` — Phase 2 의 input-hash skip 을 우회하고 ux-designer 재실행 후 `/autobot:resume 2.5 --force` 로 preview 재생성. (그냥 `/autobot:plan` 재호출은 input-hash 가 Phase 1·2 를 skip 해서 같은 HTML 이 다시 뜬다 — 의도와 어긋남) |
| 기획부터 다시 | `/autobot:resume 1 --force` — architect 재실행. 그 다음 자동으로 Phase 2 가 신선한 architecture 로 재실행, preview 도 갱신 |
| 폐기 | 새 디렉토리에서 `/autobot:plan <새 아이디어>` |

## 중단 / 실패 시

`/autobot:resume 2.5` 로 Phase 2.5 부터 재실행. Phase 1·2 산출물은 보존.

## 완료 보고

스킬이 Phase 2.5 까지 마치면 다음을 1 화면으로 출력한다:

- 앱 이름·식별자·번들 ID
- 프로젝트 경로
- preview HTML 경로 + 브라우저 자동 열림 안내
- critique 항목 수 (high / medium / low / positive)
- 검토 후 다음 액션 안내 (위 표 그대로)

failure 시 (architecture.md 없음 / design-spec 없음 등) `autobot-plan-preview` 스킬의 Failure Modes 표대로 안내.
