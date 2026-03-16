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
| 1 | Architecture + Type Contract | architect | No | 3min |
| 2 | Project Scaffold | (self) | No | 1min |
| 3 | Parallel Coding | ui-builder + data-engineer | **Yes** | 5min |
| 4 | Integration & Build | quality-engineer | No | 3min |
| 5 | TestFlight Deploy | deployer | No | 5min |
| 6 | Retrospective | (self) | No | 30s |

**Phase 1 now produces two outputs:**
1. `.autobot/architecture.md` — design document
2. `Models/*.swift` — compilable @Model files that serve as the **type contract** for Phase 3

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
- `.autobot/build-state.json` — **Build state** (phase status, app metadata, resume point)
- `.autobot/architecture.md` — Architecture specification
- `Models/*.swift` — **Type contract** (compilable @Model files created by architect)
- `.autobot/learnings.json` — Past build learnings
- `.autobot/deploy-status.json` — Deployment results

**Type contract rule:** Both ui-builder and data-engineer MUST read `Models/*.swift` files before writing any code, and MUST NOT modify them. The Model files are the single source of truth for type names, property names, and initializer signatures.

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

## Build State Management

### State File: `.autobot/build-state.json`

매 Phase 시작/완료/실패 시 상태 파일을 갱신한다. 이를 통해 `/autobot:resume`으로 중단된 빌드를 재개할 수 있다.

```json
{
  "buildId": "build-20260316-socialfitness",
  "appName": "SocialFitness",
  "displayName": "소셜 피트니스",
  "bundleId": "com.saroby.socialfitness",
  "projectPath": "/Users/saroby/SocialFitness",
  "idea": "소셜 피트니스 트래킹 앱",
  "startedAt": "2026-03-16T12:00:00Z",
  "phases": {
    "0": { "status": "completed", "completedAt": "2026-03-16T12:00:30Z" },
    "1": { "status": "completed", "completedAt": "2026-03-16T12:03:00Z" },
    "2": { "status": "completed", "completedAt": "2026-03-16T12:04:00Z" },
    "3": { "status": "completed", "completedAt": "2026-03-16T12:09:00Z" },
    "4": { "status": "failed", "error": "Cannot find type 'ModelContext'", "failedAt": "2026-03-16T12:11:00Z", "retryCount": 5 },
    "5": { "status": "pending" },
    "6": { "status": "pending" }
  }
}
```

### Phase Status Values

| Status | 의미 |
|--------|------|
| `pending` | 아직 시작 안 됨 |
| `in_progress` | 현재 실행 중 |
| `completed` | 성공적으로 완료 |
| `failed` | 실패 (에러 메시지 포함) |
| `skipped` | 실패로 인해 건너뜀 |

### State Update Protocol

1. Phase 시작 시: `status: "in_progress"`, `startedAt` 기록
2. Phase 성공 시: `status: "completed"`, `completedAt` 기록
3. Phase 실패 시: `status: "failed"`, `error`, `failedAt`, `retryCount` 기록
4. 실패로 건너뛴 Phase: `status: "skipped"`

### Resume 연동

`/autobot:resume` 커맨드가 이 상태 파일을 읽어:
- 실패/중단 지점을 자동 감지
- 이전 에러 메시지를 에이전트 프롬프트에 포함
- 완료된 Phase는 건너뜀
- 사용자가 특정 Phase를 지정하면 해당 지점부터 재실행

## Error Recovery

When a phase fails:
1. 상태 파일에 에러 기록 (`build-state.json`)
2. Attempt automatic recovery (rebuild, re-sign, etc.)
3. If unrecoverable, skip to retrospective (Phase 6) — 건너뛴 Phase는 `skipped`로 마킹
4. Report partial completion to user with **`/autobot:resume` 재시도 안내**

## Additional Resources

### Reference Files

For detailed coordination patterns:
- **`references/planning-patterns.md`** — App idea analysis and feature extraction patterns
- **`references/agent-dispatch.md`** — Advanced parallel agent coordination strategies
