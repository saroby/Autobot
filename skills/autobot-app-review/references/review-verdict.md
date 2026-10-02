## Post-submission — check review verdict (on-demand)

Phase G ends at "Waiting for Review"; the verdict (approval/rejection) arrives
hours~days later. `check-review-status.sh` retrieves it via the ASC API (API
Key auth, read-only). It is deliberately **not** a controller phase — run it
on demand when the user asks "심사 어떻게 됐어?" or before planning a
re-submission.

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/autobot-app-review/scripts/check-review-status.sh" \
  --bundle-id "$BUNDLE_ID"
```

Writes `.autobot/review-verdict.json`:

```json
{
  "fetchedAt": "2026-07-17T12:00:00+00:00",
  "appVersionState": "REJECTED",
  "reviewSubmissionState": "UNRESOLVED_ISSUES",
  "guidelineNumbers": [],
  "notes": "States fetched via ASC API. Rejection rationale (Resolution Center) is not exposed by the public API — check ASC web/email for details."
}
```

On `REJECTED` / `METADATA_REJECTED`: the written rationale lives only in ASC
web (Resolution Center) / email — an IRREDUCIBLE human read (see
`references/autonomy-touchpoints.md`). After fixing, re-run Phase B/E as
needed and re-submit via Phase G (idempotent).
