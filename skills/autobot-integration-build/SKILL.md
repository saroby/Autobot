---
name: autobot-integration-build
user-invocable: false
description: "Integrate and verify an Autobot iOS app in Phase 5, including compile-error recovery."
---

# Integration & Build Validation

Phase 5 integrates the app and proves its authored feature contracts. Execute the steps below in order. Read only the current step's reference; read completion.md when advancing the gate or handing off exhausted retries. Resolve project paths from the project root and existing `references/` paths from this skill directory.

## Invariants

- `<AppName>/Models/` is frozen. Fix consumers; hand genuine contract defects back to Phase 1.
- Preserve `App/ServiceStubs.swift`. Production repositories and ModelContainer belong in `CompositionRoot.swift`; the app entry uses that composition.
- Honor `architecture.json.seedPolicy`; runtime seeding applies only to `seeded` apps.
- Build-fix limits and error-signature handling come from `spec/pipeline.json` `policies.buildFixLoop` and `policies.circuitBreaker`.
- Every P0 feature needs functional acceptance that proves its declared postcondition. Authored tests must compile and pass.
- Run required checks once. Repeat affected checks after changes or failures; avoid additional test/verification loops after they pass.
- Record missing tool evidence and DEGRADED outcomes accurately. Preserve privacy, signing, accessibility, and preflight-ship checks.

## Step routing

| Step | Read when reached | Work |
|------|-------------------|------|
| 0 | [Project sync](references/step-0.md) | Register new files unless filesystem synchronization already handles them |
| 1 | [Wiring](references/step-1.md) | Wire real repositories; preserve Preview stubs |
| 2 | [Platform](references/step-2.md) | Privacy, entitlements, permissions, package dependencies |
| 3 | [Build-fix loop](references/step-3.md) | Checkpoint, build, diagnose, fix within the spec budget |
| 4 | [Backend](references/step-4.md) | Only when `backend_required == true` |
| 5 | [Authored tests](references/step-5.md) | Functional acceptance and test-result evidence |
| 6 | [Code quality](references/step-6.md) | Required deterministic checks |
| 7 | [Axiom](references/step-7.md) | Critical audit or explicit unavailability |
| 8 | [Peer review](references/step-8.md) | Opposite-runtime review and metadata |
| 9 | [Visual judge](references/step-9.md) | Fidelity evidence and degraded outcomes |
| End | [Completion and recovery](references/completion.md) | Gate 5→6 metadata and retry handoff |

Finish the authorized Phase 5 workflow and report build/test outcomes and remaining evidence gaps concisely. Do not stop for review after the first successful compile.
