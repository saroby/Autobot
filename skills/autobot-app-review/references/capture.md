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
| Seed data | Read `seedPolicy` from `.autobot/architecture.json`. `"seeded"` → a fresh install auto-populates the primary screen via data-engineer's `seedIfNeeded` (capture directly). `"empty"` (todo/journal) → a fresh install is intentionally blank; drive the primary flow to create a few entries before capturing so screenshots aren't empty. Missing field (legacy build) → capture as-is. |

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
