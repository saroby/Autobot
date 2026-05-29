# E2E Verification Proof — Design Spec

**Date:** 2026-05-29
**Status:** Approved design, pending implementation
**Cycle:** 2 (follows the functional-verification-spine cycle)

## 1. Problem

The functional-verification spine (cycle 1) added gate checks (`check_logic_tests_pass`, `check_functional_flows_pass`) that are supposed to prove a generated app actually works. But the maturity audit (2026-05-29) scored "verification rigor" 5/10 and "real-world E2E" 4/10 for one reason: **those checks have never run against a real app on a real Mac.** Every test mocks the `xcodebuild`/`simctl`/AXe boundary; the nightly `smoke-e2e.yml` builds (not tests) a hand-rolled stub and never invokes the gate; and it has never even succeeded in CI (it used `macos-15`, which has no Xcode 26). So a green checkmark is proven only at the unit-of-logic level, never end-to-end.

**Smoke-detector analogy:** we installed the detector but never lit a fire to confirm it goes off.

## 2. Goal / Non-goals

**Goal:** Prove — by actually running them against real apps on a real iOS 26 simulator — that the shipped verification path (AXe-driven `check_functional_flows_pass` + `xcodebuild test`–driven `check_logic_tests_pass`) **passes a working app and FAILS a deliberately broken one.** Deliver the proof two ways: (1) executed locally on this Mac (observable, real), (2) automated in CI on `macos-26`.

**Mechanism decision (user-approved):** prove the **actual shipped path (AXe)**, not a substitute. Research recommends XCUITest as the more CI-robust long-term verifier; that migration is explicitly a **future cycle**, noted but out of scope here.

**Non-goals (structural limits, stated honestly):**
- The full pipeline's LLM stages (Phase 1 architect, Phase 4 ui-builder/data-engineer) **cannot run in CI/headless** (they need Claude). E2E therefore uses **committed fixture apps**, not idea→app generation. The "one-line idea → working code" leap remains unproven by automation — acknowledged, not solved.
- Not running the entire 11-check Gate 5→6 (peer review, axiom audit, learnings-consumed, metadata, stub-wiring all need heavy fixture faking). We exercise the two NEW checks directly — the exact mechanism the audit found unproven.
- Migrating the verifier to XCUITest. Quick-win doc fixes (README setup ordering) are out of scope except the stale CI test-count string.

## 3. Architecture

Two committed fixture iOS 26 apps + an e2e harness that drives the two real verification checks against them on a booted iOS 26 simulator, run both locally and in CI.

```
tests/e2e/fixtures/
  GreenApp/   — minimal SwiftUI iOS26 app that WORKS:
                top-level (non-scrolling) "Add" CTA (autobot.add) +
                count label (autobot.count); tap → SwiftData insert → count++.
                + @Test func named after the logic acceptance id (round-trip).
                + .autobot/feature-spec.json (1 P0 flow accept: count_increased,
                  1 P0 logic accept) + minimal build-state.json.
  RedApp/     — identical BUT the Add CTA is wired to nothing (count never
                changes) → the P0 count_increased flow MUST fail.

scripts/e2e_verify.py   — the harness: boots an iOS26 sim, builds+installs a
                          fixture, runs check_logic_tests_pass +
                          check_functional_flows_pass against it, asserts the
                          expected verdict. Exit 0 on all-expectations-met.
scripts/e2e-verify.sh   — thin wrapper: env preflight (xcode-select, downloadPlatform,
                          axe install check, sim create/boot/bootstatus), then e2e_verify.py.
.github/workflows/e2e-verify.yml — macos-26 CI wrapper (replaces smoke-e2e.yml).
```

**Why exercise the checks directly (not full `run-gate 5->6`):** the new checks are the unproven mechanism. Running them directly (`check_logic_tests_pass(fixture, app, state)` and `check_functional_flows_pass(...)`) is the tightest possible proof and avoids faking 9 unrelated gate checks. The harness asserts:
- GreenApp → `check_logic_tests_pass` passed AND `check_functional_flows_pass` passed.
- RedApp → `check_functional_flows_pass` **hard-fails** (P0 `count_increased` did not happen). This proves the gate catches a non-working app — not just that it rubber-stamps a working one.

## 4. Local proof (the core deliverable)

Implementation **step 1 is a feasibility spike**: `brew tap cameroncooke/axe && brew install axe`, boot an iOS 26 sim on this Mac, launch a stock app, run `axe describe-ui` and confirm it returns a real accessibility tree headlessly. This Mac has Xcode 26.5 + iOS 26.0–26.5 runtimes (verified), so it can run the whole thing. If the spike fails (AXe can't drive the sim here), STOP and revisit the mechanism (the XCUITest fallback) before building fixtures.

After the spike passes, I run `scripts/e2e-verify.sh` against both fixtures on this Mac and capture the VERIFIED (GreenApp) + FAIL (RedApp) output as the actual proof that closes the audit gap.

## 5. CI workflow (`e2e-verify.yml`, replaces smoke-e2e.yml)

- `runs-on: macos-26` (GA since 2026-02-26; default Xcode 26.4.1 + iOS 26.0–26.5 sims pre-installed). Pin via `sudo xcode-select -s /Applications/Xcode_26.4.1.app`.
- `xcodebuild -downloadPlatform iOS` (safety net for runtime pruning).
- `brew tap cameroncooke/axe && brew install axe`.
- **Early AXe smoke** (boot sim, launch a trivial app, `axe describe-ui`, assert a known anchor) → fail-fast if the headless AX path is unavailable, before the full run.
- `xcrun simctl create + boot + bootstatus -b` an iPhone 17 / iOS 26 device; pass its UDID to the harness (work around runner-images device-clone flakiness).
- Run `scripts/e2e-verify.sh`.
- On failure: upload `axe screenshot` PNGs + `describe-ui` JSON + `.xcresult` as artifacts.
- **Triggers:** `pull_request` + `push:main` **path-filtered** to `scripts/flow_runner.py`, `scripts/gate_checks/functional.py`, `scripts/sim_runtime.py`, `tests/e2e/**`, the workflow itself (slow 4–6 min macOS job shouldn't run on unrelated PRs) + `workflow_dispatch`.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| AXe HID-tap fails inside scroll lists (issue #42) — hits `count_increased` | Fixture CTA + count label are top-level, never inside a List/ScrollView |
| AXe unproven headless on GitHub runners (medium confidence) | Local spike first (this Mac); early CI smoke fails fast; XCUITest fallback documented |
| Cold sim boot 4–6 min in CI | `simctl bootstatus -b`; generous timeouts; flow_runner already uses semantic waits (no sleeps) |
| iOS 26 runtime pruned from runner | `xcodebuild -downloadPlatform iOS` before use |
| Sim device-clone flakiness (runner-images #12777) | Explicit `simctl create+boot`, target `-destination id=$UDID` |

## 7. Testing (how we validate the test itself)

- **The real proof:** I run `scripts/e2e-verify.sh` on this Mac and show GreenApp=VERIFIED, RedApp=FAIL.
- **Harness unit tests:** the result-aggregation/assertion logic in `e2e_verify.py` gets a stdlib-unittest test with mocked check outputs (pass/fail/degraded → correct exit code), runnable in the existing ubuntu suite.
- **Negative case is first-class:** RedApp failing is an assertion, not a side note — it proves the detector detects.
- Fix the stale `ci.yml` "185 tests" string → actual count.

## 8. Decision log
- Mechanism: prove real AXe path (user-approved A); XCUITest = future cycle.
- Scope: two new checks directly, not full gate; fixture-based, not idea→app.
- CI: macos-26, PR-gating with path filter.
- Order: feasibility spike FIRST (de-risk before building fixtures).
