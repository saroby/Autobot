## Phase F — Ensure binary on ASC

If the current `build-state.json` indicates the build has not been uploaded yet (no `.autobot/upload-status.json` with `result: uploaded` or `already_uploaded`), dispatch the **`deployer` agent** — the same agent `/autobot:testflight` uses. The deployer chains `autobot-register-app` → `autobot-archive-build` → `autobot-upload-build` → `autobot-invite-testers` with the proper error contracts (`name_collision`, `bundle_id_taken`, `asc_session_expired`, `asc_permission_denied` halt before any expensive archive work).

```
Agent(
  description: "Ensure ASC binary",
  subagent_type: "deployer",
  prompt: "Ensure the latest build is on App Store Connect. App: <DISPLAY_NAME>, bundle: <BUNDLE_ID>.
           Re-running is safe — register is idempotent (already_exists is silent success).
           If .autobot/upload-status.json already shows result=uploaded or result=already_uploaded
           for the current archive, do nothing and report so. Otherwise run register → archive → upload.
           invite-testers is optional — skip unless config.json:testerEmails is populated."
)
```

The deployer writes `.autobot/register-status.json`, `archive-status.json`, `upload-status.json` (atomic). On any halt (name_collision / bundle_id_taken / asc_session_expired / asc_permission_denied / signing failure / upload failure after bounded retries), surface the deployer's diagnostic to the user and stop the orchestrator — do not proceed to Phase G.

**Skip Phase F only when the controller marks it complete.** It requires the
upload status to match the current `buildId`, `bundleId`, and archive/artifact
digest. Timestamp or source-mtime heuristics are not release identity.

`result: already_uploaded` means ASC rejected the binary as a redundant upload
(same bundle version already on ASC) — `upload.sh` maps that to success since
the upload goal is met. Heed its WARN about build-number reuse: content match
with the ASC binary is unverified, so a re-build with changed code needs a
build-number bump to actually ship.
