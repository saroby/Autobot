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
  DOWNLOAD_URL="https://axi-homepage.vercel.app/ko/products/${SLUG}"
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
  "canonical_url": "https://axi-homepage.vercel.app/ko/products/myapp",
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
