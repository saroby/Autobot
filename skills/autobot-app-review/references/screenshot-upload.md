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
