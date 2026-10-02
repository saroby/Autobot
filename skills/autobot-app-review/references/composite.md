## Phase D-2 — Composite at the required iPhone size

Use **`app-store-screenshots:app-store-screenshots`** (Skill-invoke — this one scaffolds a Next.js project, so it must run) to take `marketing/<locale>/*.png` (raw simulator captures) + the app icon + brand colors and composite them into Apple-style ad slides with headlines, gradients, and device mockups, exported at **the single required iPhone size (6.9")**.

### Generator location

`.autobot/screenshots-generator/` (gitignored — already covered by `.autobot/` in `.gitignore`).

### Required export size — one size only

Apple (2025+) requires **only the 6.9" iPhone screenshot** (1320×2868). ASC
displays it on every iPhone, so no smaller size is needed.

> **Why one size, not four:** uploading multiple iPhone sizes (6.5"/6.3"/6.1")
> alongside 6.9" is what makes **each slide appear twice** in App Store Connect.
> `fastlane deliver` classifies each image into an ASC display family by pixel
> dimensions, and several of those sizes collapse onto the same modern-iPhone
> family — so ASC receives two images for one slot. One size per slide → exactly
> one image per slot → no duplicates.

| Display Size | Pixels (portrait) | Required by ASC |
|--------------|-------------------|------------------|
| 6.9" | 1320×2868 | Yes — the only required iPhone size; shown on all iPhones |

The `app-store-screenshots` skill's `IPHONE_SIZES` array must contain **only**
the 6.9" entry: `{ label: '6.9"', w: 1320, h: 2868 }`.

### Drive the skill

Load `app-store-screenshots:app-store-screenshots` via the Skill tool with directive:
> Context: this is an automated Autobot run. Pre-derived answers live in `.autobot/screenshot-plan.md` (slide narrative + headlines) and `app-marketing-context.md` (brand, colors, font, audience). Raw captures live in `./marketing/<locale>/`. App icon is at `<appIconPath>` (from `autobot-app-icon` output). **Do not ask follow-up questions** — use the files. Generator scaffolds to `.autobot/screenshots-generator/`. **Target: Apple App Store iPhone only.** Export **only** the 6.9" size (1320×2868) — the single required iPhone size — for every locale. Do **not** export 6.5"/6.3"/6.1"; extra sizes cause each slide to appear twice on ASC. Output naming: `<locale>/<NN>_<slot-name>.png` written into `fastlane/screenshots/<locale>/` so fastlane's deliver step picks them up.

**Filename convention** (required by fastlane deliver):
- `01_hero.png`, `02_feature.png`, ... — numeric prefix determines ASC slot order
- One 1320×2868 image per slide — fastlane classifies it as the 6.9" family, the only iPhone slot ASC needs

### Verify output

```bash
IPHONE_SIZE_COUNT=1   # 6.9" only — the single required iPhone size
EXPECTED_SHOTS_PER_LOCALE=$((SLOT_COUNT * IPHONE_SIZE_COUNT))

ACTUAL=$(find fastlane/screenshots -mindepth 2 -name "*.png" -type f | wc -l | tr -d ' ')
EXPECTED_TOTAL=$((EXPECTED_SHOTS_PER_LOCALE * LOCALE_COUNT))
if [ "$ACTUAL" -lt "$EXPECTED_TOTAL" ]; then
  echo "WARN: only $ACTUAL/$EXPECTED_TOTAL screenshots generated. Proceeding — fastlane accepts partial sets."
fi
# Guard against the duplicate-upload bug: every screenshot must be 1320×2868 (6.9").
# A slide present at any other dimension collapses onto the same ASC slot → shown twice.
if command -v sips &>/dev/null; then
  find fastlane/screenshots -mindepth 2 -name "*.png" -type f | while read -r f; do
    dims=$(sips -g pixelWidth -g pixelHeight "$f" 2>/dev/null | awk '/pixelWidth/{w=$2}/pixelHeight/{h=$2}END{print w"x"h}')
    if [ "$dims" != "1320x2868" ]; then
      echo "WARN: non-6.9\" screenshot ($dims) will duplicate the slot on ASC — remove it: $f"
    fi
  done
fi
```

Don't hard-fail on partial output; fastlane accepts incomplete sets — ASC allows submission with the 6.9" set. Any screenshot that is **not** 1320×2868 must be removed before upload, or ASC will show that slide twice.
