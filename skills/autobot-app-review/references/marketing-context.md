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
