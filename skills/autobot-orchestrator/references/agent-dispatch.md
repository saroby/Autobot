# Agent Dispatch Contract

## Authority

- Phase membership comes from `spec/pipeline.json` `phases.<id>.agents`.
- Writable paths come from `spec/pipeline.json` `fileOwnership.agents`.
- Static role instructions live only in `agents/<name>.md`.
- Runtime context comes from `pipeline.sh context-pack`.

Do not copy role instructions, ownership tables, reference lists, or model names into the dispatch prompt. Those copies drift and can override the current agent definition. Agent model selection inherits the host default except for the host-gated **Model Routing** policy below — the "centrally managed policy" this note reserves. It lives here, never in agent frontmatter (frontmatter stays model-neutral so the same pipeline runs on any host; a test enforces this).

## Path Convention

`[project]` is the project root. `[sources]` is `[project]/[AppName]`, the Xcode source group. `.autobot/`, `Packages/`, and `backend/` are rooted at `[project]`.

## Dispatch

Before every agent dispatch, build the focused prompt from executable state:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" context-pack \
  --phase <N> --agent <agent-name> \
  --prompt-tail "<dynamic retry or failure context only>" \
  --format text
```

Pass that output to the matching `Agent(subagent_type=...)`. `--prompt-tail` must contain only information unique to this run, such as the previous failure signature. The agent definition already owns its workflow and pre-reads.

Phase 4 dispatches `ui-builder` and `data-engineer`, plus `backend-engineer` only when `backend_required == true`, concurrently in one tool batch. Do not invent a second team-coordination protocol and do not continue to build verification or deployment until every required Phase 4 agent has completed.

## Model Routing (host-gated)

Frontmatter stays model-neutral (agents inherit the host model — enforced by a test) so the same pipeline runs whether driven by Claude Code or another host. **Only on a Claude Code host** may the dispatcher pass an explicit tier to the `Agent(model=...)` parameter per the table below; on any other host the parameter is omitted and the agent inherits the host default. This is a Claude-only cost optimization layered on top of a neutral core.

Detect the host once per build (reuse the value across all dispatches):

```bash
HOST=$(bash "$CLAUDE_PLUGIN_ROOT/scripts/detect-peer-ai.sh" --format env | sed -n 's/^runtimeHost=//p')
# HOST=claude → apply the tier table; HOST=codex/unknown → omit model (inherit)
```

| Agent | Tier (claude host only) | Why this tier |
|-------|-------------------------|---------------|
| architect | opus | requirements → architecture → contract reasoning; highest blast radius |
| quality-engineer | opus | compile-error diagnosis + build-fix loop reasoning |
| ui-builder | sonnet | high-volume SwiftUI view generation |
| data-engineer | sonnet | repository implementation behind fixed protocols |
| backend-engineer | sonnet | FastAPI proxy, largely boilerplate |
| design-system | sonnet | token + shared-component generation |
| ux-designer | sonnet | Native-first design direction + design-spec authoring |
| deployer | sonnet | skill chaining + ASC error classification |

Use only the bare tier alias (`opus` / `sonnet`) so the host resolves it to its current model of that tier. Never write a provider-qualified model id — a provider-prefixed string breaks host neutrality and is rejected by test. An unrecognized agent not in the table inherits the host default (omit `model`).

## Sandbox

Use the pipeline sandbox marker before dispatch and clear it after the agent finishes:

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox set-active \
  --agent <agent-name> --phase <N>

# Agent(...)

bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" sandbox clear-active
```

For the concurrent Phase 4 batch, follow the broad-access marker rule in `autobot-orchestrator/SKILL.md`; Gate 4→5 performs the per-agent after-diff ownership check. The spec remains authoritative if prose differs.

## Completion and Recovery

Each agent must leave either gate-verifiable artifacts or a blocker report containing:

- `inputs_read`
- `outputs_written`
- `policy_violations`
- `next_action`

If one concurrent agent fails, let the others finish and redispatch only the failed agent with the failure reason in `prompt-tail`. Never run build verification, tests, or deployment in the background across an unmet phase dependency.
