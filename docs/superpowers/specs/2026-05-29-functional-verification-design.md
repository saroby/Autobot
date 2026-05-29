# Functional Verification Spine — Design Spec

**Date:** 2026-05-29
**Status:** Approved design, pending implementation plan
**Scope:** Single spec cycle (cycle 1). North star: **the green checkmark at Gate 5→6 must mean "the app actually does what the idea asked, and works."**

---

## 1. Problem

A green build today proves almost nothing about whether the generated app does what the user's idea asked. Verified facts about the current pipeline (mapped from source):

- **`build_succeeded` is self-attested.** The quality-engineer agent calls `pipeline.sh advance-phase --phase 5 --metadata build_succeeded=true` and Gate 5→6 trusts that boolean (`scripts/gate_checks/build.py:36-54`). The harness never re-runs `xcodebuild` at Phase 5. (Phase 3 scaffold gate *does* run a real `xcodebuild` — `scripts/gate_checks/scaffold.py:75` — so the harness is capable of it.)
- **Authored tests are never run.** quality-engineer writes Swift Testing tests (one per model, basic CRUD) per `skills/autobot-integration-build/SKILL.md` Step 5, but nothing executes them. There is no `xcodebuild test`, no pass/fail gate.
- **`integration_build(test=True)` is dead code.** `scripts/xcodebuild_runner.py:217-254` fully implements `xcodebuild test -resultBundlePath X.xcresult` but has zero callers.
- **`happyPath` is decorative.** `AppIntent.happy_path` (`scripts/intent_spec.py:52`) is parsed and consumed by zero executable code. No XCUITest target exists in generated apps (no `.tap()`, no `XCUIApplication`). "Anchor present" = a regex grep for the `accessibilityIdentifier` literal in source (`scripts/intent_spec.py:103-136`); a hidden/disabled/unreachable button with the right identifier passes.
- **Intent collapses multi-feature ideas to one CTA.** `app-intent.json` carries a single `primaryCTA` + free-text `promise` + ~3 default anchors. Non-primary features have zero verification surface.
- **The gate engine has no DEGRADED state.** A sub-check is satisfied if `passed OR skipped` (`scripts/gate_runner.py:314`). `runtime_smoke` / `visual_contract` / `metadata_readiness` return `skipped=True` (folded into PASS) when the simulator/artifact/tool is unavailable (`scripts/gate_checks/build.py`). On CI with no simulator, green = "compiled + self-attested" with zero runtime evidence.

Net: a green checkmark means "the architect filled ~5 strings, those identifier strings textually appear in Swift source, and the binary launched without crashing for 2-4s." It does **not** mean any feature behaves as the idea asked.

## 2. Goals / Non-goals

**Goals (cycle 1):**
1. Make intent machine-checkable per feature, autonomously (no user checkpoint — preserve the "질문 없이" promise).
2. Actually execute the authored logic/integration tests and gate on real pass/fail.
3. Drive each P0 feature's happy path on the running app and assert observable state changes (not just "anchor exists").
4. Make the gate signal honest: a check that *could* run but didn't is DEGRADED, never silent PASS. Shipping path hard-blocks on DEGRADED.
5. Defend against Goodhart (spec laundering) and verifier mutability (agents "passing" by weakening tests/specs).

**Non-goals (deferred to later cycles):**
- Per-screen *visual* assertions / screenshot diffing as gate truth (cut from cycle 1 — screenshots are debug artifacts only; behavior first).
- XCUITest-target generation (documented future path; cycle 1 uses AXe).
- Interactive intent checkpoint with the user (cluster B's interactive half).
- Recovery-robustness overhaul (cluster C), learning-noise correction (#10).

## 3. Architecture — three pillars

```
idea ──► [Phase 1 architect]
            ├─ architecture.md, Models/, ServiceProtocols.swift   (existing)
            └─ feature-spec.json                                   (NEW — pillar 1)
                  features:[{ id, title, priority, screen, anchor,
                              acceptance:[{ id, kind:"flow"|"logic",
                                            steps[], postcondition }] }]
                  │
       Gate 1→2:  feature_spec_declared  (P0/P1 have ≥1 acceptance + bound anchor)
                  feature_spec_quality    (every P0/P1 acceptance has ≥1 observable
                                           state-changing postcondition — anti-Goodhart)
                  │
       [Phase 4 ui-builder] attaches a per-feature anchor as .accessibilityIdentifier
                  │
       Gate 4→5:  intent_anchors_in_ui   (generalized from single CTA to per-feature)
                  │
       [Phase 5 quality-engineer]
            ├─ (a) LOGIC: run authored Swift Testing tests
            │        integration_build(test=True) → xcodebuild test → parse .xcresult   (pillar 2a)
            │        ★ side effect: build is harness-verified (self-attested boolean retired)
            └─ (b) FLOW: flow_runner.py drives running app via AXe                       (pillar 2b)
                     per happyPath step: describe-ui poll (anchor enabled, frame in bounds)
                     → tap → assert postcondition (state change), per-step debug screenshot
                  │
       Gate 5→6:  build_succeeded            (state_field → corroborated by harness test run)
                  logic_tests_pass    (NEW)  (real .xcresult pass/fail)
                  functional_flows_pass(NEW) (AXe flow + postcondition assertions; P0 hard, P1 soft)
                  + DEGRADED semantics, shipping-path hard-required                       (pillar 3)
```

## 4. Pillar 1 — machine-checkable feature spec (autonomous)

### 4.1 Schema (`scripts/intent_spec.py`, new `FeatureSpec` dataclass beside `AppIntent`)

`.autobot/feature-spec.json`:
```json
{
  "features": [
    {
      "id": "add-workout",
      "title": "Log a workout",
      "priority": "P0",
      "screen": "WorkoutListView",
      "anchor": "autobot.feature.add-workout",
      "acceptance": [
        {
          "id": "add-workout-persists",
          "kind": "flow",
          "steps": [
            {"action": "tap", "anchor": "autobot.feature.add-workout"},
            {"action": "tap", "anchor": "autobot.save"}
          ],
          "postcondition": {
            "kind": "count_increased",
            "anchorList": "autobot.workout.list",
            "by": 1
          }
        }
      ]
    }
  ]
}
```

`acceptance[].kind`:
- `"logic"` — asserted by a Swift Testing/integration test (pillar 2a). `postcondition` describes the model-level invariant (e.g., repository round-trip).
- `"flow"` — asserted by AXe-driven UI walk (pillar 2b).

`postcondition.kind` (closed enum — the anti-Goodhart lever): one of
`count_increased`, `count_decreased`, `value_persisted_after_relaunch`, `navigated_to`, `artifact_generated`, `setting_stored`. **`anchor_exists` / `tapped` are NOT valid postconditions** — they are necessary preconditions, not evidence of behavior.

### 4.2 Producer rules (`agents/architect.md`)

The architect emits `feature-spec.json` autonomously, but derives acceptance by **conservative rules**, not free invention:
- Every feature's `screen` MUST reference a screen named in `architecture.md`; every `anchor` becomes a `ui-builder` obligation.
- Every P0/P1 feature's acceptance postcondition MUST be grounded in an already-emitted artifact: a SwiftData model (for `count_*`, `value_persisted_*`, `setting_stored`), a named screen (`navigated_to`), or an explicit output (`artifact_generated`).
- A feature whose behavior cannot be expressed as an observable postcondition from the idea+architecture is downgraded to P2 (verified by anchor presence only, not gated).

### 4.3 Gate 1→2 checks (`scripts/gate_checks/capability.py`, registered in `gate_runner.py` + `spec/pipeline.json`)

- `feature_spec_declared` — `feature-spec.json` exists and validates; every P0/P1 feature has ≥1 acceptance and a bound `anchor`. (Replaces the soft, single-CTA `app_intent_declared` as the spine; `app-intent.json` may remain as a compatibility shim feeding `FeatureSpec`.)
- `feature_spec_quality` — every P0/P1 acceptance has a `postcondition` of an allowed observable kind. Fails if any acceptance is anchor-only. **This is the primary defense against fake green.**

## 5. Pillar 2 — hybrid verification

### 5.1 (a) Logic tests — wire the dead code

- A **unit-test target** is added to the scaffold (`skills/autobot-ios-scaffold/scripts/create-xcode-project.sh` + `generate-pbxproj.py`). This is required regardless of mechanism choice; unit-test targets are far less flaky than UI-test targets.
- New gate check `logic_tests_pass` (`scripts/gate_checks/functional.py`) calls `integration_build(test=True)` (`scripts/xcodebuild_runner.py:217`) → `xcodebuild test -resultBundlePath …xcresult` with `-retry-tests-on-failure -test-iterations 2`, parses the `.xcresult` for real pass/fail.
- **D1 resolution:** because this compiles + runs the app target, the build is independently harness-verified. `build_succeeded` metadata is demoted to audit-only; the gate's source of truth is the harness `.xcresult`.
- **Acceptance binding (cycle 1):** `logic_tests_pass` requires the authored test suite to compile and pass. Binding a `kind:"logic"` acceptance to a specific test is by convention — quality-engineer names the test after the acceptance `id`. A soft completeness sub-check warns when a P0 `logic` acceptance has no correspondingly-named test; it does not hard-fail in cycle 1 (avoids over-coupling before the naming convention is proven).

### 5.2 (b) Flow driver — `scripts/flow_runner.py` (NEW)

- Reuses `sim_runtime.py` boot/install/launch (sim_runtime keeps its launch/liveness responsibility; not modified beyond what's needed to expose a launched-session handle).
- For each P0 (hard) and P1 (soft) feature's `kind:"flow"` acceptance:
  1. **Semantic wait, not sleep:** poll `axe describe-ui` until the step's target anchor is present AND `enabled:true` AND its `frame` is within screen bounds, up to a timeout (the AXe equivalent of `waitForExistence`/`isHittable`). Closes the static-grep gap with real rendered truth.
  2. `axe tap --id <anchor>` (preferred over coordinates).
  3. Assert the acceptance `postcondition` by re-running `describe-ui` (e.g., `count_increased`: list anchor's child count delta; `navigated_to`: destination anchor appears; `value_persisted_after_relaunch`: relaunch via simctl, re-query).
  4. Capture a per-step screenshot as a **debug artifact only** (not a gate assertion — cut from cycle 1 per decision).
- Per-step bounded retry with backoff; first-launch permission prompts pre-granted via `simctl privacy` in Phase 0; animations suppressed via launch arg/env.
- New gate check `functional_flows_pass` (`scripts/gate_checks/functional.py`): **all P0 flows must pass (hard); P1 flows verified-but-soft** (failure → warning/degraded note, not gate fail) in cycle 1.

### 5.3 AXe as an external capability (D3)

- Phase 0 `env_snapshot` records `axe` availability + version (preflight), alongside the existing tool detections. Version is pinned/documented.
- "axe unavailable" is classified **DEGRADED**, never PASS (see pillar 3).
- XCUITest-target generation is documented as the future, more-defensible shipping verifier.

## 6. Pillar 3 — honest signal (DEGRADED) + anti-laundering

### 6.1 DEGRADED gate state

- `scripts/gate_runner.py:314` rollup: a skipped sub-check no longer counts as satisfied for a green verdict. Compute `passed` strictly on `passed`; surface a `degraded` flag when any required sub-check is skipped-because-unrunnable.
- `scripts/gate_persistence.py:43`: status minting extended to emit `degraded` (passed-with-unrunnable-checks). No schema migration — gate-evidence status is not enum-constrained by `spec.statuses` (which governs phase status). Verify `state_store.collect_schema_issues` does not reject the gates subtree (it currently does not inspect gate status values).

### 6.2 Enforcement boundary (D2)

- `/autobot:mvp` (local): DEGRADED is **allowed** — the build proceeds, but the run-summary and CLI output show **DEGRADED: functional checks not run**, visibly non-green. Never confusable with PASS.
- `/autobot:testflight` and `/autobot:app-review` (shipping): `logic_tests_pass` + `functional_flows_pass` (P0) are **hard-required**. DEGRADED hard-blocks.
- **Anti-laundering (codex):** the shipping path does NOT trust a stale green/`build_succeeded` flag. Concretely, on `/autobot:testflight` / `/autobot:app-review` entry, the deployer reads the current `build-state.json` Gate 5→6 evidence and requires `logic_tests_pass` + `functional_flows_pass` (P0) to be **`passed` (not `degraded`, not absent)** for the current build. If they are degraded/absent, the shipping path **blocks** with guidance to re-run `/autobot:mvp` (or `/autobot:resume --phase 5`) on a host with a working simulator + AXe so the functional checks execute for real. The build is not re-archived from a degraded state; verification is re-earned, not re-trusted.

### 6.3 DEGRADED normalization risk

CLI wording and `run-summary` must make DEGRADED painful/visible (badge: `VERIFIED` vs `DEGRADED (functional unverified)`), so teams don't quietly accept it.

## 7. Recovery — separate functional-fix loop (D4)

When `logic_tests_pass` or `functional_flows_pass` fails, do **not** route through the Phase 5 build-fix loop. Use a **separate bounded functional-fix loop**:

- **max 2 attempts.**
- **Ownership routing by failure type:**
  - compile / test-infra failure → quality-engineer
  - model/data assertion failure → data-engineer + quality-engineer
  - anchor missing / disabled / navigation failure → ui-builder + quality-engineer
  - acceptance/spec ambiguity → **FAIL** (do not auto-weaken)
- **Immutability invariant (anti verifier-mutability):** during a functional-fix retry, `feature-spec.json` and the generated acceptance/test files are **forbidden to edit** — enforced via the existing `fileOwnership.forbiddenInfra` + sandbox mechanism (`spec/pipeline.json` + `scripts/agent-sandbox.sh`). The fixer changes app behavior, never the verifier.
- A separate, rare **spec-correction path** may edit `feature-spec.json` only if the spec is proven invalid against the idea+architecture — gated, not part of the normal fix retry.

## 8. Scope summary (cycle 1)

| In | Out (deferred) |
|----|----|
| feature-spec.json + 2 gate-1→2 checks | per-screen visual assertions |
| logic_tests_pass (wire dead code) + unit-test target | XCUITest target generation |
| functional_flows_pass via AXe (P0 hard, P1 soft) | interactive intent checkpoint |
| DEGRADED state + shipping hard-block + anti-laundering | recovery-robustness overhaul, learning-noise |
| functional-fix loop (max 2, immutable verifier) | |

## 9. Affected files (grounded in map)

| File | Change |
|----|----|
| `scripts/intent_spec.py` | `FeatureSpec` dataclass, `load/validate_feature_spec` (postcondition enum), generalize `find_unused_anchors` to per-feature |
| `agents/architect.md` | emit `feature-spec.json` with conservative derivation rules; fix stale `architectureSchema` reference (`architect.md:93`) |
| `scripts/gate_checks/capability.py` | `feature_spec_declared`, `feature_spec_quality`; generalize `intent_anchors_in_ui` |
| `scripts/flow_runner.py` (NEW) | AXe describe-ui poll + tap + postcondition assertions |
| `scripts/gate_checks/functional.py` (NEW) | `logic_tests_pass`, `functional_flows_pass` |
| `scripts/xcodebuild_runner.py` | wire `integration_build(test=True)` (currently dead) |
| `scripts/gate_runner.py` | register new checks; DEGRADED rollup (`:314`) |
| `scripts/gate_persistence.py` | mint `degraded` status (`:43`) |
| `scripts/sim_runtime.py` | expose launched-session handle for flow_runner (minimal) |
| `skills/autobot-ios-scaffold/scripts/create-xcode-project.sh` + `generate-pbxproj.py` | add unit-test target |
| `skills/autobot-integration-build/SKILL.md` | Step 5: run tests; generate flow + logic acceptance tests from feature-spec |
| `spec/pipeline.json` | Gate 1→2 / 4→5 / 5→6 checks; functional-fix-loop policy; axe preflight; shipping hard-required flags |
| `agents/ui-builder.md` | attach per-feature anchors (not just primaryCTA) |

## 10. Testing strategy (how we verify these changes)

The repo has a python `tests/` suite (pytest) and CI (`.github/workflows/ci.yml`). For each change:
- **Unit (pytest):** `FeatureSpec` validation (valid/invalid postcondition kinds, anchor-only rejection), `feature_spec_quality` accept/reject cases, DEGRADED rollup logic, `gate_persistence` degraded status, flow_runner postcondition evaluation against fixture `describe-ui` JSON, `logic_tests_pass` parsing of a fixture `.xcresult`. Mirror existing test style (`tests/test_intent_spec.py`, `tests/test_visual_contract.py`).
- **Contract:** `cmd_list_checks` (`gate_runner.py`) flags any check declared in `spec/pipeline.json` but unimplemented — built-in wiring guard; new checks must be registered.
- **Smoke E2E:** extend `scripts/smoke-e2e.sh` to exercise a minimal feature-spec → flow_runner path against the throwaway smoke app (AXe present case + AXe-absent DEGRADED case).
- No change is "done" until `tests/run_tests.sh` passes and the schema/drift CI checks are green.

## 11. Decision log (codex consulted; final calls are ours)

- **D1** harness re-verify build — ADOPTED (codex: agree). `xcodebuild test` proves compile+test+artifact; self-attested boolean retired to audit.
- **D2** DEGRADED boundary — ADOPTED + anti-laundering (codex: agree, must be visibly non-green; shipping must re-run, not trust prior flags).
- **D3** AXe for cycle 1 — ADOPTED (codex: agree, treat as pinned/preflighted external capability; absence = DEGRADED; XCUITest is future).
- **D4** recovery — codex's design ADOPTED over original (separate bounded loop, ownership routing, immutable verifier; never feed Phase 5 build-fix loop).
- **D5** Goodhart — `feature_spec_quality` postcondition gate ADOPTED as cycle-1's most important addition. Cut per-step visual assertions; behavior first.

**Top risks tracked:** spec laundering, verifier mutability, AXe flake/timing, single-happy-path bias, DEGRADED normalization, no-oracle inference. Mitigations are wired into pillars 1/3 and the fix-loop immutability invariant.
