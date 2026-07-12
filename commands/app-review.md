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

**Phase 별 세부 절차·스킵 게이트·실패 매트릭스의 SSOT 는 `$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/SKILL.md` 다.** 본 커맨드는 진입점이며 다음만 소유한다: (1) 상태머신 진입/이탈 (Step 0/1/3/4), (2) Phase F 선행 anti-laundering 게이트 (Step 2.5). Phase 본문을 여기 복제하지 마라 — 커맨드-스킬 문서 드리프트가 무인 완주를 이미 두 번 깨뜨렸다 (register 선행 누락, 연령등급 단계 누락).

## CRITICAL RULES

1. **`.autobot/build-state.json` 이 있어야 한다** — 없으면 "이 디렉토리는 Autobot 프로젝트가 아닙니다." 출력 후 중단.
2. **Phase 5 (Integration & Build) 완료 상태여야 한다** — 아니면 `/autobot:resume` 안내 후 중단.
3. **ASC API key 3종 필수** — `ASC_API_KEY_ID`, `ASC_API_ISSUER_ID`, `ASC_API_KEY_PATH`.
4. **질문 금지 (Auto Mode)** — 모든 결정은 `architecture.md` + `build-state.json` + `build-report.md` 에서 자동 도출. 하드 실패만 보고 후 중단.
5. **스크린샷은 App Store iPhone 사이즈 (6.9"/6.5"/6.3"/6.1") 만 다룬다.**
6. **상태 전이는 `scripts/pipeline.sh` 만** — Phase 6 의 일부로 취급. `start-phase --phase 6 --detail "App Review Submission"`.

## Step 0: 사전 검증

```bash
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi

P5=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('phases',{}).get('5',{}).get('status',''))")
if [ "$P5" != "completed" ]; then
  echo "ERROR: Phase 5 (Integration & Build) not completed (status: $P5)."
  echo "Run /autobot:resume to finish the build first."
  exit 1
fi

# ASC 자격증명: 전역(`~/.autobot/.env`, /autobot:setup 이 기록) → 프로젝트 .env 순 로드.
AUTOBOT_ENV_DIR="${AUTOBOT_CONFIG_DIR:-$HOME/.autobot}"
set -a
[ -f "$AUTOBOT_ENV_DIR/.env" ] && . "$AUTOBOT_ENV_DIR/.env"
[ -f .env ] && . .env
set +a
for v in ASC_API_KEY_ID ASC_API_ISSUER_ID ASC_API_KEY_PATH; do
  if [ -z "${!v:-}" ]; then
    echo "ERROR: $v missing. Set once via /autobot:setup (~/.autobot/.env) or per-project ./.env"
    echo "See: skills/autobot-upload-build/references/signing-guide.md"
    exit 1
  fi
done

BUNDLE_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('bundleId',''))")
DISPLAY_NAME=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('displayName',''))")
if [ -z "$BUNDLE_ID" ]; then
  echo "ERROR: bundleId missing in build-state.json. Run /autobot:setup."
  exit 1
fi
echo "INFO: app-review for $DISPLAY_NAME ($BUNDLE_ID)"
```

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

## Step 2: SKILL.md 의 phase 머신 실행

`$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/SKILL.md` 를 Read 하고 그 안의 phase 머신을 **문서 그대로** 실행한다: **Phase 0 → 0b → A → B → C → D-1 → D-2 → H → E → F → G**. 각 phase 는 멱등 — 이미 완료된 산출물은 SKILL.md 의 스킵 게이트가 건너뛴다. 단 하나의 예외: **Phase F(deployer 디스패치) 직전에 아래 Step 2.5 게이트를 먼저 통과시킨다.**

사용자-가시 요약 (전체 흐름 — 각 phase 의 실행 명령·분기표는 SKILL.md 참조):

| Phase | 하는 일 | 산출물 |
|-------|---------|--------|
| 0 | 사전 검증 (Step 0 과 동일 항목의 SKILL.md 판) | — |
| 0b | **ASC 앱 등록 선행** (멱등) — 앱 레코드 없이는 연령등급·metadata URL 이 적용되지 않아 첫 실행 원패스가 깨진다 | `.autobot/register-status.json` |
| A | 마케팅 컨텍스트 도출 (질문 없음) | `app-marketing-context.md` (프로젝트 루트) |
| B | 메타데이터 생성 + **연령등급 config (2b)** + ASC 업로드 — 이원 스킵 게이트 (`.txt` 존재와 `app_store_rating_config.json` 존재를 독립 검사) | `fastlane/metadata/` |
| C | 5-슬롯 스크린샷 narrative 계획 | `.autobot/screenshot-plan.md` |
| D-1 | 원본 캡쳐 (`ios-marketing-capture`, 없으면 자동 설치) | `marketing/<locale>/*.png` |
| D-2 | 4개 iPhone 사이즈 합성 (`app-store-screenshots`) | `fastlane/screenshots/<locale>/*.png` |
| H | AXI-Homepage 제품 등록 (신규 앱만 — 실패해도 E/F/G 진행) | `.autobot/homepage-status.json` |
| E | ASC 스크린샷 업로드 | `.autobot/screenshot-upload-status.json` |
| F | 바이너리 보장 — `deployer` 에이전트 (register→archive→upload). **Step 2.5 선행 필수** | `.autobot/archive-status.json`, `.autobot/upload-status.json` |
| G | 심사 제출 (PROCESSING 폴링 최대 30분 → deliver `--submit_for_review`) | `.autobot/review-submit-status.json` |

## Step 2.5: Phase F 진입 전 기능 검증 게이트 (anti-laundering)

deployer 디스패치 전에 Gate 5→6 을 신선하게 재실행한다. 정책 세부사항은 `spec/pipeline.json`과 `gate_checks.registry`가 소유한다; 이 명령 문서는 PASS 아니면 review 제출을 중단한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "5->6" || true

FUNC_STATUS=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('gates',{}).get('5->6',{}).get('status','missing'))")
if [ "$FUNC_STATUS" != "passed" ]; then
  echo "ERROR: functional verification not passed (gate 5->6 status: $FUNC_STATUS). Refusing to submit for review."
  [ "$FUNC_STATUS" = "degraded" ] && echo "       Functional flows UNVERIFIED — re-run /autobot:resume 5 on a host with simulator + axe + xcodebuild."
  exit 1
fi
echo "INFO: functional verification passed — proceeding with Phase F"
```

통과하면 SKILL.md Phase F(deployer 디스패치)로 진행한다. deployer 가 중단 사유(name_collision / bundle_id_taken / asc_session_expired / asc_permission_denied / signing failure / upload 실패)를 보고하면 진단을 사용자에게 표시하고 Phase G 를 진행하지 않는다.

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
Screenshots:      <COUNT> files × <LOCALES> locales — <SLOTS> slides × 4 sizes (6.9"/6.5"/6.3"/6.1")
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
