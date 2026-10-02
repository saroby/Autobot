## Phase B — Metadata (dual skip gate)

Detect — **two independent checks**. The `.txt` count says nothing about the age-rating config: a `/autobot:meta`-produced tree can have text metadata without `app_store_rating_config.json`, and skipping step 2b for it deterministically halts Phase G with `age_rating_missing`.

```bash
META_DIR="fastlane/metadata"
META_COUNT=0
if [ -d "$META_DIR" ]; then
  META_COUNT=$(find "$META_DIR" -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
fi
RATING_CONFIG_PRESENT=0
[ -f "$META_DIR/app_store_rating_config.json" ] && RATING_CONFIG_PRESENT=1
```

- **`META_COUNT > 0` and `RATING_CONFIG_PRESENT == 1`:** skip Phase B entirely. Log `INFO: metadata already exists ($META_COUNT files) — keeping existing content`.
- **`META_COUNT > 0` and `RATING_CONFIG_PRESENT == 0`:** keep the existing `.txt` files — run **step 2b only** (write the rating config), then **step 3** (upload). Both are idempotent.
- **`META_COUNT == 0`:** full run — all steps below.

**Full run steps:**

0. **Derive the canonical AXI-Homepage URLs** before drafting copy. Slug is `<lowercased displayName, kebab-case>` (e.g. `MyApp` → `myapp`). AXI-Homepage is a Next.js site with `[locale]` routing, deployed on Vercel:

   ```
   marketing_url = https://axi-homepage.vercel.app/ko/products/<slug>
   support_url   = https://axi-homepage.vercel.app/ko/products/<slug>   # same as marketing_url
   privacy_url   = https://axi-homepage.vercel.app/en/privacy           # fixed shared privacy page
   ```

   - **marketing_url == support_url** — both point at the app's own product page. Phase H registers the product on AXI-Homepage so `/ko/products/<slug>` exists (route `src/app/[locale]/products/[slug]`).
   - **privacy_url is fixed** — the shared `/en/privacy` page (route `src/app/[locale]/privacy`), not slug-specific. Always include it: ASC requires a privacy policy URL on submission, and a valid shared page satisfies it whether or not the app collects data.

   Phase H runs *after* Phase B/D-2 in the orchestration order, but the product URL is predictable (slug-derived) so we write it into metadata now, and Phase H ensures the page exists before Apple review begins. The `/en/privacy` page is already deployed (not per-app), so it needs no Phase H work.

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
               "keywords": "...", "promotional_text": "...", "release_notes": "...",
               "marketing_url": "https://axi-homepage.vercel.app/ko/products/<slug>",
               "support_url": "https://axi-homepage.vercel.app/ko/products/<slug>",
               "privacy_url": "https://axi-homepage.vercel.app/en/privacy" }
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

2b. **Write the age-rating config** — this is what makes the pipeline reach review with **zero manual ASC-web step**. Without it, Phase G halts on `age_rating_missing`. `autobot-upload-metadata` auto-detects `fastlane/metadata/app_store_rating_config.json` and passes it to `fastlane deliver` (which answers the ASC age-rating questionnaire in the same call). Always write it before the upload:

   ```bash
   cat > fastlane/metadata/app_store_rating_config.json <<'JSON'
   {
     "alcoholTobaccoOrDrugUseOrReferences": "NONE",
     "contests": "NONE",
     "gamblingSimulated": "NONE",
     "gunsOrOtherWeapons": "NONE",
     "horrorOrFearThemes": "NONE",
     "matureOrSuggestiveThemes": "NONE",
     "medicalOrTreatmentInformation": "NONE",
     "profanityOrCrudeHumor": "NONE",
     "sexualContentGraphicAndNudity": "NONE",
     "sexualContentOrNudity": "NONE",
     "violenceCartoonOrFantasy": "NONE",
     "violenceRealistic": "NONE",
     "violenceRealisticProlongedGraphicOrSadistic": "NONE",
     "advertising": false,
     "ageAssurance": false,
     "gambling": false,
     "healthOrWellnessTopics": false,
     "lootBox": false,
     "messagingAndChat": false,
     "parentalControls": false,
     "unrestrictedWebAccess": false,
     "userGeneratedContent": false
   }
   JSON
   ```

   **Every** ASC age-rating field is declared explicitly — 13 content-descriptor enums (`NONE`) + 9 capability booleans (`false`). Do not omit any: ASC treats an omitted field as *unanswered*, which re-triggers `age_rating_missing` and halts submission. This is the clean **4+ / no-objectionable-content** answer set — correct for a default Autobot scaffold. Keys are the modern App Store Connect API keys; fastlane 2.235.0 passes modern `camelCase`-key + string-enum / JSON-boolean values through unchanged (verified against `map_key_from_itc` / `map_value_from_itc`), and auto-maps legacy iTunesConnect keys with a deprecation warning. **Derive-adjust from `architecture.md`** only when the app genuinely has flagged content: set `unrestrictedWebAccess: true` for an in-app browser / arbitrary web content, `messagingAndChat: true` or `userGeneratedContent: true` for user-to-user messaging or UGC feeds, `advertising: true` if the app shows ads, `healthOrWellnessTopics: true` for health/fitness content, and the relevant `violence*` / `gamblingSimulated` / `matureOrSuggestiveThemes` enum to `INFREQUENT_OR_MILD` or `FREQUENT_OR_INTENSE` for apps that surface such content. When unsure, keep the no-content default — an under-declared rating is an App Review rejection, so only raise a field on clear evidence.

3. **Upload immediately** — Phase B always uploads to ASC right after writing files, so Phase G's `--submit_for_review` has all required metadata in place:

   ```bash
   AUTOBOT_METADATA_UPLOAD_STATUS_FILE=.autobot/metadata-upload-status.json \
   bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-upload-metadata/scripts/upload-metadata.sh" \
     --bundle-id "$BUNDLE_ID" \
     --metadata-path fastlane/metadata
   ```

   Failure handling — same `reason` matrix as `/autobot:meta`. `app_not_registered` → fall through to Phase F's register step (the testflight register pattern), then retry upload.
