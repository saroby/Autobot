# Agent Dispatch Contract

## Authority

- Phase membership comes from `spec/pipeline.json` `phases.<id>.agents`.
- Writable paths come from `spec/pipeline.json` `fileOwnership.agents`.
- Static role instructions live only in `agents/<name>.md`.
- Runtime context comes from `pipeline.sh context-pack`.

Do not copy role instructions, ownership tables, reference lists, or model names into the dispatch prompt. Those copies drift and can override the current agent definition. Agent model selection inherits the host default unless a measured, centrally managed policy is added later.

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
