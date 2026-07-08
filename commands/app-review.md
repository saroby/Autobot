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

`/autobot:testflight` 로 TestFlight까지 갔다면 그 다음 자연스러운 단계. **메타데이터 생성/업로드 → 스크린샷 narrative 계획 → 원본 캡쳐(ios-marketing-capture) → 모든 iPhone 사이즈 합성(app-store-screenshots) → ASC 업로드 → 심사 제출**까지 한 번에 수행한다.

상세 contract 는 `skills/autobot-app-review/SKILL.md` 를 따른다. 본 커맨드는 진입점이며 동일 phase 머신을 그대로 실행한다.

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

## Step 2: `skills/autobot-app-review/SKILL.md` 의 Phase A–G 수행

다음 순서로 진행한다. 각 단계는 멱등이며 이미 완료된 산출물이 있으면 건너뛴다.

### Phase A — Marketing context (`<project-root>/app-marketing-context.md`)

`.autobot/build-state.json` + `architecture.md` (+ `build-report.md` if exists) 를 읽어 `aso-skills:app-marketing-context` 스키마로 작성한다. **경로는 반드시 프로젝트 루트** (또는 `.claude/`) — `aso-skills:*` 가 그 두 위치에서만 파일을 찾으므로 `.autobot/` 에 두면 Q&A 폴백이 발동된다. 모든 필드는 자동 도출 (질문 금지). `companyName` 은 `bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh" get-or companyName ''` 로 가져온다.

### Phase B — Metadata (조건부)

```bash
META_COUNT=0
if [ -d fastlane/metadata ]; then
  META_COUNT=$(find fastlane/metadata -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
fi
```

**`META_COUNT == 0` 일 때만**:

0. **Canonical homepage URL 도출 (slug-based)** — slug 는 `displayName` 의 kebab-case 변환. `marketing_url` = `support_url` = `https://axi-homepage.vercel.app/ko/products/<slug>` (동일), `privacy_url` = `https://axi-homepage.vercel.app/en/privacy` (고정 공유 페이지, 항상 포함). 제품 페이지는 Phase H 가 push 로 생성(route `[locale]/products/[slug]`); privacy 는 앱별이 아닌 고정 페이지라 Phase H 불필요. URL 은 slug 만으로 결정되므로 metadata 작성 시점에 미리 채워 둠.

1. **ASO 원칙을 inline 으로 적용** (`aso-skills:*` 를 Skill 도구로 로드하지 않는다 — 그 스킬들은 5-question Q&A 로 시작). 적용 규칙:
   - title (30자): brand 인지도 낮으면 키워드 우선, 높으면 brand 우선
   - subtitle (30자): title 키워드 반복 금지, benefit-driven
   - keywords (100자 total): comma-separated, 공백 없음, 단수형, title/subtitle 미중복
   - description (4000자): 첫 3줄 = App Store 리스트 hook, 이후 기능 bullet + 시나리오
   - keyword 후보는 `architecture.md` 의 feature/value proposition/target audience 에서 도출
2. 위 원칙으로 title/subtitle/keywords/description/promotional_text/release_notes 초안 작성.
3. `autobot-generate-metadata/scripts/write-metadata.sh` 로 atomic 작성 (길이 한도 enforce — 위반 시 LLM 이 줄여 최대 2회 재시도).
4. `autobot-upload-metadata/scripts/upload-metadata.sh` 로 ASC 즉시 업로드.

**`META_COUNT > 0` 일 때**: Phase B 전체 스킵. 기존 파일을 그대로 사용. 다만 ASC 업로드 이력이 없으면 (`metadata-upload-status.json` 없음) 업로드만 실행.

### Phase C — Screenshot plan (`.autobot/screenshot-plan.md`)

`aso-skills:screenshot-optimization` 원칙을 inline 으로 적용 (스킬 로드 금지 — Q&A 발동). 5-슬롯 narrative 구성:

| Slot | 역할 | 원칙 |
|------|------|------|
| 1 | The Hook | benefit headline + 핵심 UI ("이 앱이 내 문제를 해결해?" 3초 안에 답) |
| 2-3 | Core Value | 핵심 기능 #1, #2 — benefit-driven caption (기능명 X) |
| 4 | Feature showcase | 기능 #3 — `[benefit] + [UI] + [supporting detail]` |
| 5 | Trust/Closing | "Made for [target audience]" 또는 차별점 |

`app-marketing-context.md` 의 top features + value proposition 에서 각 slot 의 headline 과 어느 화면 (architecture.md 의 view 이름) 을 보여줄지 결정. 결과를 `.autobot/screenshot-plan.md` 로 원자적 기록 — Phase D-1 (어느 화면 캡쳐) 과 Phase D-2 (어느 headline overlay) 의 입력 contract.

### Phase D-1 — Raw capture via `ParthJadhav/ios-marketing-capture`

```bash
SKILL_PATH="$HOME/.claude/skills/ios-marketing-capture"
if [ ! -d "$SKILL_PATH" ]; then
  echo "INFO: cloning ios-marketing-capture skill"
  git clone --depth 1 https://github.com/ParthJadhav/ios-marketing-capture "$SKILL_PATH"
fi
```

`$SKILL_PATH/SKILL.md` 를 읽고 (Read 도구 또는 Skill 호출) 그 안의 워크플로우를 다음 자동 응답으로 진행:
- **Screens**: `.autobot/screenshot-plan.md` 의 슬롯 리스트
- **Isolated elements**: none
- **Locales**: `ko` (international audience 표시 시 `en-US` 추가)
- **Device**: `iPhone 17 Pro Max` (6.9" 캡쳐 — 합성 단계에서 작은 사이즈로 다운스케일)
- **Appearance**: `light`
- **Seed data**: Autobot 스캐폴드는 기본 시드 포함 — "fresh install seeds it automatically"

스킬이 `MarketingCapture.swift` + `scripts/capture-marketing.sh` 를 생성하면 즉시 실행:

```bash
bash scripts/capture-marketing.sh
```

출력: `marketing/<locale>/*.png`.

### Phase D-2 — Composite at all iPhone sizes via `app-store-screenshots:app-store-screenshots`

`app-store-screenshots:app-store-screenshots` 를 Skill 도구로 로드. 디렉티브:
> Context: automated Autobot run. Pre-derived inputs at `.autobot/screenshot-plan.md` (slides), `app-marketing-context.md` (brand). Raw captures at `./marketing/<locale>/`. App icon at `<derived from autobot-app-icon output>`. Generator scaffolds to `.autobot/screenshots-generator/`. Target: iPhone App Store only. Export every iPhone size in `IPHONE_SIZES` (6.9"/6.5"/6.3"/6.1") per locale. Output: `<locale>/<NN>_<slot>.png` under `fastlane/screenshots/`. Do not ask questions — use the files.

검증:

```bash
ACTUAL=$(find fastlane/screenshots -mindepth 2 -name "*.png" -type f | wc -l | tr -d ' ')
if [ "$ACTUAL" -eq 0 ]; then
  echo "ERROR: no screenshots generated under fastlane/screenshots/. Check .autobot/screenshots-generator/ build logs."
  exit 1
fi
echo "INFO: $ACTUAL screenshots ready under fastlane/screenshots/"
```

### Phase H — Register on AXI-Homepage (new apps only)

새 앱이면 `https://github.com/saroby/AXI-Homepage` 의 `src/data/products.ts` 에 제품 entry 를 삽입하고 icon + 스크린샷을 `public/` 에 복사한 뒤 `origin/main` 으로 push 한다. push 이후의 배포는 homepage 레포가 외부에서 처리.

**Slug 도출 + 신규 여부 판정**:

```bash
HOMEPAGE_REPO="${AUTOBOT_HOMEPAGE_REPO:-$HOME/Code/AXI/AXI-Homepage}"
SLUG="$(python3 -c "
import re, sys
s = sys.argv[1]
# CamelCase → kebab-case (간이 변환)
s = re.sub(r'(?<!^)(?=[A-Z])', '-', s).lower()
s = re.sub(r'[^a-z0-9-]+', '-', s).strip('-')
print(s)
" "$DISPLAY_NAME")"

IS_NEW=1
if [ -f "$HOMEPAGE_REPO/src/data/products.ts" ] && \
   grep -Eq "slug:[[:space:]]*\"$SLUG\"" "$HOMEPAGE_REPO/src/data/products.ts"; then
  IS_NEW=0
  echo "INFO: '$SLUG' already on homepage — skipping Phase H"
fi
```

`IS_NEW == 1` 일 때만 진행:

1. **Product JSON 작성 (LLM 책임)** — `app-marketing-context.md` + `architecture.md` + `build-state.json` + 메타데이터 + 합성된 스크린샷 + autobot-app-icon 의 1024×1024 마스터에서 도출. App Store ID 가 `.autobot/register-status.json` 에 있으면 `downloadUrl = "https://apps.apple.com/app/id<ASID>"`, 아직 모르면 canonical homepage URL 로 fallback.

   ```json
   {
     "slug": "<SLUG>",
     "name": {"ko": "<displayName>", "en": "<English displayName>"},
     "tagline": {"ko": "<from subtitle>", "en": "..."},
     "description": {"ko": "<elevator + 2 paragraphs>", "en": "..."},
     "features": {"ko": ["<feat1>","<feat2>","<feat3>"], "en": [...]},
     "platform": "iOS",
     "systemRequirements": "iOS 26.0+",
     "techStack": ["Swift 6","SwiftUI","iOS 26"],
     "downloadUrl": "<App Store URL or homepage fallback>",
     "downloadLabel": {"ko": "App Store에서 다운로드", "en": "Download on the App Store"},
     "iconPath": "<absolute path to 1024 master>",
     "screenshots": ["<abs path 01>","<abs path 02>","<abs path 03>"]
   }
   ```

   `/tmp/autobot-homepage-product.json` 에 저장.

2. **등록 스크립트 호출**:

   ```bash
   AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE=.autobot/homepage-status.json \
   bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/register-on-homepage.sh" \
     --product-json /tmp/autobot-homepage-product.json
   rm -f /tmp/autobot-homepage-product.json
   ```

3. **결과 분기 (`.autobot/homepage-status.json` 의 `result`)**:

   - `registered` → Phase E 계속
   - `already_exists` → no-op, Phase E 계속
   - `committed_no_push` (--no-push 사용 시) → 사용자에게 manual push 안내
   - `failed (reason=clone_failed)` → SSH 키 안내, 그래도 Phase E 계속 (marketing_url 은 metadata 에 이미 적힘 — 사람이 나중에 homepage 수정 가능)
   - `failed (reason=git_push_failed)` → 로컬 commit 보존 안내, Phase E 계속
   - 기타 `failed` → 로그 첨부, Phase E 계속

Phase H 실패는 **Phase E/F/G 를 막지 않는다**. Apple 은 marketing_url 이 누락되어도 reject 하지 않는다 (description 에서 URL 을 직접 언급하지 않는 한). 사용자 보고서에는 Phase H 실패를 명시.

### Phase E — Upload screenshots to ASC

```bash
AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE=.autobot/screenshot-upload-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/upload-screenshots.sh" \
  --bundle-id "$BUNDLE_ID" \
  --screenshots-path fastlane/screenshots
```

실패 분기는 SKILL.md 의 failure matrix 그대로. `app_not_registered` 면 Phase F 먼저 후 재시도.

### Phase F — 빌드가 ASC 에 없으면 deployer 에이전트 디스패치

### Phase F-0 — 기능 검증 사전 차단 (anti-laundering)

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

`/autobot:testflight` 와 동일한 패턴. **`deployer`** 에이전트 (`agents/deployer.md`) 가 `autobot-register-app` → `autobot-archive-build` → `autobot-upload-build` (→ optional `autobot-invite-testers`) 를 chain 한다. register 는 멱등이며 archive/upload 도 status 파일로 중복 작업을 방지한다.

```bash
NEED_UPLOAD=1
if [ -f .autobot/upload-status.json ]; then
  RESULT=$(python3 -c "import json; print(json.load(open('.autobot/upload-status.json')).get('result',''))" 2>/dev/null)
  if [ "$RESULT" = "uploaded" ]; then
    # 소스가 status 파일 이후로 바뀌지 않았으면 스킵
    NEWER=$(find . -path ./.autobot -prune -o -path ./build -prune -o -path ./fastlane -prune -o -path ./marketing -prune -o -name "*.swift" -newer .autobot/upload-status.json -print 2>/dev/null | head -1)
    [ -z "$NEWER" ] && NEED_UPLOAD=0
  fi
fi
```

`NEED_UPLOAD == 1` 이면 `Agent` 도구로 deployer 디스패치:

```
Agent(
  description: "Ensure ASC binary",
  subagent_type: "deployer",
  prompt: "Ensure the latest build is on App Store Connect for App: <DISPLAY_NAME> (bundle: <BUNDLE_ID>).
           Re-running is safe — register is idempotent. If upload-status.json shows result=uploaded
           for the current archive and no Swift source is newer, report and skip.
           Otherwise run register → archive → upload. invite-testers is optional —
           run only if config.json:testerEmails is populated."
)
```

Deployer 가 `name_collision` / `bundle_id_taken` / `api_key_insufficient_role` / signing failure / upload 5xx 로 중단되면 진단을 사용자에게 표시하고 Phase G 를 진행하지 않는다.

### Phase G — Submit for review (빌드 processing 폴링 포함)

```bash
AUTOBOT_REVIEW_SUBMIT_STATUS_FILE=.autobot/review-submit-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/submit-for-review.sh" \
  --bundle-id "$BUNDLE_ID"
```

스크립트가 자체적으로 최대 30분 동안 60초 간격으로 `fastlane pilot builds` 폴링하여 빌드가 PROCESSING → VALID 로 전이될 때까지 대기 후, `fastlane deliver --submit_for_review` 를 호출한다. 기본 submission information:

- `export_compliance_uses_encryption: false` (Autobot scaffold 의 `ITSAppUsesNonExemptEncryption=false` 와 일치)
- `content_rights_contains_third_party_content: false`
- `content_rights_has_rights: true`
- `add_id_info_uses_idfa: false` (Autobot scaffold 가 AdSupport 미포함)
- `automatic_release: true` — 승인 즉시 공개

`architecture.md` 가 위 가정에서 벗어남을 명시하는 경우만 `--uses-encryption` / `--uses-idfa` / `--no-auto-release` 등을 전달한다.

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
Metadata:         <META_FIELDS> fields × <LOCALES> locales
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

| 시점 | 증상 | 대응 |
|------|------|------|
| Step 0 | Phase 5 미완료 | `/autobot:resume` 안내 |
| Step 0 | ASC creds 누락 | `.env` 설정 안내 |
| Phase B | metadata 길이 초과 | write-metadata.sh 가 잡음 — LLM 재작성 (max 2회) |
| Phase B | `app_not_registered` | Phase F register 먼저 실행 후 재시도 |
| Phase D-1 | 캡쳐 빌드 실패 | `/autobot:resume` 안내, 원인 진단 |
| Phase D-1 | 시뮬레이터 없음 | capture-marketing.sh 가 자동 생성 시도, 그래도 실패면 ERROR |
| Phase D-2 | 산출물 0건 | `.autobot/screenshots-generator/` 빌드 로그 확인 |
| Phase E | `screenshot_size_invalid` | Phase D-2 재실행 |
| Phase G | `build_processing_timeout` | 잠시 후 재실행 (idempotent) |
| Phase G | `missing_metadata_or_screenshots` | ASC 웹 확인 — Phase B/E 재실행 |
| Phase G | `age_rating_missing` | ASC 웹에서 등급 답변 수동 입력 후 재실행 |

## Output 파일

- `app-marketing-context.md` — Phase A
- `fastlane/metadata/<locale>/*.txt` + `fastlane/metadata/*.txt` — Phase B
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
