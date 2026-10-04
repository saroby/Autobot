---
name: autobot-axiom-bridge
user-invocable: false
description: "Run Axiom critical audits in Phase 5 or health checks in Phase 7."
---

# Autobot ↔ Axiom Bridge

| Caller | Mode | Scope |
|--------|------|-------|
| Phase 5 Step 7, after build/local checks, before completion metadata | `critical` | Four critical auditors; bounded fixes/re-audits |
| Phase 7, after metrics collection | `health-check` | Full health-check, report-only |

## Detection / soft-skip

Set `PHASE` and `MODE` for the caller, then detect:

```bash
AXIOM_ROOT=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-axiom.sh" 2>/dev/null || true)
```

If absent, record the event below and current audit metadata `ran=false`, then return success. Do not ask to install Axiom mid-build.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" \
  --phase "$PHASE" --event axiom_audit_skipped \
  --detail '{"reason":"axiom_plugin_not_installed","mode":"'"$MODE"'"}'
```

When available, invoke loaded Axiom agents directly with `Task`, not slash commands or shell-outs. Pass metadata to the caller for `pipeline.sh` state changes; do not edit build-state directly.

## Mode 1: Gate-5 Critical Audit

Dispatch all four in **one message**, in parallel:

- `axiom:concurrency-auditor`
- `axiom:swiftdata-auditor`
- `axiom:memory-auditor`
- `axiom:swiftui-architecture-auditor`

Audit `<AppName>/{Views,ViewModels,Services,App}`; exclude frozen `Models/`. Return JSON `{critical:[],warning:[],info:[]}` with each finding `{file,line,rule,message,fix_hint}`.

Save full output to `.autobot/axiom-critical.json` before the gate. Caller records `phases.5.metadata.axiom_critical_audit`:

```json
{"ran":true,"auditors":["concurrency","swiftdata","memory","swiftui-architecture"],"critical_count":0,"findings_path":".autobot/axiom-critical.json"}
```

Use the actual critical total. Findings must be parseable JSON inside the project and agree with metadata. Log actual counts:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/build-log.sh" --phase 5 \
  --event axiom_audit_completed --detail "$AUDIT_DETAIL_JSON"
```

`AUDIT_DETAIL_JSON` requires `mode="critical"`, `criticalCount`; optional `auditors`, `warningCount`, `findingsPath`.

- Zero criticals: proceed.
- Criticals: Step 3 Build-Fix Loop follows `fix_hint`, rebuilds, then reruns **only auditors that reported criticals**. Do not set `build_succeeded=true` during fixes. Fix consumers even for Models-rooted findings; preserve the contract.
- Retry/signature limits: `spec/pipeline.json.policies.buildFixLoop` / `circuitBreaker`. On exhaustion, preserve `axiom_critical_unresolved` evidence and hand off.

Missing/invalid artifacts or unresolved criticals yield Gate 5→6 **DEGRADED**: local MVP can progress, shipping is blocked. Ordinary unavailable Axiom soft-skips; `qualityMax` degrades unavailable/skipped evidence too. Do not relabel it a clean pass.

## Mode 2: Phase-7 Health-Check

Dispatch **one** `axiom:health-check`; do not call individual auditors again. Exclude `<AppName>/Models` and `<AppName>Tests`. Request unified findings at `.autobot/axiom-health.json` and a one-paragraph executive summary.

1. Append summary under `.autobot/build-report.md` → `## Axiom Health-Check`.
2. Increment `learnings.json.patterns.axiom_findings[rule].frequency` once per distinct observed rule (initialize if absent), using the `common_build_errors` shape.
3. Caller records `phases.7.metadata.axiom_health_check`:

```json
{"ran":true,"findings_path":".autobot/axiom-health.json","summary_path":"build-report.md#axiom-health-check"}
```

Phase 7 findings never fail the build. `autobot-retrospective` self-check verifies invocation or explicit skip evidence.
