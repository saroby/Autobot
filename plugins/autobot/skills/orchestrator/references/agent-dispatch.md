# Agent Dispatch Patterns

## Parallel Agent Execution

### File Ownership, Type Contract & Worktree Isolation

Agents write to separate directories to prevent conflicts. `Models/` is the **shared type contract** (data models + service protocols) created by architect — no other agent may modify it.

Phase 3의 ui-builder와 data-engineer는 **별도의 git worktree**에서 실행되어 파일시스템 수준의 격리를 보장한다.

| Agent | Writes To | Reads From | MUST NOT Touch | Isolation |
|-------|-----------|------------|----------------|-----------|
| architect | `.autobot/architecture.md`, `Models/` | (user input) | — | main |
| ui-builder | `Views/`, `ViewModels/`, `App/` | `Models/*.swift`, `Models/ServiceProtocols.swift` | `Models/`, `Services/` | **worktree** |
| data-engineer | `Services/`, `Utilities/` | `Models/*.swift`, `Models/ServiceProtocols.swift` | `Models/`, `Views/`, `ViewModels/`, `App/` | **worktree** |
| backend-engineer | `backend/` | `Models/APIContracts.swift`, `Models/ServiceProtocols.swift` | `Models/`, `Views/`, `ViewModels/`, `Services/`, `App/`, root `.gitignore` | **worktree** |
| quality-engineer | `Tests/`, fixes in any file, integration wiring | All source files | — | main |
| deployer | `build/`, config files | Built app | — | main |

### Agent Prompt Templates

#### For ui-builder dispatch:
```
ZEROTH: Read $CLAUDE_PLUGIN_ROOT/references/ios-ux-style.md for authoritative iOS design patterns and anti-patterns.
FIRST: Read ALL .swift files in [project]/Models/ to learn exact type names, properties, and initializers.
SECOND: Read [project]/Models/ServiceProtocols.swift to learn the service interfaces your ViewModels depend on.
THEN: Read the architecture at [project]/.autobot/architecture.md for screen inventory, navigation, and integration map.
Generate all SwiftUI views, view models, and the app entry point.
ViewModels MUST depend on Service protocols (e.g. ItemServiceProtocol), NOT on ModelContext directly.
Create App/ServiceStubs.swift with stub implementations for each protocol (return empty arrays, no-ops).
Write files to [project]/Views/, [project]/ViewModels/, and [project]/App/.
In the App entry point, register ALL @Model types in .modelContainer(for:).
Follow ALL patterns from ios-ux-style.md. Do NOT use patterns listed in the Anti-Patterns table.
Do NOT create, modify, or overwrite files in Models/ or Services/ — those are handled by other agents.
Use the EXACT type names, initializer signatures, and protocol method signatures from Models/*.swift.
```

#### For data-engineer dispatch:
```
ZEROTH: Read $CLAUDE_PLUGIN_ROOT/references/ios-ux-style.md for authoritative iOS target version and API patterns.
FIRST: Read ALL .swift files in [project]/Models/ to learn exact type names, properties, and initializers.
SECOND: Read [project]/Models/ServiceProtocols.swift to learn the service interfaces you MUST implement.
THEN: Read the architecture at [project]/.autobot/architecture.md for API endpoints and data flow.
For EACH protocol in ServiceProtocols.swift, create a Repository class that conforms to it.
Implement repositories and network services that use the existing Model types.
Write files to [project]/Services/ and [project]/Utilities/.
Follow ALL patterns from ios-ux-style.md (concurrency, data persistence sections).
Do NOT create, modify, or overwrite files in Models/, Views/, ViewModels/, or App/.
Use the EXACT type names, initializer signatures, and protocol method signatures from Models/*.swift.
```

#### For backend-engineer dispatch (conditional: backend_required == true):
```
FIRST: Read [project]/.autobot/architecture.md — focus on Backend Requirements, API Contract, Environment Variables sections.
SECOND: Read [project]/Models/APIContracts.swift to learn exact API request/response types.
Generate a complete Docker-based FastAPI backend in [project]/backend/.
All API endpoints MUST match the API Contract section exactly.
All request/response schemas MUST match Models/APIContracts.swift types.
Server MUST start and /health MUST return 200 even with dummy .env values.
Do NOT create, modify, or overwrite files outside backend/.
Do NOT touch root .gitignore (already configured in Phase 2).
```

### Three-Agent Parallel Pattern (backend_required == true)

When `build-state.json` has `backend_required: true`, Phase 3 dispatches three agents in parallel:

```
Agent(
  prompt="[ui-builder task with full context]",
  isolation="worktree"
)
Agent(
  prompt="[data-engineer task with full context]",
  isolation="worktree"
)
Agent(
  prompt="[backend-engineer task with full context]",
  isolation="worktree"
)
```

All three write to disjoint directories → merge conflict probability zero.
Worktree fallback applies to all three agents identically.

## AgentTeam Integration

When AgentTeam feature is available (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1):

### Team Structure
```json
{
  "name": "autobot-<app-name>",
  "members": [
    {"name": "architect", "agentType": "orchestrator", "model": "claude-opus-4-6"},
    {"name": "ui-builder", "agentType": "worker", "model": "claude-sonnet-4-6"},
    {"name": "data-engineer", "agentType": "worker", "model": "claude-sonnet-4-6"},
    {"name": "quality-engineer", "agentType": "worker", "model": "claude-sonnet-4-6"},
    {"name": "backend-engineer", "agentType": "worker", "model": "claude-sonnet-4-6"}
  ]
}
```

### Communication via Inboxes
Team members communicate through message inboxes:
- architect → broadcasts architecture decisions
- ui-builder → reports UI completion status
- data-engineer → reports data layer completion
- quality-engineer → reports build/test results

## Background Agent Pattern

For non-blocking work, use `run_in_background: true`:

```
Agent(
  prompt="Write tests for...",
  run_in_background=true
)
```

Use background agents for:
- Test writing (while moving to deployment)
- Documentation generation
- Code quality analysis

Do NOT use background agents for:
- Architecture planning (blocks everything)
- Build verification (must complete before deploy)
- Deployment (must report status)

## Worktree Fallback

`Cannot create agent worktree` 에러 발생 시 (세션 중 `git init`된 저장소 등):

1. `isolation` 파라미터를 **제거**하고 general-purpose 에이전트로 재디스패치
2. 두 에이전트를 **병렬로** 실행 — 파일 소유권 규칙(Views/ vs Services/)이 충돌 방지
3. 에이전트 프롬프트는 동일하게 유지 (worktree 관련 언급만 제거)

```
# Fallback 예시
Agent(
  prompt="[ui-builder task - 동일 프롬프트]"
  # isolation 파라미터 없음
)
Agent(
  prompt="[data-engineer task - 동일 프롬프트]"
  # isolation 파라미터 없음
)
```

## Error Recovery in Parallel Agents

If one parallel agent fails:
1. Let the other agent complete
2. Manually fix the failed agent's work
3. Do NOT re-dispatch both agents
4. Log the failure pattern for retrospective
