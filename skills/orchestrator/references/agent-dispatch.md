# Agent Dispatch Patterns

## Path Convention

> **모든 소스 파일은 `[sources]` 디렉토리에 작성한다.** `[sources]` = `[project]/[AppName]` (Xcode 소스 그룹).
> `.autobot/`, `backend/` 등은 `[project]` 루트에 위치.
>
> 예: AppName이 `FocusTimer`이고 프로젝트가 `/Users/saroby/FocusTimer`이면:
> - `[project]` = `/Users/saroby/FocusTimer`
> - `[sources]` = `/Users/saroby/FocusTimer/FocusTimer`

## Parallel Agent Execution

### File Ownership & Type Contract

Agents write to separate directories to prevent conflicts. `[sources]/Models/` is the **shared type contract** (data models + service protocols) created by architect — no other agent may modify it.

Phase 4의 에이전트들은 **파일 소유권 규칙**으로 충돌을 방지한다. 각 에이전트는 지정된 디렉토리에만 쓰고, 다른 에이전트의 디렉토리를 건드리지 않는다.

| Agent | Writes To | Reads From | MUST NOT Touch |
|-------|-----------|------------|----------------|
| architect | `.autobot/architecture.md`, `[sources]/Models/` | (user input) | — |
| ux-designer | `.autobot/designs/`, `.autobot/design-spec.md` | `.autobot/architecture.md` | `[sources]/`, `.autobot/architecture.md` |
| ui-builder | `[sources]/Views/`, `[sources]/ViewModels/`, `[sources]/App/`, `[sources]/Utilities/Theme.swift` | `[sources]/Models/*.swift`, `.autobot/design-spec.md` (있으면) | `[sources]/Models/`, `[sources]/Services/`, `.autobot/*` (infra) |
| data-engineer | `[sources]/Services/`, `[sources]/Utilities/` (Theme.swift 제외) | `[sources]/Models/*.swift` | `[sources]/Models/`, `[sources]/Views/`, `[sources]/ViewModels/`, `[sources]/App/`, `[sources]/Utilities/Theme.swift`, `.autobot/*` (infra) |
| backend-engineer | `[project]/backend/` | `[sources]/Models/APIContracts.swift` | `[sources]/`, root `.gitignore`, `.autobot/*` (infra) |
| quality-engineer | `[project]/*Tests/`, fixes in any file, integration wiring | All source files | `[sources]/Models/`, `.autobot/*` (infra) |
| deployer | `[project]/build/`, config files | Built app | `.autobot/*` (infra) |

> **`.autobot/*` (infra)** = `build-state.json`, `architecture.md`, `contracts/`, `build-log.jsonl`, `build.lock`, `learnings.json`, `active-learnings.md`, `phase-learnings/`. 파이프라인 제어 파일은 오케스트레이터만 수정한다.

## Agent Sandbox (파일 소유권 강제)

에이전트 실행 전후에 `agent-sandbox.sh`를 호출하여 파일 소유권 규칙을 **프로그래밍적으로 강제**한다.

```bash
# 에이전트 디스패치 직전
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" before --agent ui-builder --app-name "<AppName>"

# Agent(subagent_type="ui-builder", prompt="...")

# 에이전트 완료 직후
bash "$CLAUDE_PLUGIN_ROOT/scripts/agent-sandbox.sh" after --agent ui-builder --app-name "<AppName>"
# → "OK: ui-builder — 12 created, 0 deleted, 0 violations"
# → 또는 "VIOLATION: ui-builder wrote to Models/ → ..." (exit 1)
```

위반 감지 시:
1. 위반 파일을 삭제
2. 이벤트 로그에 기록: `build-log.sh --phase 4 --event agent_violation --agent <name>`
3. 해당 에이전트만 재실행

## Success Contract

각 에이전트는 완료 시 아래 중 하나를 남겨야 한다:

- Gate가 검증 가능한 파일 산출물
- 재시도에 필요한 blocker 보고

최소 보고 항목:

- `inputs_read`: 읽은 파일
- `outputs_written`: 생성 또는 수정한 파일
- `policy_violations`: 금지 디렉토리 침범 여부
- `next_action`: 성공 또는 재시도 지침

### Agent Prompt Templates

오케스트레이터는 `[project]`와 `[sources]`를 실제 경로로 치환하여 에이전트에게 전달한다.

#### For ux-designer dispatch (Phase 2, 필수):
```
Read the architecture at [project]/.autobot/architecture.md for:
- App overview (display name, identifier name)
- Screen inventory (## Screens section)
- Navigation structure (## Navigation Structure section)
- Feature list (## Features section)

Generate UI mockup designs for each screen using Google Stitch.
Save screenshots to [project]/.autobot/designs/<ScreenName>.png
Write design specification to [project]/.autobot/design-spec.md

App display name: [displayName]
App identifier: [appName]
```

#### For ui-builder dispatch:
```
ZEROTH: Read $CLAUDE_PLUGIN_ROOT/references/ios-ux-style.md for authoritative iOS design patterns and anti-patterns.
FIRST: Read ALL .swift files in [sources]/Models/ to learn exact type names, properties, and initializers.
SECOND: Read [sources]/Models/ServiceProtocols.swift to learn the service interfaces your ViewModels depend on.
THEN: Read the architecture at [project]/.autobot/architecture.md for screen inventory, navigation, and integration map.
THEN: Read [project]/.autobot/design-spec.md for visual design references, design tokens, and UI pattern guidance from Stitch mockups. Check [project]/.autobot/designs/ for screen mockup images. This is the PRIMARY design input — if it exists, it takes precedence over architecture.md for visual decisions.
IF design-spec.md DOES NOT EXIST (fallback mode): Proceed with architecture.md alone for UI decisions.
Generate all SwiftUI views, view models, and the app entry point.
ViewModels MUST depend on Service protocols using existential types (e.g. `any ItemServiceProtocol`), NOT on ModelContext directly.
Create [sources]/App/ServiceStubs.swift with stub implementations for each protocol (return empty arrays, no-ops).
Write files to [sources]/Views/, [sources]/ViewModels/, and [sources]/App/.
In the App entry point, register ALL @Model types in .modelContainer(for:).
Follow ALL patterns from ios-ux-style.md. Do NOT use patterns listed in the Anti-Patterns table.
Do NOT create, modify, or overwrite files in [sources]/Models/ or [sources]/Services/ — those are handled by other agents.
Use the EXACT type names, initializer signatures, and protocol method signatures from [sources]/Models/*.swift.
IMPORTANT: All files MUST be inside [sources]/ — never at the project root [project]/.
```

#### For data-engineer dispatch:
```
ZEROTH: Read $CLAUDE_PLUGIN_ROOT/references/ios-ux-style.md for authoritative iOS target version and API patterns.
FIRST: Read ALL .swift files in [sources]/Models/ to learn exact type names, properties, and initializers.
SECOND: Read [sources]/Models/ServiceProtocols.swift to learn the service interfaces you MUST implement.
THEN: Read the architecture at [project]/.autobot/architecture.md for API endpoints and data flow.
For EACH protocol in ServiceProtocols.swift, create a Repository class that conforms to it.
Implement repositories and network services that use the existing Model types.
Write files to [sources]/Services/ and [sources]/Utilities/.
Follow ALL patterns from ios-ux-style.md (concurrency, data persistence sections).
Do NOT create, modify, or overwrite files in [sources]/Models/, [sources]/Views/, [sources]/ViewModels/, or [sources]/App/.
Use the EXACT type names, initializer signatures, and protocol method signatures from [sources]/Models/*.swift.
IMPORTANT: All files MUST be inside [sources]/ — never at the project root [project]/.
```

#### For backend-engineer dispatch (conditional: backend_required == true):
```
FIRST: Read [project]/.autobot/architecture.md — focus on Backend Requirements, API Contract, Environment Variables sections.
SECOND: Read [sources]/Models/APIContracts.swift to learn exact API request/response types.
Generate a complete Docker-based FastAPI backend in [project]/backend/.
All API endpoints MUST match the API Contract section exactly.
All request/response schemas MUST match [sources]/Models/APIContracts.swift types.
Server MUST start and /health MUST return 200 even with dummy .env values.
Do NOT create, modify, or overwrite files outside [project]/backend/.
Do NOT touch root .gitignore (already configured in Phase 3).
```

### Three-Agent Parallel Pattern (backend_required == true)

When `build-state.json` has `backend_required: true`, Phase 4 dispatches three agents in parallel:

```
Agent(
  subagent_type="ui-builder",
  prompt="[ui-builder task with full context]"
)
Agent(
  subagent_type="data-engineer",
  prompt="[data-engineer task with full context]"
)
Agent(
  subagent_type="backend-engineer",
  prompt="[backend-engineer task with full context]"
)
```

All three write to disjoint directories (`[sources]/Views/` vs `[sources]/Services/` vs `[project]/backend/`) → conflict probability zero.

## Agent Team Integration (Primary Coordination Pattern)

Agent Team을 사용하여 Phase 4의 병렬 에이전트를 조율한다.

### Team 생성

```
TeamCreate(
  name="autobot-<app-name>",
  members=[
    {"name": "ui-builder", "agentType": "autobot:ui-builder", "model": "claude-sonnet-4-6"},
    {"name": "data-engineer", "agentType": "autobot:data-engineer", "model": "claude-sonnet-4-6"},
    {"name": "backend-engineer", "agentType": "autobot:backend-engineer", "model": "claude-sonnet-4-6"}
  ]
)
```

### Communication via SendMessage

Team 멤버 간 상태를 SendMessage로 공유:

```
# 오케스트레이터 → 멤버에게 작업 시작 지시
SendMessage(to="ui-builder", message="[ui-builder task with full context]")
SendMessage(to="data-engineer", message="[data-engineer task with full context]")

# 조건부
if backend_required:
  SendMessage(to="backend-engineer", message="[backend-engineer task with full context]")
```

### 상태 수집

각 멤버가 완료되면 오케스트레이터가 결과를 수신:
- ui-builder → `[sources]/Views/`, `[sources]/ViewModels/`, `[sources]/App/` 생성 완료
- data-engineer → `[sources]/Services/`, `[sources]/Utilities/` 생성 완료
- backend-engineer → `[project]/backend/` 생성 완료
- quality-engineer → 빌드/테스트 결과 보고

### Fallback: Agent Team 미사용 시

Agent Team이 불가능한 환경에서는 일반 Agent 도구로 **병렬 디스패치**:

```
Agent(
  subagent_type="ui-builder",
  prompt="[ui-builder task]"
)
Agent(
  subagent_type="data-engineer",
  prompt="[data-engineer task]"
)
```

파일 소유권 규칙이 충돌을 방지하므로 격리 없이도 안전하다.

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
1. Let the other agent(s) complete
2. Re-dispatch only the failed agent
3. Do NOT re-dispatch all agents
4. Log the failure pattern for retrospective
