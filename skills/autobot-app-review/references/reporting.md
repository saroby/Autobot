## Reporting (final output to user)

After all phases complete:

```
✅ App Store 리뷰 제출 완료

Bundle ID:        com.axi.MyApp
Display Name:     내 앱
Metadata:         5 fields × 1 locale (ko)
Screenshots:      5 files × 1 locale (ko) — 5 slides × 6.9" (1320×2868)
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
- `references/autonomy-touchpoints.md` — full inventory of every point the pipeline can halt (CLOSED / IRREDUCIBLE / CONDITIONAL). Read this to answer "does it run to review with zero human help?" — the honest answer is per-app autonomy is total; only account-level bootstrap + Apple's periodic agreement acceptance need a human.
- `scripts/upload-screenshots.sh` — fastlane deliver wrapper for screenshots-only upload
- `scripts/submit-for-review.sh` — build-processing poll + `fastlane deliver --submit_for_review` wrapper
- `scripts/check-review-status.sh` — on-demand post-submission verdict fetch → `.autobot/review-verdict.json`
- (age-rating config is written by Phase B into `fastlane/metadata/app_store_rating_config.json` and applied by `autobot-upload-metadata`)

## Integration with other Autobot commands

- **`/autobot:testflight`** — TestFlight-only deploy. App review is a strict superset (TestFlight upload + screenshots + metadata + review submission). Re-runs of `/autobot:app-review` after testflight will detect the existing upload and skip Phase F.
- **`/autobot:meta`** — Text metadata only. `/autobot:app-review` calls the same `autobot-generate-metadata` + `autobot-upload-metadata` skills under the hood, so artefacts are compatible.
- **`/autobot:mvp`** — Initial build. `/autobot:app-review` requires Phase 5 (build) completed; it does not run the MVP pipeline itself.
