---
name: autobot-app-review
description: Use when running the end-to-end App Store review submission pipeline for an Autobot project — generates ASO-optimized metadata (if `fastlane/metadata/` is empty), plans a screenshot narrative via `aso-skills:screenshot-optimization`, captures raw screens via the `ParthJadhav/ios-marketing-capture` skill, composites them into App Store-sized iPhone slides via `app-store-screenshots` at every required iPhone size (6.9"/6.5"/6.3"/6.1"), registers new apps on the AXI-Homepage product directory by pushing to `https://github.com/saroby/AXI-Homepage`, uploads metadata + screenshots + binary, and submits the version for App Review. Triggers on "submit for review", "app review", "앱 리뷰", "App Store 제출", "/autobot:app-review".
---

# Autobot App Review — Metadata + Screenshots + Submit

End-to-end orchestrator that takes an Autobot project from "build ready" to "submitted for App Store review". It composes seven autonomous phases. Each phase is idempotent — re-running the orchestrator skips work that is already done.

**Single responsibility:** orchestrate the submission pipeline. Each step delegates to a single-responsibility skill or shell script.

## When to use

- After `/autobot:testflight` succeeded but you want to push the same build to public review (not just TestFlight).
- When you have `fastlane/metadata/` already and just need screenshots + submission.
- When you have nothing and want metadata + screenshots + build + submission in one shot.
- For re-submission after rejection — re-running is safe.

## CRITICAL RULES

1. **`.autobot/build-state.json` must exist.** This skill is for Autobot projects only. Without it, exit early with "이 디렉토리는 Autobot 프로젝트가 아닙니다."
2. **No interactive Q&A.** Auto Mode applies — derive every answer from `architecture.md` + `build-state.json` + `build-report.md`. The only exception is hard precondition failures (missing ASC creds, missing bundle ID) where we ERROR + halt.
3. **ASC creds required.** Same three env vars as the rest of Autobot — `ASC_API_KEY_ID`, `ASC_API_ISSUER_ID`, `ASC_API_KEY_PATH` (App Manager role or higher).
4. **Build processing wait is bounded.** Submission cannot proceed while the latest build is `PROCESSING` on ASC. The submit script polls for up to 30 minutes; after timeout it ERRORs with a `--skip-wait` retry hint.
5. **Cross-plugin Q&A is bypassed by design.** `aso-skills:metadata-optimization`, `keyword-research`, and `screenshot-optimization` all start with "ask the user 5 questions" — invoking them via the Skill tool reliably triggers Q&A. Treat them as **reference material** the orchestrator-LLM reads inline (their character limits, slot frameworks, copy patterns are documented in this SKILL.md), not as Skill-tool calls. The two skills that *must* be Skill-invoked because they write files are `ios-marketing-capture` (writes Swift files + capture-marketing.sh) and `app-store-screenshots:app-store-screenshots` (scaffolds Next.js generator) — for these, pre-build `app-marketing-context.md` and pass an explicit "context populated; do not re-ask" preamble.
6. **iOS source modifications are scoped — but persistent.** `ios-marketing-capture` adds a `Debug/MarketingCapture.swift` file (DEBUG-gated) and modifies `ContentView.swift` (or root navigation host) to call into the coordinator. All changes are `#if DEBUG` so they have no release-build footprint. **WARN**: `/autobot:resume` regenerates Autobot-owned views via the codegen pipeline — if it regenerates `ContentView.swift`, the capture hook is lost. Record the touched files in `.autobot/app-review-status.json` so subsequent `/autobot:app-review` runs detect the lost hook and re-inject. (Mitigation: keep capture hooks in a separate `ContentView+Capture.swift` extension file when possible — see the ios-marketing-capture SKILL.md for the recommended layout.)

## Phase map

| Phase | Skill / Script | Output |
|-------|----------------|--------|
| **0. Precheck** | inline | env, build-state.json, ASC creds |
| **A. Marketing context** | inline | `app-marketing-context.md` |
| **B. Metadata** | `autobot-generate-metadata` + `autobot-upload-metadata` (only if `fastlane/metadata/` is empty/missing) | `fastlane/metadata/<locale>/*.txt` |
| **C. Screenshot plan** | `aso-skills:screenshot-optimization` (via Skill tool) | `.autobot/screenshot-plan.md` |
| **D-1. Raw capture** | `ParthJadhav/ios-marketing-capture` (via Skill tool, auto-install if absent) | `marketing/<locale>/*.png` |
| **D-2. Composite at all iPhone sizes** | `app-store-screenshots:app-store-screenshots` (via Skill tool) | `fastlane/screenshots/<locale>/*.png` at 4 iPhone sizes |
| **H. Homepage registration** (new apps only) | `scripts/register-on-homepage.sh` | AXI-Homepage `products.ts` updated + assets copied + pushed to origin/main |
| **E. Screenshot upload** | `scripts/upload-screenshots.sh` | ASC screenshots replaced |
| **F. Build upload** | `deployer` agent (`autobot-register-app` → `autobot-archive-build` → `autobot-upload-build`) | ASC binary uploaded |
| **G. Submit for review** | `scripts/submit-for-review.sh` | ASC version `Waiting for Review` |

## Phase 0 — Precheck

```bash
# (a) Autobot project
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi

# (b) Build completed (Phase 5)
P5=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('phases',{}).get('5',{}).get('status',''))")
[ "$P5" != "completed" ] && { echo "ERROR: Phase 5 (build) not completed (status: $P5). Run /autobot:resume."; exit 1; }

# (c) ASC creds
for v in ASC_API_KEY_ID ASC_API_ISSUER_ID ASC_API_KEY_PATH; do
  [ -z "${!v:-}" ] && { echo "ERROR: $v missing in .env"; exit 1; }
done

# (d) Bundle ID
BUNDLE_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('bundleId',''))")
[ -z "$BUNDLE_ID" ] && { echo "ERROR: bundleId missing — run /autobot:setup."; exit 1; }
```

Halt on any failure. Do not proceed to Phase A.

## Phase A — Marketing context derivation

Many of the cross-plugin skills (`aso-skills:metadata-optimization`, `aso-skills:keyword-research`, `aso-skills:screenshot-optimization`, `app-store-screenshots:app-store-screenshots`) check for `app-marketing-context.md` and otherwise ask 5+ questions. We pre-build the file so they have a single source of truth.

**Output path matters.** `aso-skills:app-marketing-context` looks for the file in **project root or `.claude/`** — *not* `.autobot/`. Write to `<project-root>/app-marketing-context.md` so the delegated skills find it without prompting.

**Inputs:**
- `.autobot/build-state.json` → `appName`, `displayName`, `bundleId`, `idea`
- `.autobot/architecture.md` → features, target audience, value proposition
- `.autobot/build-report.md` (if exists) → recent changes for release notes
- `~/.autobot/config.json` → `companyName` (copyright)

**Output:** `app-marketing-context.md` (at project root) matching the aso-skills `app-marketing-context` schema. Required sections:

```markdown
# App Marketing Context

## App Overview
- **App Name:** <displayName>
- **App ID (Apple):** <bundleId>
- **Category:** <derived primary category, e.g. PRODUCTIVITY>
- **Platform:** iOS
- **Price Model:** Free
- **Launch Date:** not yet launched
- **Current Version:** <derived from .autobot/build-state.json>

## Value Proposition
- **Problem:** <from architecture.md>
- **Target Audience:** <from architecture.md>
- **Unique Differentiator:** <from architecture.md>
- **Elevator Pitch:** <from architecture.md / idea>

## Top Features (priority order)
1. <feature 1 from architecture.md>
2. <feature 2>
3. ...

## Brand
- **Tone:** <inferred — clean/minimal default for Autobot scaffolds>
- **Colors:** <from architecture.md design notes or default Liquid Glass>
- **Font:** SF Pro (iOS system)
```

**Auto Mode policy:** if a field can't be derived, fill in a reasonable default and mark it `(auto-derived)`. Do not ask the user.

## Phase B — Metadata (only if missing)

Detect:

```bash
META_DIR="fastlane/metadata"
META_COUNT=0
if [ -d "$META_DIR" ]; then
  META_COUNT=$(find "$META_DIR" -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
fi
```

**If `META_COUNT > 0`:** skip Phase B. Log `INFO: metadata already exists ($META_COUNT files) — keeping existing content`.

**If empty:**

0. **Derive the canonical AXI-Homepage product URL** before drafting copy. Slug is `<lowercased displayName, kebab-case>` (e.g. `MyApp` → `myapp`). Canonical URL:

   ```
   marketing_url = https://axi.dev/products/<slug>
   support_url   = https://axi.dev/products/<slug>
   privacy_url   = (omit; ASC won't require it for the first submission unless the app collects data — Autobot scaffolds do not by default)
   ```

   These URLs are pre-deployed on AXI-Homepage by Phase H. Phase H runs *after* Phase B/D-2 in the orchestration order, but the URL is predictable (slug-derived) so we can write it into metadata now and Phase H ensures the page exists before Apple review begins.

1. **ASO-informed drafting (orchestrator-LLM, no Skill invocation).** Apply the principles documented in `aso-skills:metadata-optimization` and `aso-skills:keyword-research` directly — do **not** Skill-invoke them (they trigger Q&A). Key rules to follow inline:
   - Title (30 chars): lead with keyword if brand unknown, lead with brand if known. Format like `<Brand>: <Primary Keyword>`.
   - Subtitle (30 chars): never repeat title keywords. Benefit-driven.
   - Keyword field (100 chars total): comma-separated, **no spaces** after commas, singular forms only, no repeats with title/subtitle. Maximize coverage.
   - Description (4000 chars): first 3 lines are the App Store list hook. Then feature bullets + use cases.
   - Promotional text (170 chars): short hook, can change post-release.
   - Release notes (4000 chars): user-perspective changes from `build-report.md`. First release: "첫 공개" 류.

   Derive keyword candidates from `architecture.md`'s feature list + value proposition + target audience. Pick the top 6-10 that fit in the keyword field budget.

2. **Generate via Autobot's metadata pipeline** — feed the ASO-optimized drafts into the existing `autobot-generate-metadata` JSON contract (which enforces ASC character limits atomically):

   ```bash
   cat > /tmp/autobot-meta-$$.json <<JSON
   {
     "locales": {
       "ko": { "name": "...", "subtitle": "...", "description": "...",
               "keywords": "...", "promotional_text": "...", "release_notes": "..." }
     },
     "root": { "copyright": "© 2026 <companyName>", "primary_category": "<derived>" }
   }
   JSON

   AUTOBOT_METADATA_STATUS_FILE=.autobot/metadata-status.json \
   bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-generate-metadata/scripts/write-metadata.sh" \
     --metadata-json "/tmp/autobot-meta-$$.json" \
     --output-dir fastlane/metadata
   rm -f "/tmp/autobot-meta-$$.json"
   ```

   On `result: failed` with `reason: field=X len=N max=M`, shorten the offending field (LLM responsibility, max 2 retries), then re-call.

3. **Upload immediately** — Phase B always uploads to ASC right after writing files, so Phase G's `--submit_for_review` has all required metadata in place:

   ```bash
   AUTOBOT_METADATA_UPLOAD_STATUS_FILE=.autobot/metadata-upload-status.json \
   bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh" \
     --bundle-id "$BUNDLE_ID" \
     --metadata-path fastlane/metadata
   ```

   Failure handling — same `reason` matrix as `/autobot:meta`. `app_not_registered` → fall through to Phase F's register step (the testflight register pattern), then retry upload.

## Phase C — Screenshot plan

The orchestrator-LLM applies `aso-skills:screenshot-optimization` principles inline — do **not** Skill-invoke (that would prompt Q&A). The principles to apply:

- **Slot 1 = The Hook.** Benefit headline + key UI. "Does this solve my problem?" answered in 3 seconds. Avoid welcome/login/settings.
- **Slots 2-3 = Core Value.** Top 2 features with benefit-driven captions (not feature names).
- **Slots 4-N = Feature showcase.** One feature per slide. `[Benefit Headline] + [Feature UI] + [Supporting Detail]`.
- **Last slot = Trust/Closing.** "Made for [audience]" or a clear differentiator.

Output a 5-slot plan derived from `app-marketing-context.md`'s top features + value proposition. Persist to `.autobot/screenshot-plan.md` (atomic write). This file becomes the input contract for Phase D-1 (which screens to capture) and Phase D-2 (which headlines to overlay).

**Slot defaults** (used if the optimizer fails to produce a plan):

| Slot | Headline | Screen |
|------|----------|--------|
| 1 | Elevator pitch (from context) | Home / main view |
| 2 | Top feature #1 | Feature screen |
| 3 | Top feature #2 | Feature screen |
| 4 | Top feature #3 | Feature screen |
| 5 | "Made for [target audience]" | Hero / closing screen |

## Phase D-1 — Raw screenshot capture via `ios-marketing-capture`

Use the **`ParthJadhav/ios-marketing-capture`** skill — an in-app SwiftUI capture system (not XCUITest) that builds the app once, then relaunches per locale to produce reproducible PNGs.

### Auto-install if missing

```bash
SKILL_PATH="$HOME/.claude/skills/ios-marketing-capture"
if [ ! -d "$SKILL_PATH" ]; then
  log_info "ios-marketing-capture skill not found — cloning from GitHub"
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 https://github.com/ParthJadhav/ios-marketing-capture "$SKILL_PATH"
  else
    echo "ERROR: git is required to install ios-marketing-capture. Install git or run: npx skills add ParthJadhav/ios-marketing-capture"
    exit 1
  fi
fi
```

### Drive the skill

Load `$SKILL_PATH/SKILL.md` via the Skill tool. The skill itself asks for 6 inputs — supply all of them inline from the screenshot plan + build-state.json:

| Skill question | Auto-supplied value |
|----------------|---------------------|
| Screens to capture | From `.autobot/screenshot-plan.md` slot list |
| Isolated elements | None (skip — App Store screenshots only need full screens, not isolated components) |
| Locales | `ko` (and `en-US` if `app-marketing-context.md` flags international) |
| Device | `iPhone 17 Pro Max` (6.9" — captures at the largest required ASC size, downscaled by Phase D-2) |
| Appearance | `light` (single appearance; second submission can vary) |
| Seed data | Detect via `grep -lE 'previewData\|DemoData\|PreviewProvider'` in `.autobot/architecture.md`'s referenced files. If unknown: default to "fresh install seeds it automatically" — Autobot scaffolds include seed data |

**Critical**: when invoking the skill via the Skill tool, prefix the user message with:
> Context: this is an automated Autobot run. Pre-derived answers live in `.autobot/screenshot-plan.md` and `app-marketing-context.md`. Do not ask follow-up questions — read the files and proceed. Use defaults for any unspecified value.

### Run the capture script

The skill writes `scripts/capture-marketing.sh` at the project root, populated with the project's BUNDLE_ID, SCHEME, locales, etc.

```bash
bash scripts/capture-marketing.sh
```

Output: `marketing/<locale>/01-home.png`, `02-feature.png`, ... (full-screen PNGs at the simulator's native resolution).

**If capture fails:**
- Build failure → re-run `/autobot:resume` to fix the build first.
- Simulator unavailable → ERROR with the device install hint from the script.
- Sentinel timeout → the capture coordinator didn't finish — log + ERROR with retry hint.

## Phase D-2 — Composite at all required iPhone sizes

Use **`app-store-screenshots:app-store-screenshots`** (Skill-invoke — this one scaffolds a Next.js project, so it must run) to take `marketing/<locale>/*.png` (raw simulator captures) + the app icon + brand colors and composite them into Apple-style ad slides with headlines, gradients, and device mockups, exported at **every required iPhone size**.

### Generator location

`.autobot/screenshots-generator/` (gitignored — already covered by `.autobot/` in `.gitignore`).

### Required export sizes

The `app-store-screenshots` skill's `IPHONE_SIZES` array must include all four sizes.

| Display Size | Pixels (portrait) | Required by ASC |
|--------------|-------------------|------------------|
| 6.9" | 1320×2868 | Yes (universal — accepted by every iPhone) |
| 6.5" | 1284×2778 | Yes (older devices fallback) |
| 6.3" | 1206×2622 | Yes |
| 6.1" | 1125×2436 | Yes |

### Drive the skill

Load `app-store-screenshots:app-store-screenshots` via the Skill tool with directive:
> Context: this is an automated Autobot run. Pre-derived answers live in `.autobot/screenshot-plan.md` (slide narrative + headlines) and `app-marketing-context.md` (brand, colors, font, audience). Raw captures live in `./marketing/<locale>/`. App icon is at `<appIconPath>` (from `autobot-app-icon` output). **Do not ask follow-up questions** — use the files. Generator scaffolds to `.autobot/screenshots-generator/`. **Target: Apple App Store iPhone only.** Export every iPhone size in `IPHONE_SIZES` (6.9"/6.5"/6.3"/6.1") for every locale. Output naming: `<locale>/<NN>_<slot-name>.png` written into `fastlane/screenshots/<locale>/` so fastlane's deliver step picks them up.

**Filename convention** (required by fastlane deliver):
- `01_hero.png`, `02_feature.png`, ... — numeric prefix determines ASC slot order
- Fastlane auto-detects the display family from pixel dimensions (1320×2868 → 6.9", etc.), so all four sizes can live in the same locale directory

### Verify output

```bash
IPHONE_SIZE_COUNT=4   # 6.9", 6.5", 6.3", 6.1"
EXPECTED_SHOTS_PER_LOCALE=$((SLOT_COUNT * IPHONE_SIZE_COUNT))

ACTUAL=$(find fastlane/screenshots -mindepth 2 -name "*.png" -type f | wc -l | tr -d ' ')
EXPECTED_TOTAL=$((EXPECTED_SHOTS_PER_LOCALE * LOCALE_COUNT))
if [ "$ACTUAL" -lt "$EXPECTED_TOTAL" ]; then
  echo "WARN: only $ACTUAL/$EXPECTED_TOTAL screenshots generated. Proceeding — fastlane will accept partial sets."
fi
```

Don't hard-fail on partial output; fastlane accepts incomplete sets — ASC will mark missing sizes as "needs attention" but still allows submission for the largest supplied size.

## Phase H — Register on AXI-Homepage (new apps only)

A new iOS app needs a public marketing URL that Apple can verify during review. We register the product on `https://github.com/saroby/AXI-Homepage` by inserting an entry into `src/data/products.ts`, copying icon + screenshots to `public/`, and pushing to `origin/main`. The homepage repo's deployment is handled externally — the orchestrator's responsibility ends at the git push.

### Detect new vs existing

```bash
HOMEPAGE_REPO="${AUTOBOT_HOMEPAGE_REPO:-$HOME/Code/AXI/AXI-Homepage}"
SLUG="$(python3 -c "import sys, re; s=sys.argv[1]; print(re.sub(r'[^a-z0-9-]', '', re.sub(r'(?<!^)(?=[A-Z])', '-', s).lower()))" "$DISPLAY_NAME")"

IS_NEW=1
if [ -d "$HOMEPAGE_REPO/.git" ]; then
  (cd "$HOMEPAGE_REPO" && git fetch origin main --quiet 2>/dev/null) || true
  if [ -f "$HOMEPAGE_REPO/src/data/products.ts" ] && grep -Eq "slug:[[:space:]]*\"$SLUG\"" "$HOMEPAGE_REPO/src/data/products.ts"; then
    IS_NEW=0
  fi
fi
```

If `IS_NEW=0` → skip Phase H (product already registered). Phase B's `marketing_url` is already correct.

If `IS_NEW=1` → run Phase H.

### Build the product JSON

Derive from `app-marketing-context.md` + `architecture.md` + `build-state.json` + the icon Autobot generated in Phase 3 (`autobot-app-icon`) + the largest-size screenshots from `fastlane/screenshots/<primary-locale>/`.

```bash
# Find the largest iPhone size set (6.9" = 1320×2868) for the primary locale.
PRIMARY_LOCALE="ko"
SHOTS_DIR="fastlane/screenshots/$PRIMARY_LOCALE"
HERO_SHOTS=$(find "$SHOTS_DIR" -name "*.png" -type f | sort | head -3 | python3 -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin]))")

# App icon — autobot-app-icon writes the master 1024x1024 to a known path.
ICON_PATH=$(python3 -c "
import json, pathlib
s = json.load(open('.autobot/build-state.json'))
p = s.get('appIconPath') or '.autobot/app-icon-1024.png'
print(pathlib.Path(p).resolve())
")

# App Store ID — from the deployer's register-app status. Fall back to a
# generic 'apps.apple.com' search URL if id is unknown (rare — register
# step runs before Phase G submission).
APP_STORE_ID=$(python3 -c "
import json, pathlib
p = pathlib.Path('.autobot/register-status.json')
if p.exists():
    print(json.load(p.open()).get('app_store_id', '') or '')
" 2>/dev/null)
if [ -n "$APP_STORE_ID" ]; then
  DOWNLOAD_URL="https://apps.apple.com/app/id${APP_STORE_ID}"
else
  DOWNLOAD_URL="https://axi.dev/products/${SLUG}"
fi
```

Compose the JSON (orchestrator-LLM responsibility — content comes from the marketing context):

```json
{
  "slug": "<slug>",
  "name": { "ko": "<displayName ko>", "en": "<displayName en>" },
  "tagline": { "ko": "<subtitle from metadata>", "en": "..." },
  "description": { "ko": "<elevator pitch + 2 paragraphs from architecture.md>", "en": "..." },
  "features": { "ko": ["<feat1>", "<feat2>", "<feat3>"], "en": [...] },
  "platform": "iOS",
  "systemRequirements": "iOS 26.0+",
  "techStack": ["Swift 6", "SwiftUI", "iOS 26"],
  "downloadUrl": "<DOWNLOAD_URL>",
  "downloadLabel": { "ko": "App Store에서 다운로드", "en": "Download on the App Store" },
  "iconPath": "<ICON_PATH>",
  "screenshots": <HERO_SHOTS>
}
```

Write to `/tmp/autobot-homepage-product.json`.

### Run the registration script

```bash
AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE=.autobot/homepage-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/register-on-homepage.sh" \
  --product-json /tmp/autobot-homepage-product.json
rm -f /tmp/autobot-homepage-product.json
```

The script:
1. Clones AXI-Homepage to `$HOME/Code/AXI/AXI-Homepage` if not present
2. Validates JSON schema
3. Inserts the product object into `src/data/products.ts` (before the closing `];` — TS-aware insertion)
4. Copies the icon to `public/icons/<slug>.png`
5. Copies the first 3 screenshots to `public/screenshots/<slug>/01..03.png`
6. `git commit` + `git push origin main`
7. Writes `.autobot/homepage-status.json` with the canonical URL

### Status file contract

```json
{
  "result": "registered" | "already_exists" | "no_op" | "committed_no_push" | "dry_run" | "failed",
  "slug": "myapp",
  "canonical_url": "https://axi.dev/products/myapp",
  "commit_sha": "abc1234...",
  "reason": "<error reason if result=failed>",
  ...
}
```

### Failure handling

| `reason` | Meaning | Recovery |
|----------|---------|----------|
| `clone_failed` | No SSH access to `git@github.com:saroby/AXI-Homepage.git` | Verify SSH key in GitHub. Or pre-clone the repo to `$HOME/Code/AXI/AXI-Homepage` |
| `dirty_worktree` | The local AXI-Homepage clone has uncommitted changes | Stash or commit them; re-run |
| `products_ts_mutation_failed` | Couldn't parse / insert into products.ts | products.ts schema changed — update the script's regex / Python helper |
| `git_commit_failed` | git commit failed for non-trivial reason | Check git log / hooks |
| `git_push_failed` | Push rejected (auth, remote diverged, etc.) | Resolve in the homepage repo; the local commit is preserved. Re-push manually |
| `nothing_to_commit` | Same content already committed (race) | Treat as success |

Phase H failure does **not** block Phase E/F/G unless the marketing URL is critically required. Continue and report Phase H failure in the final summary — Apple won't reject a missing marketing_url unless the description references it. A failed Phase H means manual homepage edit later.

## Phase E — Upload screenshots to ASC

```bash
AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE=.autobot/screenshot-upload-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/upload-screenshots.sh" \
  --bundle-id "$BUNDLE_ID" \
  --screenshots-path fastlane/screenshots
```

Failure matrix:

| `reason` | Meaning | Recovery |
|----------|---------|----------|
| `app_not_registered` | App missing on ASC | Run Phase F first (build upload includes register), then retry |
| `screenshot_size_invalid` | Pixel dimensions don't match any ASC display family | Re-run Phase D-2 — generator config drift |
| `auth_failed` | API key wrong | Verify `.env` |
| `asc_state_locked` | Existing version in review | Check ASC web — wait for current review to complete or use the same in-review version |

## Phase F — Ensure binary on ASC

If the current `build-state.json` indicates the build has not been uploaded yet (no `.autobot/upload-status.json` with `result: uploaded`), dispatch the **`deployer` agent** — the same agent `/autobot:testflight` uses. The deployer chains `autobot-register-app` → `autobot-archive-build` → `autobot-upload-build` → `autobot-invite-testers` with the proper error contracts (`name_collision`, `bundle_id_taken`, `api_key_insufficient_role` halt before any expensive archive work).

```
Agent(
  description: "Ensure ASC binary",
  subagent_type: "deployer",
  prompt: "Ensure the latest build is on App Store Connect. App: <DISPLAY_NAME>, bundle: <BUNDLE_ID>.
           Re-running is safe — register is idempotent (already_exists is silent success).
           If .autobot/upload-status.json already shows result=uploaded for the current archive,
           do nothing and report so. Otherwise run register → archive → upload.
           invite-testers is optional — skip unless config.json:testerEmails is populated."
)
```

The deployer writes `.autobot/register-status.json`, `archive-status.json`, `upload-status.json` (atomic). On any halt (name_collision / bundle_id_taken / api_key_insufficient_role / signing failure / upload 5xx), surface the deployer's diagnostic to the user and stop the orchestrator — do not proceed to Phase G.

**Skip Phase F entirely** if `.autobot/upload-status.json` exists with `result: uploaded` and its timestamp is newer than the iOS source tree's most recent mtime. Heuristic check:

```bash
SKIP_F=0
if [ -f .autobot/upload-status.json ]; then
  RESULT=$(python3 -c "import json; print(json.load(open('.autobot/upload-status.json')).get('result',''))" 2>/dev/null)
  if [ "$RESULT" = "uploaded" ]; then
    NEWER=$(find . -path ./.autobot -prune -o -path ./build -prune -o -path ./fastlane -prune -o -path ./marketing -prune -o -name "*.swift" -newer .autobot/upload-status.json -print 2>/dev/null | head -1)
    [ -z "$NEWER" ] && SKIP_F=1
  fi
fi
```

## Phase G — Submit for review

```bash
AUTOBOT_REVIEW_SUBMIT_STATUS_FILE=.autobot/review-submit-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/submit-for-review.sh" \
  --bundle-id "$BUNDLE_ID"
```

The script polls for up to 30 minutes for the build to leave PROCESSING, then submits with these defaults (matching Autobot's standard scaffold):

```json
{
  "export_compliance_uses_encryption": false,
  "content_rights_contains_third_party_content": false,
  "content_rights_has_rights": true,
  "add_id_info_uses_idfa": false
}
```

These match `ITSAppUsesNonExemptEncryption=false` (Autobot's mandatory contract — see `CONVENTIONS.md`) and "no AdSupport/ATT framework" (Autobot scaffold doesn't add either). If the orchestrator detects either deviation (e.g. `architecture.md` mentions analytics SDK with IDFA), pass the appropriate `--uses-idfa` / `--uses-encryption` flag.

`automatic_release` is on by default — once approved, the app goes live without manual intervention. To hold for manual release, pass `--no-auto-release`.

Failure matrix:

| `reason` | Meaning | Recovery |
|----------|---------|----------|
| `build_processing_timeout` | Build still PROCESSING after 30 min | Re-run later (cheaper) or `bash submit-for-review.sh --bundle-id <id> --skip-wait` if you've verified the build is VALID in ASC web |
| `build_not_ready` | Submission tried but no VALID build attached | Wait, retry |
| `missing_metadata_or_screenshots` | Required fields/screenshots missing on ASC | Re-run Phase B + E to push the missing data |
| `age_rating_missing` | ASC age rating questionnaire unanswered | Manual one-time step in ASC web → re-run |
| `export_compliance_question` | Encryption answer mismatch | Verify `ITSAppUsesNonExemptEncryption` in Info.plist; pass `--uses-encryption` if needed |
| `already_in_review` | Version already submitted | Treated as success (exit 0) |

## Reporting (final output to user)

After all phases complete:

```
✅ App Store 리뷰 제출 완료

Bundle ID:        com.axi.MyApp
Display Name:     내 앱
Metadata:         5 fields × 1 locale (ko)
Screenshots:      20 files × 1 locale (ko) — 5 slides × 4 sizes (6.9"/6.5"/6.3"/6.1")
Build:            v1.0 (123) — VALID
Submission:       Waiting for Review
Auto-release:     ON (released immediately upon approval)

다음 단계:
  https://appstoreconnect.apple.com → My Apps → App Store → Submissions
  심사 소요 시간: 보통 24-48시간
```

On partial failure, report what completed + what failed + the recovery command. Never claim success unless `.autobot/review-submit-status.json` shows `result: submitted` or `already_in_review`.

## Status files written by this skill

| File | Phase | Producer |
|------|-------|----------|
| `<project-root>/app-marketing-context.md` | A | inline (required location for aso-skills lookup) |
| `.autobot/metadata-status.json` | B (write) | `autobot-generate-metadata/scripts/write-metadata.sh` |
| `.autobot/metadata-upload-status.json` | B (upload) | `autobot-upload-metadata/scripts/upload-metadata.sh` |
| `.autobot/screenshot-plan.md` | C | inline (from `aso-skills:screenshot-optimization` output) |
| `marketing/<locale>/*.png` | D-1 | `ios-marketing-capture` skill |
| `fastlane/screenshots/<locale>/*.png` | D-2 | `app-store-screenshots` skill |
| `.autobot/screenshot-upload-status.json` | E | `scripts/upload-screenshots.sh` |
| `.autobot/archive-status.json`, `upload-status.json` | F | existing `autobot-archive-build`, `autobot-upload-build` |
| `.autobot/review-submit-status.json` | G | `scripts/submit-for-review.sh` |
| `.autobot/app-review-status.json` | summary | inline (final aggregator) |

## Auto Mode rules (recap)

- Never ask the user clarifying questions during phases B–G. Use defaults derived from the marketing context.
- The only ASK is the one Autobot already documents: hard precondition failures (Phase 0) get reported and the run halts.
- Every delegated skill is given the directive "context exists at `app-marketing-context.md`; do not re-ask" — if a delegated skill still tries to interact, override its behavior and proceed with defaults.

## Files in this skill

- `SKILL.md` — this orchestrator contract
- `scripts/upload-screenshots.sh` — fastlane deliver wrapper for screenshots-only upload
- `scripts/submit-for-review.sh` — build-processing poll + `fastlane deliver --submit_for_review` wrapper

## Integration with other Autobot commands

- **`/autobot:testflight`** — TestFlight-only deploy. App review is a strict superset (TestFlight upload + screenshots + metadata + review submission). Re-runs of `/autobot:app-review` after testflight will detect the existing upload and skip Phase F.
- **`/autobot:meta`** — Text metadata only. `/autobot:app-review` calls the same `autobot-generate-metadata` + `autobot-upload-metadata` skills under the hood, so artefacts are compatible.
- **`/autobot:mvp`** — Initial build. `/autobot:app-review` requires Phase 5 (build) completed; it does not run the MVP pipeline itself.
