---
name: autobot-app-review
user-invocable: false
description: "Run App Store review submission or check its verdict for an Autobot project (/autobot:app-review)."
---

# Autobot App Review

Run `scripts/pipeline.sh app-review-controller next`; retain its `claimToken` and return `complete`/`fail` for the claimed phase. `busy` means another session owns the work. `halted` is terminal: report the reason and stop. The controller owns ordering, retries, and completion; never infer a skip from timestamps.

Read only the claimed phase's reference below. Resolve project paths from the project root and existing `scripts/` paths within this skill from `$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/`. Do not preload future phases or invoke ASO reference skills through the Skill tool.

## CRITICAL RULES

1. **`.autobot/build-state.json` must exist.** This skill is for Autobot projects only. Without it, exit early with "이 디렉토리는 Autobot 프로젝트가 아닙니다."
2. **No interactive Q&A.** Auto Mode applies — derive every answer from `architecture.md` + `build-state.json` + `build-report.md`. The only exception is hard precondition failures (missing ASC creds, missing bundle ID) where we ERROR + halt.
3. **ASC creds required.** Same three credentials as the rest of Autobot — `APP_STORE_CONNECT_API_KEY_KEY_ID`, `APP_STORE_CONNECT_API_KEY_ISSUER_ID`, `APP_STORE_CONNECT_API_KEY_KEY_FILEPATH` (App Manager role or higher), resolved as inherited env → project `.env` → `~/.autobot/.env` (every deploy script sources `scripts/release_env.sh`; validation is owned by the controller Phase 0 ship doctor).
4. **Build processing wait is bounded.** Submission cannot proceed while the latest build is `PROCESSING` on ASC. The submit script polls for up to 30 minutes; after timeout it ERRORs with a `--skip-wait` retry hint.
5. **Cross-plugin Q&A is bypassed by design.** Apply `aso-skills` metadata, keyword, and screenshot guidance inline from the current phase reference. Skill-invoke `ios-marketing-capture` and `app-store-screenshots:app-store-screenshots` when their phase writes files; supply the prebuilt `app-marketing-context.md` with "context populated; do not re-ask".
6. **iOS source modifications are scoped — but persistent.** `ios-marketing-capture` adds a `Debug/MarketingCapture.swift` file (DEBUG-gated) and modifies `ContentView.swift` (or root navigation host) to call into the coordinator. All changes are `#if DEBUG` so they have no release-build footprint. **WARN**: `/autobot:resume` regenerates Autobot-owned views via the codegen pipeline — if it regenerates `ContentView.swift`, the capture hook is lost. Record the touched files in `.autobot/app-review-status.json` so subsequent `/autobot:app-review` runs detect the lost hook and re-inject. (Mitigation: keep capture hooks in a separate `ContentView+Capture.swift` extension file when possible — see the ios-marketing-capture SKILL.md for the recommended layout.)

## Phase routing

| Controller phase | Reference | Output |
|------------------|-----------|--------|
| 0 | [Precheck](references/precheck.md) | Current build and ship prerequisites |
| 0b | [Register](references/register.md) | ASC app record; halt on auth/name/bundle failures |
| A | [Marketing context](references/marketing-context.md) | app-marketing-context.md |
| B | [Metadata](references/metadata.md) | Localized text plus independent age-rating config gate |
| C | [Screenshot plan](references/screenshot-plan.md) | Apply ASO guidance inline; no Skill Q&A |
| D1 | [Capture](references/capture.md) | DEBUG capture hooks and raw screenshots |
| D2 | [Composite](references/composite.md) | 6.9-inch iPhone PNGs, 1320×2868 only |
| H | [Homepage](references/homepage.md) | New-app registration within existing authorization |
| E | [Screenshot upload](references/screenshot-upload.md) | ASC screenshots |
| F | [Build upload](references/build-upload.md) | Recognize uploaded/already_uploaded |
| G | [Submit](references/submit.md) | ASC review state |
| On demand | [Review verdict](references/review-verdict.md) | Approved/rejected/waiting evidence |
| End/halt | [Report](references/reporting.md) | Status files and concise user outcome |
