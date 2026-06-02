---
name: autobot-peer-review-bridge
user-invocable: false
description: "Use when Autobot needs the opposite AI runtime to review generated artifacts: Codex-hosted runs ask Claude, Claude-hosted runs ask Codex. Soft-skips when the peer tool is unavailable."
---

# Autobot Peer Review Bridge

Autobot should avoid same-model self-review at the highest-risk checkpoints.
This bridge picks the opposite reviewer from the current host:

| Runtime host | Peer reviewer |
|--------------|---------------|
| `codex` | `claude` |
| `claude` | `codex` |
| `unknown` | soft skip |

## Detection

Run this first and record the result during Phase 0:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-peer-ai.sh" --format env

bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" record-environment \
  --runtimeHost codex \
  --peerAi claude \
  --peerReviewAvailable false
```

The detector treats `CODEX_*` environment as Codex, `CLAUDE_*` environment as
Claude, and maps to the opposite peer. It only reports availability; it does
not run either tool.

## Phase 1: Architecture Peer Review (bi-directional)

After architect output exists and before Gate 1->2, write the unified result to
`phases.1.metadata.peerReview` with required fields `host`, `peer`, `verdict`.

| Runtime host | Reviewer path | Implementation |
|--------------|---------------|----------------|
| `claude` | Codex CLI | `scripts/codex-architecture-review.sh` (writes both `codexReview` legacy key and `peerReview` generic key) |
| `codex` | Claude review | Ask Claude (via available CLI/SDK) to review `.autobot/architecture.md` + `<AppName>/Models/` and persist `peerReview` directly |
| either | unavailable | Record `verdict=skipped` with a concrete `skipReason` (`peer_cli_unavailable`, `peer_invocation_failed`, etc.) |

Gate 1->2 reads `phases.1.metadata.peerReview` (falls back to legacy
`codexReview`). `skipReason` is mandatory when `verdict=skipped`. Phase 1 still
accepts a properly-attributed skip because Autobot must work standalone.

Minimum Codex-host -> Claude review payload:

```json
{
  "host": "codex",
  "peer": "claude",
  "verdict": "PASS",
  "attempt": 1,
  "blockingFindingsCount": 0,
  "blockingFindings": [],
  "reviewedAt": "2026-05-26T00:00:00Z"
}
```

Include it in the Phase 1 gate transition:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 1 \
  --metadata 'peerReview={"host":"codex","peer":"claude","verdict":"PASS","attempt":1,"blockingFindingsCount":0}'
```

## Phase 5: Build-Green Peer Review

Run after `BUILD SUCCEEDED`, Axiom critical audit, and local checks, but before
recording `phases.5.metadata.build_succeeded=true`.

Reviewer scope:

```text
Review <AppName>/Views, <AppName>/ViewModels, <AppName>/Services, <AppName>/App.
Do not modify files.
Do not review <AppName>/Models; those are the immutable architect contract.
Return JSON: {"verdict":"PASS|FAIL","blockingFindings":[...],"warnings":[...]}.
Each blocking finding must include file, line, issue, and suggestedFix.
```

Result contract:

```json
{
  "host": "codex",
  "peer": "claude",
  "verdict": "PASS",
  "blockingFindingsCount": 0,
  "findingsPath": ".autobot/peer-review/phase-5.json"
}
```

Record the audit log, then include the review metadata in the Phase 5 gate transition:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event peer_review \
  --detail '{"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}'

bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 5 \
  --metadata build_succeeded=true \
  --metadata 'peerReview={"host":"codex","peer":"claude","verdict":"skipped","skipReason":"peer_cli_unavailable"}'
```

Gate 5->6 requires `phases.5.metadata.peerReview`:

- `PASS` -> continue.
- `skipped` -> continue, but the skip is explicit and auditable.
- `FAIL` or missing -> return to the build-fix loop before Gate 5->6.

## Invocation Guidance

Claude host -> Codex:

```bash
codex exec --skip-git-repo-check -C "$PROJECT_DIR" \
  --sandbox read-only \
  --output-last-message ".autobot/peer-review/phase-5.json" \
  < ".autobot/peer-review/prompt.md"
```

Codex host -> Claude:

- Prefer an installed Claude Code review integration when available.
- Fallback to a non-interactive `claude` CLI invocation if present.
- If neither exists, record `verdict=skipped`.

Do not prompt the user to install the peer tool mid-build. Setup-time discovery
is the right place to recommend installation.
