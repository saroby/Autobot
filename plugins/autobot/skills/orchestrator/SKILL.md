---
name: autobot-orchestrator
description: This skill should be used when orchestrating a full iOS app build from an idea, coordinating parallel agents, managing build phases, or when the user invokes "/autobot:build". Provides the master coordination logic for the Autobot build pipeline including agent dispatch strategy, phase management, and integration patterns.
version: 0.1.0
---

# Autobot Orchestrator

Master coordination skill for building iOS 26+ apps from ideas. Manages the complete pipeline from idea analysis through TestFlight deployment.

## Core Pipeline

The Autobot build pipeline has 6 phases executed in strict order:

| Phase | Name | Agent | Parallel | Duration Target |
|-------|------|-------|----------|-----------------|
| 0 | Environment Setup | (self) | No | 30s |
| 1 | Architecture | architect | No | 2min |
| 2 | Project Scaffold | (self) | No | 1min |
| 3 | Parallel Coding | ui-builder + data-engineer | **Yes** | 5min |
| 4 | Integration & Build | quality-engineer | No | 3min |
| 5 | TestFlight Deploy | deployer | No | 5min |
| 6 | Retrospective | (self) | No | 30s |

## Agent Dispatch Strategy

### Parallel Execution (Phase 3)

Dispatch ui-builder and data-engineer simultaneously using the Agent tool:

```
In a SINGLE message, call Agent tool twice:
1. Agent(subagent_type="general-purpose", prompt="[ui-builder task]")
2. Agent(subagent_type="general-purpose", prompt="[data-engineer task]")
```

Both agents read the same `.autobot/architecture.md` and write to different directories, so there are no file conflicts.

### Sequential Dependencies

- Phase 1 (architect) must complete before Phase 2 (scaffold)
- Phase 2 must complete before Phase 3 (parallel coding)
- Phase 3 must complete before Phase 4 (quality)
- Phase 4 must complete before Phase 5 (deploy)

### Agent Context Passing

Each agent receives context via files, not direct messages:
- `.autobot/architecture.md` — Architecture specification
- `.autobot/learnings.json` — Past build learnings
- `.autobot/deploy-status.json` — Deployment results

## Plugin Detection Strategy

Detect and leverage installed plugins without creating hard dependencies:

```
1. Check for Axiom skills availability:
   - Try invoking Skill("axiom:axiom-ios-ui")
   - If available: include in agent prompts
   - If not: agents use built-in iOS knowledge

2. Check for Serena tools:
   - Look for mcp__plugin_serena_serena__* tools
   - If available: use semantic editing for refactoring
   - If not: use standard Edit tool

3. Check for context7:
   - Look for mcp__context7__* tools
   - If available: fetch latest API docs
   - If not: rely on training knowledge
```

## Error Recovery

When a phase fails:
1. Log the error to `.autobot/build-log.md`
2. Attempt automatic recovery (rebuild, re-sign, etc.)
3. If unrecoverable, skip to retrospective (Phase 6)
4. Report partial completion to user

## Additional Resources

### Reference Files

For detailed coordination patterns:
- **`references/planning-patterns.md`** — App idea analysis and feature extraction patterns
- **`references/agent-dispatch.md`** — Advanced parallel agent coordination strategies
