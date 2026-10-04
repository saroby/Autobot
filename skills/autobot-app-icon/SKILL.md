---
name: autobot-app-icon
user-invocable: false
description: "Generate square-cornered 1024x1024 app icons with imagegen for /autobot:icon or Autobot Phase 2/3."
---

# App Icon

Use the available `imagegen` skill (`codex-util:imagegen` where named) and its built-in tool. Derive the concept and style from the request and, when present, `.autobot/architecture.md`, `.autobot/design-spec.md`, and app identity in `.autobot/build-state.json`.

## Output contract

- One **1024×1024 opaque PNG**; background fills all four sharp square corners. No rounded canvas, squircle mask, or rounded tile inside the image. Curves within the symbol are allowed.
- Recognizable at small sizes; follow the app's visual direction. No mockup, screenshot, watermark, or unrequested text; do not copy brand marks.
- Inspect the final saved file's format, dimensions, and opacity, and view it to check the corners. An alpha channel is acceptable only if all pixels are opaque. Correct violations with imagegen; report any unverified constraint.

## Standalone: `/autobot:icon`

Generate from the request without requiring pipeline state. If no app concept can be inferred, ask for it. Save the tool output to the requested path or `.autobot/app-icon-1024.png`; if that file exists, choose an unused sibling unless replacement was requested. Show the icon and report the saved path and verification result.

Apply to an asset catalog only when requested. Do not advance phases or modify build state. If imagegen is unavailable or fails, report the failure; Pillow fallback is pipeline-only.

## Pipeline

### Phase 2

Generate and verify using the output contract. Save to the canonical `.autobot/app-icon-1024.png`, replacing it on an explicit regeneration.

If imagegen is unavailable or still fails after one retry, run:

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-icon/scripts/pillow-fallback.sh" \
  --name "<AppName>" --out ".autobot/app-icon-1024.png"
```

Optionally pass `--color "<brand hex>"`. Pillow initials are allowed in this fallback. Verify its dimensions, opacity, and square corners before handoff.

The orchestrator completes Phase 2 once all Phase 2 work is ready. Set `app_icon_status` to `generated` for imagegen or `pillow` for Pillow:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2 \
  --metadata "app_icon_status=<generated-or-pillow>" \
  --metadata app_icon_path=.autobot/app-icon-1024.png
```

If both paths fail, record the failure instead:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 2 --status fallback \
  --metadata app_icon_status=fallback --metadata "app_icon_error=<reason>"
```

### Phase 3

After `ios-scaffold`, apply the verified source and check the catalog:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/app-icon.sh" apply --app-name "<AppName>" \
  --source ".autobot/app-icon-1024.png" --project-dir "."
bash "$CLAUDE_PLUGIN_ROOT/scripts/app-icon.sh" verify --app-name "<AppName>" --project-dir "."
```

For `app_icon_status=fallback`, skip application without blocking scaffold; report placeholder use and `/autobot:resume 2` for regeneration.
