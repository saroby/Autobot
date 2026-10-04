---
name: autobot-peer-review-bridge
user-invocable: false
description: "Request an opposite-runtime artifact review (Codex → Claude, Claude → Codex); record unavailability."
---

# Autobot Peer Review Bridge

Review with the opposite runtime: `codex→claude`, `claude→codex`, `unknown→soft-skip`.

## Detection

During Phase 0, detect and substitute the **actual** output values into record-environment below. Detection does not invoke reviewers. Do not ask to install tools mid-build.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-peer-ai.sh" --format env
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" record-environment \
  --runtimeHost "<runtimeHost>" --peerAi "<peerAi>" \
  --peerReviewAvailable "<peerReviewAvailable>"
```

## Phase 1: Architecture Review

After architect output and before Gate 1→2, review `.autobot/architecture.md` and `<AppName>/Models/`.

- Claude host: `scripts/codex-architecture-review.sh` writes legacy `codexReview` and generic `peerReview`.
- Codex host: use available Claude CLI/SDK; pass the generic result to the caller.
- Unavailable/invocation failure: `verdict="skipped"` with concrete `skipReason`.

`phases.1.metadata.peerReview` requires `host`, `peer`, `verdict`; actual reviews include `attempt`, `blockingFindingsCount`, `blockingFindings`, `reviewedAt`. Gate reads this key first, then legacy `codexReview`; attributed skips allow standalone builds. Retry/skip policy: `spec/pipeline.json.policies.peerArchitectureReview`.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 1 \
  --metadata "peerReview=$PEER_REVIEW_JSON"
```

## Phase 5: Build-Green Review

Run after `BUILD SUCCEEDED`, Axiom critical audit and local checks, before completion metadata. Review `<AppName>/{Views,ViewModels,Services,App}` read-only; exclude frozen `Models/`.

Return `{verdict:"PASS|FAIL",blockingFindings:[],warnings:[]}`; each blocking finding needs `file`, `line`, `issue`, `suggestedFix`. Save the real result to `.autobot/peer-review/phase-5.json`. Caller records `phases.5.metadata.peerReview` with `host`, `peer`, `verdict`, `blockingFindingsCount`, `findingsPath`. PASS requires parseable JSON inside the project agreeing with metadata; do not report PASS without an artifact.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 --event peer_review \
  --detail "$PEER_REVIEW_JSON"
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" advance-phase --phase 5 \
  --metadata build_succeeded=true --metadata "peerReview=$PEER_REVIEW_JSON"
```

The caller uses pipeline.sh for state changes and includes this metadata only after remaining Phase 5 checks finish.

- PASS: proceed.
- FAIL: route blocking findings into Step 3 Build-Fix Loop, within the spec budget.
- skipped: require `skipReason`. When `environment.peerReviewAvailable=true`, allow only `peer_invocation_failed`, `peer_timeout`, `peer_runtime_error`, `peer_returned_invalid_output`.
- Missing/invalid/failing evidence: Gate 5→6 **DEGRADED** permits local MVP progression and blocks shipping. `qualityMax` also degrades unavailable/skipped reviews.

## Invocation

Claude→Codex:

```bash
codex exec --skip-git-repo-check -C "$PROJECT_DIR" \
  --sandbox read-only \
  --output-last-message ".autobot/peer-review/phase-5.json" \
  < ".autobot/peer-review/prompt.md"
```

Codex→Claude: prefer an installed review integration, then non-interactive `claude` CLI. If neither exists, record `peer_cli_unavailable`.
