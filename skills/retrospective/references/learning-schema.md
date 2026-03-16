# Learnings JSON Schema

## File Location

`.autobot/learnings.json` in the project's working directory.

## Schema

```json
{
  "version": "1.0",
  "lastUpdated": "2026-03-16T12:00:00Z",
  "totalBuilds": 5,
  "successRate": 0.8,
  "builds": [
    {
      "id": "build-001",
      "date": "2026-03-16",
      "appName": "FitnessTracker",
      "ideaSummary": "소셜 피트니스 트래킹 앱",
      "success": true,
      "phases": {
        "architecture": {"duration_sec": 45, "retries": 0},
        "scaffold": {"duration_sec": 30, "retries": 0},
        "ui_build": {"duration_sec": 180, "retries": 0},
        "data_build": {"duration_sec": 120, "retries": 0},
        "quality": {"duration_sec": 90, "retries": 2},
        "deploy": {"duration_sec": 300, "retries": 1}
      },
      "errors": [
        {
          "phase": "quality",
          "type": "compilation",
          "message": "Cannot find type 'ModelContext' in scope",
          "fix": "Added 'import SwiftData' to ViewModel file",
          "recurring": true
        }
      ],
      "notes": "TabView + NavigationStack pattern worked well for this app type"
    }
  ],
  "patterns": {
    "common_build_errors": [
      {
        "pattern": "Cannot find type 'ModelContext'",
        "fix": "Add 'import SwiftData'",
        "frequency": 4,
        "prevention": "Always include SwiftData import in ViewModels that use ModelContext"
      },
      {
        "pattern": "@Model requires class",
        "fix": "Change struct to class for @Model types",
        "frequency": 2,
        "prevention": "Architect should specify 'class' in data model definitions"
      }
    ],
    "effective_architectures": [
      {
        "appType": "social",
        "pattern": "TabView(Home/Search/Profile) + NavigationStack per tab",
        "successRate": 1.0,
        "notes": "Clean separation, minimal agent conflicts"
      },
      {
        "appType": "utility",
        "pattern": "Single NavigationStack with List → Detail",
        "successRate": 1.0,
        "notes": "Simplest pattern, fastest to build"
      }
    ],
    "deployment_tips": [
      "Always check signing identity before archive",
      "Use automatic signing to avoid provisioning issues",
      "API Key method more reliable than Apple ID for CI"
    ],
    "agent_strategies": [
      "ui-builder and data-engineer can always run in parallel",
      "quality-engineer must wait for both to complete",
      "deployer should check prerequisites before starting archive"
    ]
  },
  "improvement_queue": [
    {
      "priority": "high",
      "description": "Add SwiftData import check to ui-builder agent prompt",
      "reason": "Missing import error occurred 4 times",
      "implemented": false
    }
  ]
}
```

## Update Rules

1. **Always append**, never overwrite build history
2. **Increment frequency** for recurring error patterns
3. **Update successRate** on every build: `successRate = successfulBuilds / totalBuilds`
4. **Mark improvements as implemented** when applied
5. **Prune old entries** only if learnings.json exceeds 50KB

## Pattern Detection Thresholds

| Metric | Threshold | Action |
|--------|-----------|--------|
| Same error 3+ times | High | Add prevention to agent prompt |
| Architecture used 2+ times successfully | Medium | Mark as "proven" pattern |
| Deploy failure 2+ times same reason | High | Add prerequisite check |
| Build time > 10min | Low | Analyze bottleneck phase |
