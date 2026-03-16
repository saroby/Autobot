# Agent Dispatch Patterns

## Parallel Agent Execution

### File Conflict Prevention

Agents write to separate directories to prevent conflicts:

| Agent | Writes To | Reads From |
|-------|-----------|------------|
| architect | `.autobot/architecture.md` | (user input) |
| ui-builder | `Views/`, `ViewModels/`, `App/` | `.autobot/architecture.md` |
| data-engineer | `Models/`, `Services/` | `.autobot/architecture.md` |
| quality-engineer | `Tests/`, fixes in any file | All source files |
| deployer | `build/`, config files | Built app |

### Agent Prompt Templates

#### For ui-builder dispatch:
```
Read the architecture at [project]/.autobot/architecture.md.
Generate all SwiftUI views, view models, and the app entry point.
Write files to the [project]/ directory following the file structure in the architecture.
Use iOS 26+ APIs: @Observable, NavigationStack, .glassEffect().
Do NOT modify files in Models/ or Services/ — those are handled by another agent.
```

#### For data-engineer dispatch:
```
Read the architecture at [project]/.autobot/architecture.md.
Implement all SwiftData models, repositories, and network services.
Write files to the [project]/ directory following the file structure in the architecture.
Use iOS 26+ APIs: @Model, actor isolation, async/await.
Do NOT modify files in Views/ or ViewModels/ — those are handled by another agent.
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
