---
name: app-review
description: "메타데이터·스크린샷·홈페이지 등록·빌드·심사 제출을 일괄 자동 수행합니다."
argument-hint: "(인자 없음 — 현재 디렉토리의 build-state.json 컨텍스트 사용)"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - Skill
---

# Autobot App Review — 메타·스크린샷·빌드·심사 제출 일괄 자동화

`/autobot:testflight` 로 TestFlight까지 갔다면 그 다음 자연스러운 단계. **ASC 앱 등록 선행 → 메타데이터(연령등급 포함) 생성/업로드 → 스크린샷 계획·캡쳐·합성 → ASC 업로드 → 심사 제출**까지 한 번에 수행한다.

**Phase 별 세부 절차·스킵 게이트·실패 매트릭스의 SSOT 는 `$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/SKILL.md` 다.** 본 커맨드는 상태머신 진입/이탈만 소유한다. 출하 anti-laundering은 archive 경계의 `pipeline.sh preflight-ship`이 소유한다. Phase 본문을 여기 복제하지 마라 — 커맨드-스킬 문서 드리프트가 무인 완주를 이미 두 번 깨뜨렸다 (register 선행 누락, 연령등급 단계 누락).

## CRITICAL RULES

1. **`.autobot/build-state.json` 이 있어야 한다** — 없으면 "이 디렉토리는 Autobot 프로젝트가 아닙니다." 출력 후 중단.
2. **Phase 5 (Integration & Build) 완료 상태여야 한다** — 아니면 `/autobot:resume` 안내 후 중단.
3. **ASC API key 3종 필수** — `ASC_API_KEY_ID`, `ASC_API_ISSUER_ID`, `ASC_API_KEY_PATH`.
4. **질문 금지 (Auto Mode)** — 모든 결정은 `architecture.md` + `build-state.json` + `build-report.md` 에서 자동 도출. 하드 실패만 보고 후 중단.
5. **스크린샷은 App Store iPhone 6.9" (1320×2868) 단일 사이즈만 다룬다.** 6.5"/6.3"/6.1" 을 함께 올리면 ASC 에서 각 슬라이드가 두 번 표시된다.
6. **상태 전이는 `scripts/pipeline.sh` 만** — Phase 6 의 일부로 취급. `start-phase --phase 6 --detail "App Review Submission"`.

## Step 0: 사전 검증

controller의 Phase 0 완료가 통합 출하 진단을 실행한다. 실패 결과에는
복구 방법이 구조화되어 있다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" app-review-controller init
```

Phase 0도 Step 2의 claim/complete 루프에서 실행한다. init 직후 미리 claim하지 않는다.

build-state, Phase 5, bundle identity, ASC 자격증명 검증은 controller Phase 0의
ship doctor가 단독 소유한다. command는 같은 조건을 다시 구현하지 않고 구조화된
실패 결과와 복구 안내만 표시한다.

## Step 1: Phase 6 진입

`/autobot:testflight` 와 같은 Phase 6 슬롯을 공유한다. 이미 testflight 가 통과해 Phase 6 가 completed 인 경우에도 본 커맨드는 멱등하게 재진입한다.

```bash
P6=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('phases',{}).get('6',{}).get('status','pending'))")
case "$P6" in
  pending|in_progress|failed|completed)
    bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" start-phase --phase 6 \
      --detail "App Review Submission (/autobot:app-review)" \
      --allow-terminal-restart
    ;;
esac
```

## Step 2: 실행형 phase controller 구동

상태 순서·재개·산출물 identity 판정의 SSOT는 `app_review_controller.py`다.
SKILL.md는 각 action의 실행 방법과 실패 원인만 제공한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" app-review-controller next
```

controller가 반환한 단 하나의 action과 `claimToken`을 보관하고, SKILL.md에서
action을 실행한 뒤 같은 token으로 결과를 기록한다. `action: busy`면 다른
세션이 해당 phase를 소유한 것이므로 실행하지 않는다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" app-review-controller complete \
  --phase '<PHASE>' --claim-token '<CLAIM_TOKEN>'
# 실패 시
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" app-review-controller fail \
  --phase '<PHASE>' --claim-token '<CLAIM_TOKEN>' --reason '<canonical reason>'
```

`next`가 `action: complete`를 반환할 때까지 반복한다. `action: halted` 면 종결이다 — controller 가 재시도 상한(3회) 또는 비재시도 실패(`name_collision` 등)로 해당 phase 를 정지시킨 것이므로, `reason` 과 복구 안내를 보고하고 루프를 끝낸다 (재claim 금지). controller는 **0 → 0b → A → B → C → D1 → D2 → H → E → F → G** 의존성을 강제하며, Phase F는 현재 `buildId`·`bundleId`와 digest가 모두 일치하는 upload status만 재사용한다.

사용자-가시 요약 (전체 흐름 — 각 phase 의 실행 명령·분기표는 SKILL.md 참조):

| Phase | 하는 일 | 산출물 |
|-------|---------|--------|
| 0 | 사전 검증 (Step 0 과 동일 항목의 SKILL.md 판) | — |
| 0b | **ASC 앱 등록 선행** (멱등) — 앱 레코드 없이는 연령등급·metadata URL 이 적용되지 않아 첫 실행 원패스가 깨진다 | `.autobot/register-status.json` |
| A | 마케팅 컨텍스트 도출 (질문 없음) | `app-marketing-context.md` (프로젝트 루트) |
| B | 메타데이터 생성 + **연령등급 config (2b)** + ASC 업로드 — 이원 스킵 게이트 (`.txt` 존재와 `app_store_rating_config.json` 존재를 독립 검사) | `fastlane/metadata/` |
| C | 5-슬롯 스크린샷 narrative 계획 | `.autobot/screenshot-plan.md` |
| D-1 | 원본 캡쳐 (`ios-marketing-capture`, 없으면 자동 설치) | `marketing/<locale>/*.png` |
| D-2 | 6.9" 단일 사이즈 합성 (`app-store-screenshots`) | `fastlane/screenshots/<locale>/*.png` (1320×2868) |
| H | AXI-Homepage 제품 등록 (신규 앱만 — 실패해도 E/F/G 진행) | `.autobot/homepage-status.json` |
| E | ASC 스크린샷 업로드 | `.autobot/screenshot-upload-status.json` |
| F | 바이너리 보장 — `deployer` 에이전트 (register→archive→upload). **Step 2.5 선행 필수** | `.autobot/archive-status.json`, `.autobot/upload-status.json` |
| G | 심사 제출 (PROCESSING 폴링 최대 30분 → deliver `--submit_for_review`) | `.autobot/review-submit-status.json` |

## Step 2.5: Phase F 진입 전 기능 검증 게이트 (anti-laundering)

Phase F의 deployer가 archive를 시작하면 `archive.sh`가 `pipeline.sh preflight-ship`으로 Gate 5→6의 fresh JSON 결과를 직접 판정한다. 이 command는 같은 gate를 선실행하거나 persisted status를 다시 해석하지 않는다. archive가 차단되면 deployer의 `preflight_ship_gate_failed`를 표시하고 Phase G를 진행하지 않는다.

## Step 3: Phase 6 advance

전 phase 가 통과했고 `.autobot/review-submit-status.json` 의 `result` 가 `submitted` 또는 `already_in_review` 면:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 6
```

실패면 `fail-phase --phase 6 --error "<reason>" --increment-retry`.

## Step 4: 사용자 보고

성공 시 (모든 phase 통과):

```
✅ App Store 리뷰 제출 완료

Bundle ID:        com.axi.MyApp
Display Name:     내 앱
Metadata:         <META_FIELDS> fields × <LOCALES> locales (+ age rating config)
Screenshots:      <COUNT> files × <LOCALES> locales — <SLOTS> slides × 6.9" (1320×2868)
Homepage:         https://axi-homepage.vercel.app/ko/products/<SLUG> (registered)   ← new apps only
Build:            v<VERSION> (<BUILD_NUMBER>) — VALID
Submission:       Waiting for Review (automatic release on approval)

다음 단계:
  https://appstoreconnect.apple.com → My Apps → App Store → Submissions
  심사 소요: 통상 24–48시간
```

부분 실패 시: 완료한 phase 와 실패한 phase + 복구 명령을 함께 보고.

## Error Handling

Phase 내부 실패 분기는 **SKILL.md 의 phase 별 failure matrix 가 SSOT** (Phase 0b register / B metadata / H homepage / E screenshots / G submit). 아래는 커맨드 수준 실패와, 무인 완주에 결정적인 복구 경로 요약만:

| 시점 | 증상 | 대응 |
|------|------|------|
| Step 0 | Phase 5 미완료 | `/autobot:resume` 안내 |
| Step 0 | ASC creds 누락 | `/autobot:setup` (~/.autobot/.env) 또는 프로젝트 `.env` 설정 안내 |
| Step 2.5 | gate 5->6 status != passed | 제출 거부. `degraded` 면 시뮬레이터/axe/xcodebuild 있는 호스트에서 `/autobot:resume 5` |
| Phase G | `build_processing_timeout` | 스크립트를 **1회 자동 재호출** (추가 30분 폴링). 재차 timeout 이면 보고 — 멱등이라 나중에 재실행 가능 |
| Phase G | `age_rating_missing` | **Phase B 재실행** — 이원 스킵 게이트가 rating config 부재를 독립 감지해 2b(작성)+업로드만 수행. ASC 웹 수동 입력은 최후 수단 |

## Output 파일

- `app-marketing-context.md` — Phase A
- `fastlane/metadata/` (locale `.txt` + root `.txt` + `app_store_rating_config.json`) — Phase B
- `.autobot/metadata-status.json`, `.autobot/metadata-upload-status.json` — Phase B
- `.autobot/screenshot-plan.md` — Phase C
- `marketing/<locale>/*.png` — Phase D-1 (원본 캡쳐)
- `fastlane/screenshots/<locale>/*.png` — Phase D-2 (모든 iPhone 사이즈)
- `.autobot/homepage-status.json` — Phase H (new apps only)
- `.autobot/screenshot-upload-status.json` — Phase E
- `.autobot/archive-status.json`, `.autobot/upload-status.json` — Phase F
- `.autobot/review-submit-status.json` — Phase G

이후 `/autobot:resume` 로 build-report.md 재생성 시 새 review 결과가 반영된다.

Do NOT ask any questions during execution. Auto Mode is mandatory. Only Step 0 precondition failures stop the run and they are reported clearly with the exact recovery command.
