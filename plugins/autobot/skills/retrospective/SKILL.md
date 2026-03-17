---
name: autobot-retrospective
description: Use after an Autobot build completes (success or failure), when checking past build history, or when analyzing build performance trends.
---

# Build Retrospective & Self-Improvement

Capture learnings from each Autobot build to continuously improve the build process.

## When to Trigger

- After every `/autobot:build` completion (success or failure)
- When analyzing past build performance
- When the build encounters a novel error pattern

## Retrospective Process

### 1. Collect Build Metrics

Gather from the build session:
- Total duration per phase
- Number of build retries needed
- Types of errors encountered
- Agent success/failure rates
- Deployment outcome

### 2. Analyze Patterns

Compare with past builds in `.autobot/learnings.json`:
- Recurring error patterns (same fix applied multiple times)
- Architecture decisions that led to cleaner code
- Agent dispatch strategies that worked well
- Deployment blockers and their solutions

### 3. Update Learnings File

Write to `.autobot/learnings.json` following the schema in `references/learning-schema.md`.

Key sections to update:
- `builds[]` — Add new build entry
- `patterns.common_build_errors` — New error patterns
- `patterns.effective_architectures` — What worked
- `patterns.deployment_tips` — Upload/signing lessons
- `patterns.agent_strategies` — Parallel execution lessons

### 4. Generate Improvement Recommendations

Based on accumulated data:
- If the same error appears 3+ times → add it to the architect's constraints
- If a certain app type builds faster → note the architecture pattern
- If deployment fails consistently → flag prerequisite check needed

## Learning Application

At the start of each new build (Phase 0), read `.autobot/learnings.json` and:
1. Apply known error prevention patterns
2. Use proven architecture patterns for similar app types
3. Skip known-failing deployment methods
4. Adjust agent prompts based on past performance

## Additional Resources

- **`references/learning-schema.md`** — JSON schema for learnings file with examples
