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
    {"name": "quality-engineer", "agentType": "worker", "model": "claude-sonnet-4-6"}
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

## Error Recovery in Parallel Agents

If one parallel agent fails:
1. Let the other agent complete
2. Manually fix the failed agent's work
3. Do NOT re-dispatch both agents
4. Log the failure pattern for retrospective
