## Phase G — Submit for review

```bash
AUTOBOT_REVIEW_SUBMIT_STATUS_FILE=.autobot/review-submit-status.json \
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/submit-for-review.sh" \
  --bundle-id "$BUNDLE_ID"
```

The script polls for up to 30 minutes for the build to leave PROCESSING, then submits with these defaults (matching Autobot's standard scaffold):

```json
{
  "export_compliance_uses_encryption": false,
  "content_rights_contains_third_party_content": false,
  "content_rights_has_rights": true,
  "add_id_info_uses_idfa": false
}
```

These match `ITSAppUsesNonExemptEncryption=false` (Autobot's mandatory contract — see `CONVENTIONS.md`) and "no AdSupport/ATT framework" (Autobot scaffold doesn't add either). If the orchestrator detects either deviation (e.g. `architecture.md` mentions analytics SDK with IDFA), pass the appropriate `--uses-idfa` / `--uses-encryption` flag.

`automatic_release` is on by default — once approved, the app goes live without manual intervention. To hold for manual release, pass `--no-auto-release`.

Failure matrix:

| `reason` | Meaning | Recovery |
|----------|---------|----------|
| `build_processing_timeout` | Build still PROCESSING after 30 min | The orchestrator re-invokes the script **once** automatically (another 30-min poll) before reporting. Second timeout → report with the retry hint, or `--skip-wait` if you've verified the build is VALID in ASC web |
| `build_not_ready` | Submission tried but no VALID build attached | Wait, retry |
| `missing_metadata_or_screenshots` | Required fields/screenshots missing on ASC | Re-run Phase B + E to push the missing data |
| `age_rating_missing` | Age-rating questionnaire unanswered (Phase B's `app_store_rating_config.json` missing or didn't apply — e.g. the app record didn't exist on ASC yet when metadata uploaded) | Re-run Phase B — its dual skip gate checks `app_store_rating_config.json` independently of the `.txt` count, writes it if missing (step 2b), and re-uploads. Manual ASC-web answer is last-resort only. |
| `export_compliance_question` | Encryption answer mismatch | Verify `ITSAppUsesNonExemptEncryption` in Info.plist; pass `--uses-encryption` if needed |
| `already_in_review` | Version already submitted | Treated as success (exit 0) |
