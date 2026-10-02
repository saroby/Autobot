## Phase 0b — Ensure app registered on ASC (idempotent)

Register the app on App Store Connect **before** any metadata/rating upload. The age-rating declaration and the metadata URL fields can only be applied to an existing ASC app record — `fastlane deliver` silently skips age rating if the app can't be fetched. Running register first guarantees the first `/autobot:app-review` reaches review **in a single pass**, with no reliance on the Phase B → Phase F → retry fallback. It also fails fast: a name/bundle collision halts here, before any expensive metadata/screenshot work.

`autobot-register-app` is fully idempotent — `already_exists` is silent success, so this is safe on every re-run (and makes Phase F's own register a no-op).

```bash
DISPLAY_NAME=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('displayName',''))")
[ -z "$DISPLAY_NAME" ] && { echo "ERROR: displayName missing — run /autobot:setup."; exit 1; }

AUTOBOT_REGISTER_STATUS_FILE=.autobot/register-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-register-app/scripts/register-app.sh" \
  --bundle-id "$BUNDLE_ID" --display-name "$DISPLAY_NAME"
```

Branch on `register-status.json`'s `result` + `reason`. The per-reason guidance text is owned by `agents/deployer.md` Step 1 (same producing script — do not fork the matrix here). Orchestration decisions:

| Signal | Handling |
|--------|----------|
| exit 2 (no Apple ID / no `spaceauth` session — no status file written) | **Halt.** Relay the stderr guidance: `fastlane spaceauth -u <apple-id>` (interactive 2FA, ~30-day session). Register uses the Apple ID web session, not the ASC API key. |
| `created` / `already_exists` | Proceed to Phase A (`already_exists` is silent). |
| `failed` + `fastlane_exit_N` | Transient ASC error class — **re-run `register-app.sh` once** with the same args (idempotent). Still failing → halt with the fastlane output attached. |
| `failed` + any other reason (`name_collision`, `bundle_id_taken`, `asc_session_expired`, `asc_permission_denied`) | **Halt** with the per-reason guidance from deployer.md Step 1. No auto-retry — these need a human (`asc_session_expired` requires an interactive `spaceauth` refresh; retrying cannot fix it). |

On any halt, report the diagnostic and stop — do not proceed to Phase A. Registration is cheap; the metadata/screenshot phases are not.
