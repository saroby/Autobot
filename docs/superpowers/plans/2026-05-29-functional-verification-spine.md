# Functional Verification Spine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Gate 5→6 green checkmark mean "the generated app actually does what the idea asked, and works" — by emitting a machine-checkable feature-spec, running the authored logic tests for real, driving each P0 feature's happy path via AXe, and making the gate signal honest (DEGRADED, never silent pass) with a shipping hard-block.

**Architecture:** Three pillars on top of the existing python/bash gate engine — (1) `feature-spec.json` (autonomous, architect-emitted) validated at Gate 1→2; (2) hybrid verification at Gate 5→6 = run authored Swift Testing tests via the (currently dead) `integration_build(test=True)` + AXe-driven flow assertions in a new `flow_runner.py`; (3) a DEGRADED gate verdict so unrunnable behavioral checks lower the signal instead of silently passing, with shipping (`/autobot:testflight`, `/autobot:app-review`) hard-blocking on DEGRADED via a preflight.

**Tech Stack:** Python 3 (stdlib `unittest`, NOT pytest), bash, `spec/pipeline.json` gate spec (SSOT), `xcodebuild test` + `xcresulttool`, AXe CLI (`brew install axe`), `xcrun simctl`, xcodegen/pbxproj scaffold.

**Source spec:** `docs/superpowers/specs/2026-05-29-functional-verification-design.md` (decisions D1–D5, all 5 user-confirmed knobs).

**Branch:** `feat/functional-verification-spine`.

---

## Execution order & integration notes (READ FIRST)

The 6 work-streams below were drafted in parallel against the live files under one locked shared contract. They are mutually consistent, but six integration facts MUST be honored or the build breaks:

1. **Tests are stdlib `unittest`, not pytest.** The canonical runner is `bash tests/run_tests.sh` (→ `python3 -m unittest discover -s tests -v`). Every task's tests are `unittest.TestCase` subclasses. Where a task body says "pytest", read it as "the unittest suite" — the classes also collect under pytest if it's ever installed, but do not rely on pytest being on PATH.

2. **Land in dependency order:** WS2 → WS1 → WS5 → WS3 → WS4 → WS6.
   - **WS2** (`_ok` degraded kwarg + three-valued `run_gate` + `build_gate_evidence` status) is foundational — every degraded-emitting check depends on the extended `_ok`. Land it first.
   - **WS1** (feature-spec dataclasses/loaders in `intent_spec.py`) is foundational for WS5/WS3/WS4.

3. **`scripts/gate_checks/functional.py` is ONE module written by three streams — MERGE, never overwrite.**
   - WS3 **creates** `functional.py` with the canonical `check_logic_tests_pass` (rich `.xcresult` parsing via `xcresulttool`).
   - WS4 **appends** `check_functional_flows_pass` + its helper seams. **DROP WS4's placeholder `check_logic_tests_pass`** — WS3's is canonical; do not define it twice.
   - WS6 **appends** `check_functional_verification_passed`.
   - Final `functional.py` exports exactly three checks: `check_logic_tests_pass`, `check_functional_flows_pass`, `check_functional_verification_passed`.

4. **`intent_spec.py` FeatureSpec API is owned by WS1.** WS5's "Task 0" is an idempotent guard — **SKIP it** (WS1 already landed identical signatures). WS5 still contributes the new helper `find_missing_feature_anchors(project_root, app_name) -> list[(featureId, anchor)]`.

5. **Landing-order CI guard.** `bash scripts/pipeline.sh schema` and `gate_runner.py list-checks` FAIL if `spec/pipeline.json` names a procedural check absent from the `GATE_CHECKS` registry. Therefore, in every task that appends a `{"type":"procedural","name":...}` descriptor to `spec/pipeline.json`, register the function in `GATE_CHECKS` **and** import it in `gate_runner.py` **in the same commit**. The two Gate 5→6 entries (`logic_tests_pass`, `functional_flows_pass`) must not be committed to the spec until BOTH functions exist and are registered (i.e. commit the spec entry for `functional_flows_pass` in WS4, after WS3's `logic_tests_pass` is already registered).

6. **Anti-laundering — the real block is a PREFLIGHT, not gate 6→7.** Gate 6→7 is `soft:true` and runs at `advance-phase` AFTER archive/upload, so adding `functional_verification_passed` to 6→7 alone does NOT block shipping. The actual hard block is a fresh `pipeline.sh run-gate --gate "5->6"` in `commands/testflight.md` and `commands/app-review.md` BEFORE the deployer dispatch/archive, aborting if `state.gates["5->6"].status != "passed"`. The 6→7 check + run-summary badge are for the audit trail. (This refines spec §6.2, which assumed the deployer could block post-hoc.)

7. **axiom-data is deferred to implementation, not planning.** The SwiftData round-trip assertions — WS3's authored-test guidance and WS4's `value_persisted_after_relaunch` / `count_increased` postconditions — touch SwiftData behavior. Before writing the Swift-side test/assertion code for those tasks, invoke the `axiom-data` skill for current SwiftData test patterns (model context isolation, in-memory containers, relaunch persistence). The python harness code in this plan does not need it; the generated-app assertions do.

---

## Conventions (apply to every task)

- **Run tests:** `bash tests/run_tests.sh` (or scope: `python3 -m unittest discover -s tests -v -k <name>`).
- **Gate spec sanity after any `spec/pipeline.json` edit:** `bash scripts/pipeline.sh schema` then `python3 scripts/gate_runner.py list-checks` (expect 0 unimplemented procedurals).
- **Spec-drift CI:** `.github/workflows/ci.yml` runs schema + drift + unit tests on push/PR — keep all three green.
- **Commit cadence:** one commit per task (TDD: failing test → impl → passing test → commit). Frequent, small.
- **State mutation:** only via `scripts/pipeline.sh` paths; never hand-edit `build-state.json`.

---

## WS2 — DEGRADED three-valued gate verdict (land FIRST)

## Work-stream: DEGRADED three-valued verdict in the gate engine

**Context verified against the actual files (line numbers are exact at time of writing):**
- `scripts/gate_checks/_helpers.py:35-39` — `_ok` currently has signature `_ok(check, passed, message, *, skipped=False)`.
- `scripts/gate_runner.py:310-319` — `run_gate` rollup loop computes `group_passed = all(r["passed"] or r.get("skipped", False) ...)` and returns `{"gate","passed","soft","checks"}` with each group `{"check","passed","sub_checks"}`.
- `scripts/gate_runner.py:322-342` — `format_text` renders the gate header (`PASS`/`SOFT FAIL`/`FAIL`) and per-sub-check icons (`⊘`/`✓`/`✗`).
- `scripts/gate_persistence.py:33-53` — `build_gate_evidence` mints `status = "passed" if passed else ("soft_failed" if soft else "failed")` at line 43.
- `scripts/phase_advance.py:158-160` — `gate_passed = gate_result.get("passed", False)`, `gate_soft = gate_result.get("soft", False)`, `success_path = gate_passed or gate_soft`. Because a DEGRADED gate keeps `passed=True`, `success_path` stays `True` and the phase advances. **No change needed in phase_advance.py** — confirmed by the test in Task 5.
- `scripts/state_store.py:131-198` (`collect_schema_issues`) validates ONLY **phase** `status` against `spec["statuses"]` (lines 179-181). `state.gates[gate_id].status` is written verbatim with no enum validation. Therefore a `"degraded"` gate status is **never rejected** by the schema. **No change needed in state_store.py** — confirmed by Task 4 writing real evidence through `mutate_state_with_validation` indirectly (the unit test asserts the string; the e2e test in Task 5 proves no write rejection).

**Test harness reality:** the suite is stdlib `unittest` (`tests/run_tests.sh` runs `python3 -m unittest discover -s tests -v`), NOT pytest. New tests subclass `unittest.TestCase`, import runtime modules via `import_runtime_modules()` from `conftest`, and for the e2e advance test subclass `IsolatedProjectCase`. This mirrors `tests/test_advance_phase_atomic.py` / `tests/test_visual_contract_gates.py`.

Run all tests from repo root with:
```
bash /Users/louis/Code/Autobot/tests/run_tests.sh
```
Run a single new module with:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py
```

---

### Task 1: Extend `_ok` with a `degraded` kwarg

**Files**
- Test: `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` (new — this module hosts Tasks 1, 2, 3, 4 unit tests)
- Impl: `/Users/louis/Code/Autobot/scripts/gate_checks/_helpers.py`

**Steps**

- [ ] Write the failing test. Create `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` with the `_ok` cases first (the rest of the file is filled in by later tasks; write the whole file now so later tasks only add methods):

```python
"""Three-valued (passed / degraded / failed) gate verdict — unit + e2e cover.

stdlib unittest only (see tests/run_tests.sh). Mirrors test_advance_phase_atomic.py.
"""

from __future__ import annotations

import unittest

from conftest import IsolatedProjectCase, import_runtime_modules, run_pipeline

import_runtime_modules()

from gate_checks._helpers import _ok  # noqa: E402
from gate_persistence import build_gate_evidence  # noqa: E402
from gate_runner import format_text, run_gate  # noqa: E402


# ── shared fakes ────────────────────────────────────────────────────────────

def _benign_skip(label="benign"):
    return _ok(label, True, "n/a on this path", skipped=True)


def _degraded_skip(label="degraded"):
    return _ok(label, False, "no simulator", skipped=True, degraded=True)


def _hard_fail(label="hardfail"):
    return _ok(label, False, "really broke")


def _green(label="green"):
    return _ok(label, True, "ok")


def _stub_spec_one_group():
    """Minimal spec with a single gate whose one check is a procedural hook
    we control via monkeypatching GATE_CHECKS."""
    return {
        "gates": {
            "5->6": {
                "fromPhase": "5",
                "toPhase": "6",
                "soft": False,
                "checks": [{"type": "procedural", "name": "_test_hook"}],
            }
        }
    }


# ── Task 1: _ok degraded kwarg ───────────────────────────────────────────────

class TestOkDegradedKwarg(unittest.TestCase):

    def test_plain_ok_has_no_degraded_or_skipped(self):
        r = _ok("c", True, "msg")
        self.assertNotIn("skipped", r)
        self.assertNotIn("degraded", r)
        self.assertTrue(r["passed"])

    def test_benign_skip_sets_skipped_only(self):
        r = _ok("c", True, "n/a", skipped=True)
        self.assertTrue(r["skipped"])
        self.assertNotIn("degraded", r)

    def test_degraded_skip_sets_both_flags(self):
        r = _ok("c", False, "no sim", skipped=True, degraded=True)
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])
        self.assertFalse(r["passed"])

    def test_degraded_without_skip_still_records_flag(self):
        # degraded is independent of skipped on the helper; the rollup decides meaning.
        r = _ok("c", False, "x", degraded=True)
        self.assertTrue(r["degraded"])
        self.assertNotIn("skipped", r)


# ── Task 2: run_gate three-valued rollup (filled in Task 2) ──────────────────


# ── Task 3: format_text DEGRADED marker (filled in Task 3) ───────────────────


# ── Task 4: build_gate_evidence status minting (filled in Task 4) ────────────


# ── Task 5: phase advances on degraded (filled in Task 5, IsolatedProjectCase)


if __name__ == "__main__":
    unittest.main()
```

- [ ] Run it — expect FAIL on the degraded cases (current `_ok` rejects the `degraded=` kwarg with `TypeError`):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestOkDegradedKwarg
```
Expected: `test_degraded_skip_sets_both_flags` and `test_degraded_without_skip_still_records_flag` ERROR with `TypeError: _ok() got an unexpected keyword argument 'degraded'`.

- [ ] Apply the minimal impl. In `/Users/louis/Code/Autobot/scripts/gate_checks/_helpers.py`, replace lines 35-39.

  **Before:**
```python
def _ok(check: str, passed: bool, message: str, *, skipped: bool = False) -> dict[str, Any]:
    r: dict[str, Any] = {"check": check, "passed": passed, "message": message}
    if skipped:
        r["skipped"] = True
    return r
```

  **After:**
```python
def _ok(
    check: str, passed: bool, message: str, *,
    skipped: bool = False, degraded: bool = False,
) -> dict[str, Any]:
    r: dict[str, Any] = {"check": check, "passed": passed, "message": message}
    if skipped:
        r["skipped"] = True
    if degraded:
        r["degraded"] = True
    return r
```

- [ ] Re-run — expect PASS:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestOkDegradedKwarg
```
Expected: 4 tests OK.

- [ ] Commit:
```
cd /Users/louis/Code/Autobot && git add scripts/gate_checks/_helpers.py tests/test_degraded_verdict.py && git commit -m "feat(gate): _ok gains degraded kwarg (three-valued verdict groundwork)"
```

---

### Task 2: Rewrite `run_gate`'s per-group rollup + return to the three-valued model

**Files**
- Test: `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` (add `TestRunGateRollup`)
- Impl: `/Users/louis/Code/Autobot/scripts/gate_runner.py`

**Steps**

- [ ] Add the failing test class. In `test_degraded_verdict.py`, replace the `# ── Task 2 ...` comment line with:

```python
class TestRunGateRollup(unittest.TestCase):
    """run_gate must distinguish benign-skip (green), degraded-skip (degraded),
    and hard-fail (red). Drives a single procedural group via a monkeypatched
    GATE_CHECKS entry so we control the exact sub_checks."""

    def setUp(self):
        import gate_runner
        self.gate_runner = gate_runner
        self._orig = dict(gate_runner.GATE_CHECKS)

    def tearDown(self):
        self.gate_runner.GATE_CHECKS.clear()
        self.gate_runner.GATE_CHECKS.update(self._orig)

    def _run_with_subs(self, subs):
        from pathlib import Path
        self.gate_runner.GATE_CHECKS["_test_hook"] = lambda pd, app, st: subs
        return run_gate("5->6", Path("/tmp"), "TestApp", {}, _stub_spec_one_group())

    def test_all_green_is_passed_not_degraded(self):
        r = self._run_with_subs([_green(), _benign_skip()])
        self.assertTrue(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertTrue(r["checks"][0]["passed"])
        self.assertFalse(r["checks"][0]["degraded"])

    def test_benign_skip_alone_stays_green(self):
        # backend_required N/A skip must NOT lower the gate.
        r = self._run_with_subs([_benign_skip()])
        self.assertTrue(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertFalse(r["checks"][0]["degraded"])

    def test_degraded_skip_keeps_passed_true_but_marks_degraded(self):
        r = self._run_with_subs([_green(), _degraded_skip()])
        self.assertTrue(r["passed"], "degraded must keep passed=True so mvp advances")
        self.assertTrue(r["degraded"])
        self.assertTrue(r["checks"][0]["degraded"])
        self.assertFalse(r["checks"][0]["passed"], "a degraded group is not green")

    def test_hard_fail_makes_gate_fail_not_degraded(self):
        r = self._run_with_subs([_green(), _hard_fail()])
        self.assertFalse(r["passed"])
        self.assertFalse(r["degraded"], "a failed gate is red, not degraded")
        self.assertFalse(r["checks"][0]["passed"])

    def test_hard_fail_dominates_degraded(self):
        # When a group has both a degraded skip and a real failure, it is a hard fail.
        r = self._run_with_subs([_degraded_skip(), _hard_fail()])
        self.assertFalse(r["passed"])
        self.assertFalse(r["degraded"])
        self.assertFalse(r["checks"][0]["degraded"], "hard_fail group is red, degraded suppressed")

    def test_top_level_has_degraded_key_always(self):
        r = self._run_with_subs([_green()])
        self.assertIn("degraded", r)
        self.assertIn("degraded", r["checks"][0])
```

- [ ] Run it — expect FAIL (current `run_gate` returns no `degraded` key and treats a degraded skip as green):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestRunGateRollup
```
Expected: `test_*` referencing `r["degraded"]` / `r["checks"][0]["degraded"]` ERROR with `KeyError: 'degraded'`.

- [ ] Apply the minimal impl. In `/Users/louis/Code/Autobot/scripts/gate_runner.py`, replace the rollup loop + return (lines 307-319).

  **Before:**
```python
    all_results: list[dict] = []
    all_passed = True

    for raw in raw_checks:
        descriptor = _normalize_check(raw)
        label = descriptor.get("label") or descriptor.get("name") or descriptor.get("type", "unnamed")
        sub_checks = _evaluate_descriptor(descriptor, project_dir, app_name, state)
        group_passed = all(r["passed"] or r.get("skipped", False) for r in sub_checks)
        if not group_passed:
            all_passed = False
        all_results.append({"check": label, "passed": group_passed, "sub_checks": sub_checks})

    return {"gate": gate_id, "passed": all_passed, "soft": soft, "checks": all_results}
```

  **After:**
```python
    all_results: list[dict] = []
    any_hard_fail = False
    any_degraded = False

    for raw in raw_checks:
        descriptor = _normalize_check(raw)
        label = descriptor.get("label") or descriptor.get("name") or descriptor.get("type", "unnamed")
        sub_checks = _evaluate_descriptor(descriptor, project_dir, app_name, state)

        # Three-valued group rollup:
        #   hard_fail = a sub-check ran and truly failed (not a skip)
        #   degraded  = a sub-check skipped *because* a degradable resource was
        #               missing (skipped AND degraded). A benign skip (skipped
        #               only, no degraded flag) still counts as green so
        #               backend_required N/A skips never lower the gate.
        group_hard_fail = any(
            (not r["passed"]) and (not r.get("skipped", False))
            for r in sub_checks
        )
        group_degraded = any(
            r.get("skipped", False) and r.get("degraded", False)
            for r in sub_checks
        )
        group_passed = not group_hard_fail and not group_degraded

        if group_hard_fail:
            any_hard_fail = True
        if group_degraded and not group_hard_fail:
            any_degraded = True

        all_results.append({
            "check": label,
            "passed": group_passed,
            "degraded": (group_degraded and not group_hard_fail),
            "sub_checks": sub_checks,
        })

    passed = not any_hard_fail
    degraded = passed and any_degraded
    return {
        "gate": gate_id,
        "passed": passed,
        "degraded": degraded,
        "soft": soft,
        "checks": all_results,
    }
```

- [ ] Re-run — expect PASS:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestRunGateRollup
```
Expected: 6 tests OK.

- [ ] Run the full gate-related suite to confirm no regression in existing gate behavior (benign `backend_required` skips, soft gates):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p 'test_*gate*.py'
```
Expected: all existing gate tests still OK (benign skips stay green because they set `skipped` without `degraded`).

- [ ] Commit:
```
cd /Users/louis/Code/Autobot && git add scripts/gate_runner.py tests/test_degraded_verdict.py && git commit -m "feat(gate): run_gate three-valued rollup (passed/degraded/failed)"
```

---

### Task 3: `format_text` shows a DEGRADED marker

**Files**
- Test: `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` (add `TestFormatTextDegraded`)
- Impl: `/Users/louis/Code/Autobot/scripts/gate_runner.py`

**Steps**

- [ ] Add the failing test class. Replace the `# ── Task 3 ...` comment line with:

```python
class TestFormatTextDegraded(unittest.TestCase):

    def _gate(self, *, passed, degraded, soft=False, group_degraded=False):
        return {
            "gate": "5->6",
            "passed": passed,
            "degraded": degraded,
            "soft": soft,
            "checks": [{
                "check": "functional_flows_pass",
                "passed": passed and not group_degraded,
                "degraded": group_degraded,
                "sub_checks": [
                    _ok("flow", not group_degraded, "x",
                        skipped=group_degraded, degraded=group_degraded),
                ],
            }],
        }

    def test_pass_header_when_clean(self):
        txt = format_text(self._gate(passed=True, degraded=False))
        self.assertIn("Gate 5->6: PASS", txt)
        self.assertNotIn("DEGRADED", txt)

    def test_degraded_header_and_group_marker(self):
        txt = format_text(self._gate(passed=True, degraded=True, group_degraded=True))
        self.assertIn("Gate 5->6: DEGRADED", txt)
        # the degraded group renders a DEGRADED marker, not PASS/FAIL
        self.assertIn("[DEGRADED] functional_flows_pass", txt)

    def test_fail_header_unchanged(self):
        txt = format_text(self._gate(passed=False, degraded=False))
        self.assertIn("Gate 5->6: FAIL", txt)

    def test_soft_fail_still_renders(self):
        txt = format_text(self._gate(passed=False, degraded=False, soft=True))
        self.assertIn("Gate 5->6: SOFT FAIL", txt)

    def test_degraded_sub_check_icon(self):
        txt = format_text(self._gate(passed=True, degraded=True, group_degraded=True))
        # degraded skip uses the degraded icon, distinct from benign skip ⊘
        self.assertIn("⚠", txt)
```

- [ ] Run it — expect FAIL (current `format_text` has no DEGRADED header, no `[DEGRADED]` group marker, no `⚠` icon):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestFormatTextDegraded
```
Expected: `test_degraded_header_and_group_marker`, `test_degraded_sub_check_icon` FAIL on missing substrings.

- [ ] Apply the minimal impl. In `/Users/louis/Code/Autobot/scripts/gate_runner.py`, replace `format_text` (lines 322-342).

  **Before:**
```python
def format_text(result: dict) -> str:
    lines: list[str] = []
    status = "PASS" if result["passed"] else ("SOFT FAIL" if result.get("soft") else "FAIL")
    lines.append(f"Gate {result['gate']}: {status}")
    lines.append("")

    for group in result.get("checks", []):
        mark = "PASS" if group["passed"] else "FAIL"
        lines.append(f"  [{mark}] {group['check']}")
        for sub in group.get("sub_checks", []):
            if sub.get("skipped"):
                icon = "⊘"
            elif sub["passed"]:
                icon = "✓"
            else:
                icon = "✗"
            lines.append(f"    {icon} {sub['check']}: {sub['message']}")

    if "error" in result:
        lines.append(f"\n  ERROR: {result['error']}")
    return "\n".join(lines)
```

  **After:**
```python
def format_text(result: dict) -> str:
    lines: list[str] = []
    if result["passed"]:
        status = "DEGRADED" if result.get("degraded") else "PASS"
    else:
        status = "SOFT FAIL" if result.get("soft") else "FAIL"
    lines.append(f"Gate {result['gate']}: {status}")
    lines.append("")

    for group in result.get("checks", []):
        if group["passed"]:
            mark = "PASS"
        elif group.get("degraded"):
            mark = "DEGRADED"
        else:
            mark = "FAIL"
        lines.append(f"  [{mark}] {group['check']}")
        for sub in group.get("sub_checks", []):
            if sub.get("skipped") and sub.get("degraded"):
                icon = "⚠"
            elif sub.get("skipped"):
                icon = "⊘"
            elif sub["passed"]:
                icon = "✓"
            else:
                icon = "✗"
            lines.append(f"    {icon} {sub['check']}: {sub['message']}")

    if "error" in result:
        lines.append(f"\n  ERROR: {result['error']}")
    return "\n".join(lines)
```

- [ ] Re-run — expect PASS:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestFormatTextDegraded
```
Expected: 5 tests OK.

- [ ] Commit:
```
cd /Users/louis/Code/Autobot && git add scripts/gate_runner.py tests/test_degraded_verdict.py && git commit -m "feat(gate): format_text renders DEGRADED header + group marker + ⚠ icon"
```

---

### Task 4: `build_gate_evidence` mints `"degraded"` status

**Files**
- Test: `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` (add `TestBuildGateEvidenceStatus`)
- Impl: `/Users/louis/Code/Autobot/scripts/gate_persistence.py`

**Steps**

- [ ] Add the failing test class. Replace the `# ── Task 4 ...` comment line with:

```python
class TestBuildGateEvidenceStatus(unittest.TestCase):
    """All four statuses must round-trip from gate_result → evidence.status."""

    SPEC = {
        "gates": {
            "5->6": {"fromPhase": "5", "toPhase": "6"},
            "6->7": {"fromPhase": "6", "toPhase": "7"},
        }
    }

    def _evidence(self, gate_result, gate_id="5->6"):
        return build_gate_evidence(self.SPEC, gate_id, gate_result, "2026-05-29T00:00:00Z")

    def test_passed(self):
        gr = {"gate": "5->6", "passed": True, "degraded": False, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "passed")

    def test_degraded(self):
        gr = {"gate": "5->6", "passed": True, "degraded": True, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "degraded")

    def test_failed(self):
        gr = {"gate": "5->6", "passed": False, "degraded": False, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "failed")

    def test_soft_failed(self):
        gr = {"gate": "6->7", "passed": False, "degraded": False, "soft": True, "checks": []}
        self.assertEqual(self._evidence(gr, gate_id="6->7")["status"], "soft_failed")

    def test_degraded_only_applies_when_passed(self):
        # a failed gate that somehow also flagged degraded is still failed (hard wins).
        gr = {"gate": "5->6", "passed": False, "degraded": True, "soft": False, "checks": []}
        self.assertEqual(self._evidence(gr)["status"], "failed")

    def test_soft_passed_with_degraded_is_degraded(self):
        # soft gate that passed-with-degradation records degraded, not passed.
        gr = {"gate": "6->7", "passed": True, "degraded": True, "soft": True, "checks": []}
        self.assertEqual(self._evidence(gr, gate_id="6->7")["status"], "degraded")
```

- [ ] Run it — expect FAIL (current minting has no `"degraded"` branch; `test_degraded` and `test_soft_passed_with_degraded_is_degraded` return `"passed"`):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestBuildGateEvidenceStatus
```
Expected: 2 FAIL with `'passed' != 'degraded'`.

- [ ] Apply the minimal impl. In `/Users/louis/Code/Autobot/scripts/gate_persistence.py`, replace lines 41-43.

  **Before:**
```python
    passed = gate_result.get("passed", False)
    soft = gate_result.get("soft", False)
    status = "passed" if passed else ("soft_failed" if soft else "failed")
```

  **After:**
```python
    passed = gate_result.get("passed", False)
    soft = gate_result.get("soft", False)
    status = (
        "failed" if (not passed and not soft)
        else "soft_failed" if (not passed)
        else "degraded" if gate_result.get("degraded")
        else "passed"
    )
```

  Note: this is exactly the LOCKED CONTRACT precedence — `failed` (hard) > `soft_failed` (soft, not passed) > `degraded` (passed but degraded) > `passed`. `test_degraded_only_applies_when_passed` proves a hard-failed gate stays `failed` even if `degraded` is set; `test_soft_passed_with_degraded_is_degraded` proves a passed soft gate with degradation records `degraded`.

- [ ] Re-run — expect PASS:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestBuildGateEvidenceStatus
```
Expected: 6 tests OK.

- [ ] Commit:
```
cd /Users/louis/Code/Autobot && git add scripts/gate_persistence.py tests/test_degraded_verdict.py && git commit -m "feat(gate): build_gate_evidence mints degraded status (four-valued)"
```

---

### Task 5: e2e — a DEGRADED gate keeps `passed=True` so the phase advances, and evidence status is `"degraded"`

This is the integration proof that ties the three-valued verdict to phase advancement and to durable state (confirming `phase_advance.py` and `state_store.collect_schema_issues` need NO change). It drives the real `pipeline.sh advance-phase` against an isolated project, monkeypatching a degradable check into gate `5->6` via a temporary `GATE_CHECKS` entry installed through an env hook is NOT available — instead we register the hook by writing a tiny sitecustomize-style shim. To keep it deterministic and dependency-free, this test drives `run_gate` + `build_gate_evidence` + the phase mutator **in-process** against a real `build-state.json`, exactly the same call path `_advance_phase_core` uses (gate result → `build_gate_evidence` → `mutate_state_with_validation`).

**Files**
- Test: `/Users/louis/Code/Autobot/tests/test_degraded_verdict.py` (add `TestDegradedAdvancesPhase`)
- Impl: none (proves no impl change needed in `phase_advance.py` / `state_store.py`)

**Steps**

- [ ] Add the e2e test class. Replace the `# ── Task 5 ...` comment line with:

```python
class TestDegradedAdvancesPhase(IsolatedProjectCase):
    """A degraded gate (passed=True, degraded=True) must:
      1. let success_path stay True so the phase advances, and
      2. write a "degraded" gate status that collect_schema_issues accepts."""

    def test_degraded_gate_evidence_writes_and_validates(self):
        from gate_persistence import build_gate_evidence
        from spec_loader import load_spec
        from state_store import mutate_state_with_validation

        spec = load_spec()
        state_path = self.project_dir / ".autobot" / "build-state.json"

        degraded_result = {
            "gate": "5->6",
            "passed": True,
            "degraded": True,
            "soft": False,
            "checks": [{
                "check": "functional_flows_pass",
                "passed": False,
                "degraded": True,
                "sub_checks": [
                    {"check": "flow", "passed": False, "message": "no simulator",
                     "skipped": True, "degraded": True},
                ],
            }],
        }

        # success_path mirrors phase_advance.py:158-160 — degraded keeps passed=True.
        gate_passed = degraded_result.get("passed", False)
        gate_soft = degraded_result.get("soft", False)
        success_path = gate_passed or gate_soft
        self.assertTrue(success_path, "degraded gate must keep success_path True")

        evidence = build_gate_evidence(spec, "5->6", degraded_result, "2026-05-29T00:00:00Z")
        self.assertEqual(evidence["status"], "degraded")

        # Writing the degraded evidence through the validating mutator must NOT
        # raise — gate status is not enum-validated by collect_schema_issues.
        def mutate(next_state):
            next_state.setdefault("gates", {})["5->6"] = evidence

        mutate_state_with_validation(state_path, spec, mutate)
        self.assertEqual(self.state()["gates"]["5->6"]["status"], "degraded")
```

- [ ] Run it — expect PASS immediately (no impl change; this is the regression lock proving the contract holds end-to-end):
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py -k TestDegradedAdvancesPhase
```
Expected: 1 test OK. (If it instead FAILS with `FATAL: refusing to write invalid build state`, that means a schema change snuck in elsewhere — STOP and re-read `collect_schema_issues`; per the verified state above it validates only phase status, so this must pass as written.)

- [ ] Run the full new module + the full suite to confirm nothing regressed:
```
python3 -m unittest discover -s /Users/louis/Code/Autobot/tests -v -p test_degraded_verdict.py
bash /Users/louis/Code/Autobot/tests/run_tests.sh
```
Expected: `test_degraded_verdict.py` — all classes OK (4 + 6 + 5 + 6 + 1 = 22 tests). Full suite — all prior tests still OK.

- [ ] Commit:
```
cd /Users/louis/Code/Autobot && git add tests/test_degraded_verdict.py && git commit -m "test(gate): e2e lock — degraded gate advances phase + writes degraded status"
```

---

### Wiring note for the functional.py work-stream (not implemented here)
The degradable behavioral checks that produce DEGRADED verdicts (`check_logic_tests_pass`, `check_functional_flows_pass`) must return `_ok(label, False, "<reason>", skipped=True, degraded=True)` when a degradable resource is missing (no simulator / no axe / no xcodebuild), and `_ok(label, False, "<reason>")` (hard fail) when they ran and truly failed. This work-stream guarantees the engine interprets those two shapes correctly: the first lowers the gate to DEGRADED (keeps `passed=True`), the second is a red fail. A genuinely-N/A skip stays `_ok(label, True, "<reason>", skipped=True)` (benign, green).

---

## WS1 — feature-spec schema + validators + architect producer

## Work-stream: feature-spec schema + validators + architect producer

Grounding facts verified against the live repo:
- `scripts/intent_spec.py` already imports `from dataclasses import dataclass, field` and `import json, re` + `from pathlib import Path`. The new code appends to this file; **no new imports needed**.
- Tests use **stdlib `unittest`** (NOT pytest assertions), imported via `from conftest import import_runtime_modules; import_runtime_modules()`, then `from intent_spec import ...`. Run with `python3 -m unittest discover -s tests -v` (see `tests/run_tests.sh`). Each test subclasses `unittest.TestCase`.
- `tests/test_intent_spec.py` writes artifacts with a `_write_intent(project_root, payload)` helper that does `(project_root / ".autobot").mkdir(parents=True, exist_ok=True)` then `(... / "app-intent.json").write_text(json.dumps(payload), encoding="utf-8")`. We mirror this for feature-spec.
- **CRITICAL**: `spec/pipeline.json` has NO `architectureSchema` key (verified by parsing the JSON — top keys are `schemaVersion, statuses, terminalStatuses, stateSchema, transitions, policies, logEvents, fileOwnership, phases, gates`). So `agents/architect.md` line ~93 `스키마는 spec/pipeline.json.architectureSchema 가 SSOT.` points at a dead key. The real schema is documented inline in architect.md section (d) itself. Fix = repoint the SSOT sentence to the inline block / `agents/architect.md` section (d).
- `scripts/verify_spec_docs.py:check_prose_contract_drift` does NOT scan for `architectureSchema`, so changing that prose line is safe and won't trip the drift test.

The LOCKED CONTRACT for this stream:
```
POSTCONDITION_KINDS = ("count_increased","count_decreased","value_persisted_after_relaunch","navigated_to","artifact_generated","setting_stored")
@dataclass Postcondition: kind: str; params: dict (default {})
Step is a plain dict {"action": str, "anchor": str}   (cycle1 action == "tap")
@dataclass Acceptance: id: str; kind: str ("flow"|"logic"); steps: tuple[dict,...]; postcondition: Postcondition
@dataclass FeatureSpec: id: str; title: str; priority: str ("P0"|"P1"|"P2"); screen: str; anchor: str; acceptance: tuple[Acceptance,...]
load_feature_spec(project_root: Path) -> list[FeatureSpec] | None
validate_feature_spec(project_root: Path) -> tuple[bool, list[str]]
assess_feature_spec_quality(project_root: Path) -> tuple[bool, list[str]]
```
Artifact path: `.autobot/feature-spec.json`.

---

### Task 1: feature-spec dataclasses + loader + validators in scripts/intent_spec.py

**Files**
- `scripts/intent_spec.py` (append new section — do NOT touch existing AppIntent / load_app_intent / validate_manifest / find_unused_anchors code)
- `tests/test_intent_spec.py` (append new test classes + a `_write_feature_spec` helper)

**TDD step 1 — write the failing tests FIRST.** Append the following to the END of `tests/test_intent_spec.py`, and add the new names to the existing top-of-file import block.

First, extend the existing import in `tests/test_intent_spec.py`. The current block is:
```python
from intent_spec import (  # noqa: E402
    AppIntent,
    DEFAULT_REQUIRED_ANCHORS,
    find_unused_anchors,
    load_app_intent,
    validate_manifest,
)
```
Replace it with:
```python
from intent_spec import (  # noqa: E402
    Acceptance,
    AppIntent,
    DEFAULT_REQUIRED_ANCHORS,
    FeatureSpec,
    POSTCONDITION_KINDS,
    Postcondition,
    assess_feature_spec_quality,
    find_unused_anchors,
    load_app_intent,
    load_feature_spec,
    validate_feature_spec,
    validate_manifest,
)
```

Then append these test classes to the END of `tests/test_intent_spec.py`, **before** the final `if __name__ == "__main__":` block. (Move the existing `if __name__ == "__main__": unittest.main()` to remain the last thing in the file — i.e. paste the new classes above it.)

```python
def _write_feature_spec(project_root: Path, payload: dict) -> None:
    (project_root / ".autobot").mkdir(parents=True, exist_ok=True)
    (project_root / ".autobot" / "feature-spec.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _valid_feature_payload() -> dict:
    """A structurally + quality-valid spec: one P0 flow feature with a real
    postcondition, plus a P2 feature we don't strictly police."""
    return {
        "version": 1,
        "features": [
            {
                "id": "log-workout",
                "title": "Log a workout",
                "priority": "P0",
                "screen": "Today",
                "anchor": "autobot.primaryCTA",
                "acceptance": [
                    {
                        "id": "tap-log-increments-count",
                        "kind": "flow",
                        "steps": [{"action": "tap", "anchor": "autobot.primaryCTA"}],
                        "postcondition": {
                            "kind": "count_increased",
                            "params": {"anchor": "autobot.workoutCount"},
                        },
                    }
                ],
            },
            {
                "id": "about-screen",
                "title": "About",
                "priority": "P2",
                "screen": "Settings",
                "anchor": "autobot.aboutRow",
                "acceptance": [],
            },
        ],
    }


class TestLoadFeatureSpec(unittest.TestCase):
    def test_returns_none_when_file_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_feature_spec(Path(tmp)))

    def test_returns_none_when_unparseable(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autobot").mkdir()
            (Path(tmp) / ".autobot" / "feature-spec.json").write_text("not json")
            self.assertIsNone(load_feature_spec(Path(tmp)))

    def test_valid_spec_parses_into_dataclasses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            features = load_feature_spec(tmp_path)
            assert features is not None
            self.assertEqual(len(features), 2)
            first = features[0]
            self.assertIsInstance(first, FeatureSpec)
            self.assertEqual(first.id, "log-workout")
            self.assertEqual(first.priority, "P0")
            self.assertEqual(first.screen, "Today")
            self.assertEqual(first.anchor, "autobot.primaryCTA")
            self.assertEqual(len(first.acceptance), 1)
            acc = first.acceptance[0]
            self.assertIsInstance(acc, Acceptance)
            self.assertEqual(acc.kind, "flow")
            self.assertEqual(acc.steps, ({"action": "tap", "anchor": "autobot.primaryCTA"},))
            self.assertIsInstance(acc.postcondition, Postcondition)
            self.assertEqual(acc.postcondition.kind, "count_increased")
            self.assertEqual(acc.postcondition.params, {"anchor": "autobot.workoutCount"})

    def test_tolerates_missing_and_extra_fields(self):
        # A feature missing optional bits + carrying junk keys must still parse,
        # with safe defaults (empty acceptance tuple, empty params dict).
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, {
                "features": [
                    {
                        "id": "f1",
                        "title": "F1",
                        "priority": "P1",
                        "screen": "Home",
                        "anchor": "autobot.root",
                        "junkKey": 123,
                        "acceptance": [
                            {
                                "id": "a1",
                                "kind": "logic",
                                # no "steps", no "params", extra noise field
                                "postcondition": {"kind": "setting_stored", "noise": True},
                                "alsoJunk": "x",
                            }
                        ],
                    }
                ]
            })
            features = load_feature_spec(tmp_path)
            assert features is not None
            self.assertEqual(features[0].acceptance[0].steps, ())
            self.assertEqual(features[0].acceptance[0].postcondition.params, {})
            self.assertEqual(features[0].acceptance[0].postcondition.kind, "setting_stored")

    def test_non_dict_root_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".autobot").mkdir()
            (Path(tmp) / ".autobot" / "feature-spec.json").write_text("[1, 2, 3]")
            self.assertIsNone(load_feature_spec(Path(tmp)))


class TestValidateFeatureSpec(unittest.TestCase):
    def test_valid_spec_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = validate_feature_spec(tmp_path)
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])

    def test_absent_file_fails_with_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, problems = validate_feature_spec(Path(tmp))
            self.assertFalse(ok)
            self.assertTrue(any("feature-spec.json" in p for p in problems))

    def test_p0_with_no_acceptance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"] = []  # P0 with zero acceptance
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p and "acceptance" in p for p in problems))

    def test_p1_with_empty_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["priority"] = "P1"
            payload["features"][0]["anchor"] = ""  # empty anchor on a P1 feature
            _write_feature_spec(tmp_path, payload)
            ok, problems = validate_feature_spec(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p and "anchor" in p for p in problems))

    def test_p2_feature_with_no_acceptance_is_allowed(self):
        # Only P0/P1 are policed structurally; the P2 in the payload has [].
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = validate_feature_spec(tmp_path)
            self.assertTrue(ok, problems)


class TestAssessFeatureSpecQuality(unittest.TestCase):
    def test_valid_postcondition_kind_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_feature_spec(tmp_path, _valid_feature_payload())
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])

    def test_anchor_only_acceptance_rejected(self):
        # Acceptance with no real postcondition (empty kind) = "anchor-only",
        # which assess_feature_spec_quality must reject for P0/P1.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"][0]["postcondition"] = {"kind": ""}
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("log-workout" in p for p in problems))

    def test_bad_postcondition_kind_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _valid_feature_payload()
            payload["features"][0]["acceptance"][0]["postcondition"]["kind"] = "made_up_kind"
            _write_feature_spec(tmp_path, payload)
            ok, problems = assess_feature_spec_quality(tmp_path)
            self.assertFalse(ok)
            self.assertTrue(any("made_up_kind" in p for p in problems))

    def test_absent_file_fails_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, problems = assess_feature_spec_quality(Path(tmp))
            self.assertFalse(ok)
            self.assertTrue(any("feature-spec.json" in p for p in problems))

    def test_all_kinds_recognized(self):
        # Sanity: each declared kind is accepted on a P0 acceptance.
        for kind in POSTCONDITION_KINDS:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                payload = _valid_feature_payload()
                payload["features"][0]["acceptance"][0]["postcondition"]["kind"] = kind
                _write_feature_spec(tmp_path, payload)
                ok, problems = assess_feature_spec_quality(tmp_path)
                self.assertTrue(ok, f"{kind}: {problems}")
```

**Run the tests — expected FAIL (ImportError, names don't exist yet):**
```bash
python3 -m unittest tests.test_intent_spec -v
```
Expected output contains:
```
ImportError: cannot import name 'Acceptance' from 'intent_spec'
```
(The whole module fails to import, so every test in the file errors. That is the expected red.)

**TDD step 2 — minimal implementation.** Append the following block to the END of `scripts/intent_spec.py`, immediately AFTER the `find_unused_anchors(...)` function and BEFORE the `def _main() -> int:` function. (Insert it between line 136's closing `return missing, present` block and line 139's `def _main`.) Use Edit to place it right before `def _main() -> int:`.

```python
# ---------------------------------------------------------------------------
# Feature spec — the per-feature behavioral contract (.autobot/feature-spec.json)
#
# Where app-intent.json captures ONE primary anchor/CTA, feature-spec.json
# decomposes the architect's promise into testable features. Each feature owns
# acceptance criteria whose postconditions are checkable at runtime (Phase 5
# flow_runner) rather than merely "the anchor rendered". This is the SSOT for
# functional verification; gate 1->2 validates it and gate 5->6 executes it.
# ---------------------------------------------------------------------------

POSTCONDITION_KINDS = (
    "count_increased",
    "count_decreased",
    "value_persisted_after_relaunch",
    "navigated_to",
    "artifact_generated",
    "setting_stored",
)

_POLICED_PRIORITIES = ("P0", "P1")


@dataclass
class Postcondition:
    kind: str
    params: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "Postcondition":
        if not isinstance(data, dict):
            return cls(kind="", params={})
        params = data.get("params")
        if not isinstance(params, dict):
            params = {}
        return cls(kind=str(data.get("kind") or ""), params=params)


@dataclass
class Acceptance:
    id: str
    kind: str
    steps: tuple[dict, ...]
    postcondition: Postcondition

    @classmethod
    def from_dict(cls, data: dict) -> "Acceptance":
        if not isinstance(data, dict):
            data = {}
        raw_steps = data.get("steps") or ()
        if not isinstance(raw_steps, (list, tuple)):
            raw_steps = ()
        steps = tuple(s for s in raw_steps if isinstance(s, dict))
        return cls(
            id=str(data.get("id") or ""),
            kind=str(data.get("kind") or ""),
            steps=steps,
            postcondition=Postcondition.from_dict(data.get("postcondition") or {}),
        )


@dataclass
class FeatureSpec:
    id: str
    title: str
    priority: str
    screen: str
    anchor: str
    acceptance: tuple[Acceptance, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "FeatureSpec":
        if not isinstance(data, dict):
            data = {}
        raw_acc = data.get("acceptance") or ()
        if not isinstance(raw_acc, (list, tuple)):
            raw_acc = ()
        acceptance = tuple(
            Acceptance.from_dict(a) for a in raw_acc if isinstance(a, dict)
        )
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            priority=str(data.get("priority") or ""),
            screen=str(data.get("screen") or ""),
            anchor=str(data.get("anchor") or ""),
            acceptance=acceptance,
        )


def load_feature_spec(project_root: Path) -> list[FeatureSpec] | None:
    """Return the parsed feature list, or None if the manifest is absent /
    unparseable / not a JSON object. Parsing tolerates missing & extra fields."""
    path = project_root / ".autobot" / "feature-spec.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    raw_features = data.get("features")
    if not isinstance(raw_features, list):
        return None
    return [FeatureSpec.from_dict(f) for f in raw_features if isinstance(f, dict)]


def validate_feature_spec(project_root: Path) -> tuple[bool, list[str]]:
    """Structural validation for Gate 1->2 — returns (ok, problems).

    Every P0/P1 feature must declare >=1 acceptance criterion AND a non-empty
    anchor. P2 features are not policed (they may be aspirational stubs).
    """
    features = load_feature_spec(project_root)
    if features is None:
        return False, ["feature-spec.json absent or unparseable"]

    problems: list[str] = []
    for feat in features:
        if feat.priority not in _POLICED_PRIORITIES:
            continue
        label = feat.id or "<unnamed feature>"
        if not feat.acceptance:
            problems.append(f"{label} ({feat.priority}): no acceptance criteria")
        if not feat.anchor:
            problems.append(f"{label} ({feat.priority}): empty anchor")
    return (not problems), problems


def assess_feature_spec_quality(project_root: Path) -> tuple[bool, list[str]]:
    """Quality assessment for Gate 1->2 — returns (ok, problems).

    Every P0/P1 acceptance postcondition.kind must be one of
    POSTCONDITION_KINDS. An empty kind ("anchor-only" acceptance — it only
    asserts the anchor rendered, never that behavior occurred) is invalid: a
    postcondition is what makes the flow checkable at runtime.
    """
    features = load_feature_spec(project_root)
    if features is None:
        return False, ["feature-spec.json absent or unparseable"]

    problems: list[str] = []
    for feat in features:
        if feat.priority not in _POLICED_PRIORITIES:
            continue
        label = feat.id or "<unnamed feature>"
        for acc in feat.acceptance:
            kind = acc.postcondition.kind
            if not kind:
                problems.append(
                    f"{label}/{acc.id or '<unnamed>'}: anchor-only acceptance "
                    f"(no postcondition.kind) is not runtime-checkable"
                )
            elif kind not in POSTCONDITION_KINDS:
                problems.append(
                    f"{label}/{acc.id or '<unnamed>'}: invalid postcondition.kind "
                    f"'{kind}' (allowed: {', '.join(POSTCONDITION_KINDS)})"
                )
    return (not problems), problems
```

**Run the tests — expected PASS:**
```bash
python3 -m unittest tests.test_intent_spec -v
```
Expected: all tests in `TestLoadFeatureSpec`, `TestValidateFeatureSpec`, `TestAssessFeatureSpecQuality` (plus the pre-existing `TestLoadAppIntent`, `TestValidateManifest`, `TestFindUnusedAnchors`) report `ok`. Final line:
```
OK
```

**Run the full suite to confirm no regression:**
```bash
bash tests/run_tests.sh
```
Expected: final line `OK` (no failures, no errors).

**Commit:**
```bash
git checkout -b feature-spec-schema
git add scripts/intent_spec.py tests/test_intent_spec.py
git commit -m "feat(intent_spec): feature-spec schema + load/validate/quality validators"
```

---

### Task 2: architect emits .autobot/feature-spec.json + fix stale architectureSchema reference (prose)

**Files**
- `agents/architect.md` (prose edits only — two changes)

This is a prose/documentation task. No tests are written for prose, but I verified the two factual claims it fixes:
1. `grep`/JSON-parse of `spec/pipeline.json` confirms there is **no** `architectureSchema` key — the line `스키마는 spec/pipeline.json.architectureSchema 가 SSOT.` at architect.md line ~93 is a dead reference. The schema is actually documented inline in architect.md section (d) and consumed by Phase 3 scaffold + Gate 4→5.
2. `scripts/verify_spec_docs.py:check_prose_contract_drift` does NOT scan for `architectureSchema`, so editing this line does not break `tests/test_verify_spec_docs_contracts.py::test_current_docs_have_no_prose_contract_drift`.

**TDD step 1 — confirm the current state (expected: stale ref present, drift test green):**
```bash
grep -n "architectureSchema" agents/architect.md
bash tests/run_tests.sh 2>&1 | tail -3
```
Expected: grep prints `93:스키마는 spec/pipeline.json.architectureSchema 가 SSOT.`; suite ends `OK`.

**Edit 2a — fix the stale architectureSchema SSOT reference.** In `agents/architect.md`, replace the exact line:
```
스키마는 `spec/pipeline.json.architectureSchema` 가 SSOT.
```
with:
```
이 JSON 의 스키마 SSOT 는 위 (d) 블록 자체다 (`spec/pipeline.json` 에는 `architectureSchema` 키가 없다 — 옛 참조였음). Phase 3 scaffold 와 Gate 4→5 sandbox 가 이 필드들을 읽는다.
```

**Edit 2b — add the feature-spec.json emission contract.** The architect currently emits 5 artifacts (a–e). We add a SIXTH, `(f) feature-spec.json`. Insert the following markdown block in `agents/architect.md` immediately AFTER the end of section `### (e) app-intent.json — UI 의도 계약` (i.e. after the `happyPath` rules list that ends with `- happyPath 는 정보용 (Phase 5 UI test 가 참고).`) and BEFORE the `## Integration Map` heading.

Also update the artifact enumeration in the opening sentence. Replace the opening-paragraph fragment:
```
**(e) `.autobot/app-intent.json`** — and nothing else.
```
with:
```
**(e) `.autobot/app-intent.json`**, **(f) `.autobot/feature-spec.json`** — and nothing else.
```

Insert this new section:
```markdown
### (f) feature-spec.json — 기능별 행위 계약 (Phase 5 functional verification 의 SSOT)

`app-intent.json` 이 **단일** primary anchor/CTA 만 잡는다면, `feature-spec.json` 은 architecture.md 의 `## Features` (P0–P2) 를 **런타임에서 검증 가능한** 기능 단위로 분해한다. Gate 1→2 가 구조/품질을 검증하고, Gate 5→6 의 `functional_flows_pass` 가 AXe 로 실제 실행한다.

```json
{
  "version": 1,
  "features": [
    {
      "id": "log-workout",
      "title": "Log a workout",
      "priority": "P0",
      "screen": "Today",
      "anchor": "autobot.primaryCTA",
      "acceptance": [
        {
          "id": "tap-log-increments-count",
          "kind": "flow",
          "steps": [{"action": "tap", "anchor": "autobot.primaryCTA"}],
          "postcondition": {
            "kind": "count_increased",
            "params": {"anchor": "autobot.workoutCount"}
          }
        }
      ]
    }
  ]
}
```

**보수적 유도 규칙 (CONSERVATIVE — 표현 불가능하면 다운그레이드, 절대 날조 금지):**

1. **screen 접지**: 모든 `feature.screen` 값은 architecture.md `## Screens` 에 실재하는 화면 이름을 그대로 가리킨다. 매칭되는 screen 이 없으면 그 feature 를 만들지 않는다.
2. **anchor 접지**: 모든 P0/P1 `feature.anchor` 와 acceptance step 의 `anchor` 는 `app-intent.json.requiredAnchors` 에 있거나, ui-builder 가 그 화면에 반드시 부여할 수 있는 `autobot.*` 식별자여야 한다. anchor 를 비워두면 Gate 1→2 (`feature_spec_quality`) 에서 fail.
3. **postcondition 접지**: 모든 P0/P1 acceptance 의 `postcondition.kind` 는 다음 6 개 중 하나여야 하고, `## Data Models` 의 emitted Model 또는 emitted screen 에서 **실제로 관찰 가능한** 결과를 가리켜야 한다 — `count_increased`, `count_decreased`, `value_persisted_after_relaunch`, `navigated_to`, `artifact_generated`, `setting_stored`. 예: `count_increased` 는 화면에 카운트 라벨 anchor 가 존재할 때만, `value_persisted_after_relaunch` 는 SwiftData `@Model` 로 영속되는 값일 때만 쓴다. anchor 가 렌더됐다는 것만으로는 postcondition 이 될 수 없다 (anchor-only acceptance 는 invalid).
4. **acceptance.kind**: UI 탭/내비게이션으로 검증되면 `"flow"`, 모델/로직 단위로 검증되면 `"logic"`. cycle 1 에서 step `action` 은 항상 `"tap"`.
5. **표현 불가능 → P2 다운그레이드**: 위 1–3 을 만족하는 grounded postcondition 을 만들 수 없는 기능은 `priority` 를 `"P2"` 로 낮춘다. P2 는 acceptance 가 비어 있어도 Gate 1→2 가 통과시킨다 (aspirational stub 허용). P0/P1 으로 남기려면 반드시 grounded acceptance 1 개 이상.
6. **최소 보장**: P0 기능은 최소 1 개의 `"flow"` acceptance 를 가진다 — 빌드의 핵심 약속은 런타임에서 실제로 클릭되어 검증돼야 한다.

스키마 SSOT 는 위 JSON 블록 + `scripts/intent_spec.py` 의 `FeatureSpec`/`Acceptance`/`Postcondition` 데이터클래스다. 검증기: `validate_feature_spec` (구조), `assess_feature_spec_quality` (postcondition 품질).
```

**Run the suite to confirm no drift regression — expected PASS:**
```bash
bash tests/run_tests.sh 2>&1 | tail -3
grep -c "architectureSchema 가 SSOT" agents/architect.md
```
Expected: suite ends `OK`; the second grep prints `0` (the dead `... 가 SSOT.` reference is gone — the only remaining `architectureSchema` token is inside the explanatory sentence noting the key does not exist).

**Commit:**
```bash
git add agents/architect.md
git commit -m "docs(architect): emit feature-spec.json (conservative derivation) + fix dead architectureSchema ref"
```

---

## WS5 — Gate 1→2 checks, per-feature anchors, spec wiring, agent prompts

> **Suite reality check (read first).** The repo's tests are **stdlib `unittest`**, discovered via `tests/run_tests.sh` (`python3 -m unittest discover -s tests -v`). There is no pytest dependency installed. All tasks below are written as `unittest.TestCase` subclasses to match the actual suite (`tests/test_intent_spec.py`, `tests/test_primary_cta_visibility.py`). The orchestrator-mandated "pytest" can run them too (`python3 -m pytest tests/<file>.py` discovers `unittest.TestCase` fine), but the canonical run is `unittest`.
>
> **Cross-work-stream dependency.** My Gate 1→2 checks call `intent_spec.validate_feature_spec(project_root)` and `intent_spec.assess_feature_spec_quality(project_root)`, and the generalized `intent_anchors_in_ui` calls `intent_spec.load_feature_spec(project_root)`. These three functions + the `FeatureSpec`/`Acceptance`/`Postcondition` dataclasses are **owned by the intent_spec work-stream** (LOCKED CONTRACT). They are NOT present yet (`grep` confirms 0 matches in `scripts/intent_spec.py`). **Task 0 below adds a thin, contract-exact fallback shim ONLY IF that work-stream has not landed them** — it is written so that if the real implementation lands first, the shim is a no-op import and my code calls the real functions verbatim. Each task states its precondition explicitly.

---

### Task 0: Guarantee the intent_spec FeatureSpec API exists (idempotent guard, contract-exact)

**Files:** `scripts/intent_spec.py` (append only, no edits to existing code)

This task makes my work-stream runnable independently. If the intent_spec work-stream already landed `FeatureSpec` / `load_feature_spec` / `validate_feature_spec` / `assess_feature_spec_quality`, **SKIP this task entirely** (re-running `grep -n 'def validate_feature_spec' scripts/intent_spec.py` returns a hit → skip). Otherwise add the canonical implementation verbatim from the LOCKED CONTRACT so downstream checks have something to call. The names/signatures here are byte-identical to the contract, so a later merge with the real implementation is a content match, not a conflicting variant.

- [ ] **0.1 — Check if the API already exists.**
  ```bash
  grep -n 'def validate_feature_spec\|def assess_feature_spec_quality\|def load_feature_spec\|POSTCONDITION_KINDS' scripts/intent_spec.py || echo "ABSENT — proceed with 0.2"
  ```
  Expected (current repo): prints `ABSENT — proceed with 0.2`. If it prints line numbers, **STOP — skip Task 0**.

- [ ] **0.2 — Write the failing test first** at `tests/test_feature_spec.py`:
  ```python
  """Tests for scripts/intent_spec.py FeatureSpec layer — the per-feature spine
  that Gate 1->2 (feature_spec_declared / feature_spec_quality) and the
  generalized Gate 4->5 intent_anchors_in_ui rely on.
  """
  from __future__ import annotations

  import json
  import tempfile
  import unittest
  from pathlib import Path

  from conftest import import_runtime_modules

  import_runtime_modules()

  from intent_spec import (  # noqa: E402
      POSTCONDITION_KINDS,
      assess_feature_spec_quality,
      load_feature_spec,
      validate_feature_spec,
  )


  def _write_feature_spec(root: Path, payload: dict) -> None:
      (root / ".autobot").mkdir(parents=True, exist_ok=True)
      (root / ".autobot" / "feature-spec.json").write_text(
          json.dumps(payload), encoding="utf-8"
      )


  def _good_feature(fid="f1", priority="P0", anchor="autobot.f1.cta",
                    postcondition_kind="count_increased") -> dict:
      return {
          "id": fid,
          "title": f"Feature {fid}",
          "priority": priority,
          "screen": "Home",
          "anchor": anchor,
          "acceptance": [
              {
                  "id": f"{fid}.a1",
                  "kind": "flow",
                  "steps": [{"action": "tap", "anchor": anchor}],
                  "postcondition": {"kind": postcondition_kind, "params": {}},
              }
          ],
      }


  class TestLoadFeatureSpec(unittest.TestCase):
      def test_returns_none_when_absent(self):
          with tempfile.TemporaryDirectory() as tmp:
              self.assertIsNone(load_feature_spec(Path(tmp)))

      def test_returns_none_when_unparseable(self):
          with tempfile.TemporaryDirectory() as tmp:
              (Path(tmp) / ".autobot").mkdir()
              (Path(tmp) / ".autobot" / "feature-spec.json").write_text("not json")
              self.assertIsNone(load_feature_spec(Path(tmp)))

      def test_loads_features(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write_feature_spec(Path(tmp), {"features": [_good_feature()]})
              feats = load_feature_spec(Path(tmp))
              self.assertIsNotNone(feats)
              self.assertEqual(len(feats), 1)
              self.assertEqual(feats[0].id, "f1")
              self.assertEqual(feats[0].priority, "P0")
              self.assertEqual(feats[0].anchor, "autobot.f1.cta")
              self.assertEqual(len(feats[0].acceptance), 1)
              self.assertEqual(feats[0].acceptance[0].postcondition.kind, "count_increased")


  class TestValidateFeatureSpec(unittest.TestCase):
      def test_valid_p0_passes(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write_feature_spec(Path(tmp), {"features": [_good_feature()]})
              ok, problems = validate_feature_spec(Path(tmp))
              self.assertTrue(ok, problems)
              self.assertEqual(problems, [])

      def test_p0_without_acceptance_fails(self):
          with tempfile.TemporaryDirectory() as tmp:
              feat = _good_feature()
              feat["acceptance"] = []
              _write_feature_spec(Path(tmp), {"features": [feat]})
              ok, problems = validate_feature_spec(Path(tmp))
              self.assertFalse(ok)
              self.assertTrue(any("acceptance" in p for p in problems))

      def test_p0_with_empty_anchor_fails(self):
          with tempfile.TemporaryDirectory() as tmp:
              feat = _good_feature(anchor="")
              _write_feature_spec(Path(tmp), {"features": [feat]})
              ok, problems = validate_feature_spec(Path(tmp))
              self.assertFalse(ok)
              self.assertTrue(any("anchor" in p for p in problems))

      def test_p2_without_acceptance_is_tolerated(self):
          with tempfile.TemporaryDirectory() as tmp:
              feat = _good_feature(fid="f2", priority="P2")
              feat["acceptance"] = []
              _write_feature_spec(Path(tmp), {"features": [feat]})
              ok, problems = validate_feature_spec(Path(tmp))
              self.assertTrue(ok, problems)

      def test_absent_file_fails(self):
          with tempfile.TemporaryDirectory() as tmp:
              ok, problems = validate_feature_spec(Path(tmp))
              self.assertFalse(ok)
              self.assertTrue(any("feature-spec.json" in p for p in problems))


  class TestAssessFeatureSpecQuality(unittest.TestCase):
      def test_recognized_postcondition_passes(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write_feature_spec(Path(tmp), {"features": [_good_feature()]})
              ok, problems = assess_feature_spec_quality(Path(tmp))
              self.assertTrue(ok, problems)

      def test_anchor_only_postcondition_fails(self):
          # postcondition.kind not in POSTCONDITION_KINDS -> anchor-only / placeholder
          with tempfile.TemporaryDirectory() as tmp:
              feat = _good_feature(postcondition_kind="anchor_present")
              _write_feature_spec(Path(tmp), {"features": [feat]})
              ok, problems = assess_feature_spec_quality(Path(tmp))
              self.assertFalse(ok)
              self.assertTrue(any("postcondition" in p for p in problems))

      def test_postcondition_kinds_constant(self):
          self.assertIn("count_increased", POSTCONDITION_KINDS)
          self.assertIn("value_persisted_after_relaunch", POSTCONDITION_KINDS)


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **0.3 — Run the test, expect FAIL (ImportError):**
  ```bash
  python3 -m unittest tests.test_feature_spec -v
  ```
  Expected: `ImportError: cannot import name 'POSTCONDITION_KINDS' from 'intent_spec'` (or similar). This proves the API is missing.

- [ ] **0.4 — Implement the contract-exact API.** Append to `scripts/intent_spec.py` immediately after the `find_unused_anchors` function (before `def _main`). Insert this block:
  ```python
  # ── FeatureSpec layer — the per-feature spine (Gate 1->2 + generalized 4->5) ──

  POSTCONDITION_KINDS = (
      "count_increased",
      "count_decreased",
      "value_persisted_after_relaunch",
      "navigated_to",
      "artifact_generated",
      "setting_stored",
  )


  @dataclass
  class Postcondition:
      kind: str
      params: dict = field(default_factory=dict)


  @dataclass
  class Acceptance:
      id: str
      kind: str  # "flow" | "logic"
      steps: tuple[dict, ...]
      postcondition: Postcondition


  @dataclass
  class FeatureSpec:
      id: str
      title: str
      priority: str  # "P0" | "P1" | "P2"
      screen: str
      anchor: str
      acceptance: tuple[Acceptance, ...]

      @classmethod
      def from_dict(cls, data: dict) -> "FeatureSpec":
          accs: list[Acceptance] = []
          for a in (data.get("acceptance") or ()):
              if not isinstance(a, dict):
                  continue
              pc = a.get("postcondition") or {}
              if not isinstance(pc, dict):
                  pc = {}
              steps = tuple(s for s in (a.get("steps") or ()) if isinstance(s, dict))
              accs.append(Acceptance(
                  id=str(a.get("id") or ""),
                  kind=str(a.get("kind") or "flow"),
                  steps=steps,
                  postcondition=Postcondition(
                      kind=str(pc.get("kind") or ""),
                      params=dict(pc.get("params") or {}),
                  ),
              ))
          return cls(
              id=str(data.get("id") or ""),
              title=str(data.get("title") or ""),
              priority=str(data.get("priority") or ""),
              screen=str(data.get("screen") or ""),
              anchor=str(data.get("anchor") or ""),
              acceptance=tuple(accs),
          )


  def load_feature_spec(project_root: Path) -> list[FeatureSpec] | None:
      """Return parsed features, or None if the manifest is absent / unparseable."""
      path = project_root / ".autobot" / "feature-spec.json"
      if not path.is_file():
          return None
      try:
          data = json.loads(path.read_text(encoding="utf-8"))
      except (json.JSONDecodeError, OSError):
          return None
      if not isinstance(data, dict):
          return None
      raw = data.get("features")
      if not isinstance(raw, list):
          return None
      return [FeatureSpec.from_dict(f) for f in raw if isinstance(f, dict)]


  def validate_feature_spec(project_root: Path) -> tuple[bool, list[str]]:
      """Structural gate: every P0/P1 feature has >=1 acceptance AND a non-empty anchor."""
      features = load_feature_spec(project_root)
      if features is None:
          return False, ["feature-spec.json absent or unparseable"]
      problems: list[str] = []
      for feat in features:
          if feat.priority not in ("P0", "P1"):
              continue
          if not feat.acceptance:
              problems.append(f"{feat.priority} feature '{feat.id}' has no acceptance")
          if not feat.anchor.strip():
              problems.append(f"{feat.priority} feature '{feat.id}' has empty anchor")
      return (not problems), problems


  def assess_feature_spec_quality(project_root: Path) -> tuple[bool, list[str]]:
      """Quality gate: every P0/P1 acceptance postcondition.kind is a recognized
      behavioral postcondition (anchor-only / placeholder postconditions are invalid).
      """
      features = load_feature_spec(project_root)
      if features is None:
          return False, ["feature-spec.json absent or unparseable"]
      problems: list[str] = []
      for feat in features:
          if feat.priority not in ("P0", "P1"):
              continue
          for acc in feat.acceptance:
              if acc.postcondition.kind not in POSTCONDITION_KINDS:
                  problems.append(
                      f"{feat.priority} feature '{feat.id}' acceptance '{acc.id}': "
                      f"postcondition.kind='{acc.postcondition.kind or '(empty)'}' "
                      f"is not a behavioral postcondition (anchor-only is invalid)"
                  )
      return (not problems), problems
  ```
  Note: `dataclass` and `field` are already imported at the top of `intent_spec.py` (line 35: `from dataclasses import dataclass, field`). `json`, `re`, `Path` also already imported. No new imports needed.

- [ ] **0.5 — Run again, expect PASS:**
  ```bash
  python3 -m unittest tests.test_feature_spec -v
  ```
  Expected: `OK` (10 tests).

- [ ] **0.6 — Commit:**
  ```bash
  git add scripts/intent_spec.py tests/test_feature_spec.py
  git commit -m "feat(intent_spec): FeatureSpec layer (load/validate/assess) — per-feature spine"
  ```

---

### Task 1: Gate 1->2 — check_feature_spec_declared + check_feature_spec_quality (capability.py)

**Files:** `scripts/gate_checks/capability.py`, `tests/test_feature_spec_gates.py`, `scripts/gate_runner.py` (registry + re-export)

These are **hard structural gates** — `degraded` does NOT apply. The feature-spec is the new spine, so absence is a **FAIL, not a skip** (contract: "if feature-spec absent, FAIL not skip"). This is the deliberate behavioral difference from `check_app_intent_declared`, which soft-skips when its manifest is absent.

- [ ] **1.1 — Write failing test** at `tests/test_feature_spec_gates.py`:
  ```python
  """Gate 1->2 feature-spec checks — the per-feature spine is now mandatory.
  Absent feature-spec.json is a HARD FAIL (not a skip), unlike legacy app-intent.
  """
  from __future__ import annotations

  import json
  import tempfile
  import unittest
  from pathlib import Path

  from conftest import import_runtime_modules

  import_runtime_modules()

  from gate_runner import (  # noqa: E402
      check_feature_spec_declared,
      check_feature_spec_quality,
  )


  def _write(root: Path, payload: dict) -> None:
      (root / ".autobot").mkdir(parents=True, exist_ok=True)
      (root / ".autobot" / "feature-spec.json").write_text(json.dumps(payload), encoding="utf-8")


  def _feat(fid="f1", priority="P0", anchor="autobot.f1.cta", pc="count_increased",
            with_acceptance=True) -> dict:
      acc = [{
          "id": f"{fid}.a1", "kind": "flow",
          "steps": [{"action": "tap", "anchor": anchor}],
          "postcondition": {"kind": pc, "params": {}},
      }] if with_acceptance else []
      return {"id": fid, "title": fid, "priority": priority, "screen": "Home",
              "anchor": anchor, "acceptance": acc}


  class TestFeatureSpecDeclared(unittest.TestCase):
      def test_valid_p0_passes(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write(Path(tmp), {"features": [_feat()]})
              r = check_feature_spec_declared(Path(tmp), "Demo", {})
              self.assertTrue(r[0]["passed"], r[0]["message"])
              self.assertFalse(r[0].get("skipped"))

      def test_p0_lacking_acceptance_fails(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write(Path(tmp), {"features": [_feat(with_acceptance=False)]})
              r = check_feature_spec_declared(Path(tmp), "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertFalse(r[0].get("skipped"))
              self.assertIn("acceptance", r[0]["message"])

      def test_absent_is_hard_fail_not_skip(self):
          with tempfile.TemporaryDirectory() as tmp:
              r = check_feature_spec_declared(Path(tmp), "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertFalse(r[0].get("skipped"))
              self.assertFalse(r[0].get("degraded"))
              self.assertIn("feature-spec.json", r[0]["message"])


  class TestFeatureSpecQuality(unittest.TestCase):
      def test_behavioral_postcondition_passes(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write(Path(tmp), {"features": [_feat(pc="value_persisted_after_relaunch")]})
              r = check_feature_spec_quality(Path(tmp), "Demo", {})
              self.assertTrue(r[0]["passed"], r[0]["message"])

      def test_anchor_only_postcondition_fails(self):
          with tempfile.TemporaryDirectory() as tmp:
              _write(Path(tmp), {"features": [_feat(pc="anchor_present")]})
              r = check_feature_spec_quality(Path(tmp), "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertIn("postcondition", r[0]["message"])

      def test_absent_is_hard_fail_not_skip(self):
          with tempfile.TemporaryDirectory() as tmp:
              r = check_feature_spec_quality(Path(tmp), "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertFalse(r[0].get("skipped"))
              self.assertIn("feature-spec.json", r[0]["message"])


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **1.2 — Run, expect FAIL (ImportError):**
  ```bash
  python3 -m unittest tests.test_feature_spec_gates -v
  ```
  Expected: `ImportError: cannot import name 'check_feature_spec_declared' from 'gate_runner'`.

- [ ] **1.3 — Implement the two checks.** In `scripts/gate_checks/capability.py`, insert immediately after `check_app_intent_declared` (after line 92, the existing `return [_ok("app_intent_declared", False, ...)]` block) and before `check_intent_anchors_in_ui`:
  ```python
  def check_feature_spec_declared(proj: Path, app: str, state: dict) -> list[dict]:
      """Phase 1→2 — the architect must declare a per-feature spec where every
      P0/P1 feature has at least one acceptance AND a non-empty anchor.

      This is the new SPINE: unlike legacy `app-intent.json` (which soft-skips
      when absent), `feature-spec.json` is mandatory. Absence is a HARD FAIL —
      there is nothing for Phase 5 functional flows to drive without it.
      """
      from intent_spec import validate_feature_spec, load_feature_spec

      ok, problems = validate_feature_spec(proj)
      if ok:
          features = load_feature_spec(proj) or []
          p_counts = {"P0": 0, "P1": 0, "P2": 0}
          for f in features:
              p_counts[f.priority] = p_counts.get(f.priority, 0) + 1
          return [_ok(
              "feature_spec_declared", True,
              f"{len(features)} feature(s) declared "
              f"(P0={p_counts.get('P0', 0)}, P1={p_counts.get('P1', 0)}, "
              f"P2={p_counts.get('P2', 0)}); every P0/P1 has acceptance + anchor",
          )]
      return [_ok(
          "feature_spec_declared", False,
          f"feature-spec.json invalid: {'; '.join(problems)}",
      )]


  def check_feature_spec_quality(proj: Path, app: str, state: dict) -> list[dict]:
      """Phase 1→2 — every P0/P1 acceptance must assert a behavioral postcondition.

      An acceptance whose postcondition is merely "the anchor exists" (kind not in
      POSTCONDITION_KINDS) is a placeholder that cannot prove the feature works.
      Hard gate: absent / placeholder-only specs FAIL.
      """
      from intent_spec import assess_feature_spec_quality

      ok, problems = assess_feature_spec_quality(proj)
      if ok:
          return [_ok(
              "feature_spec_quality", True,
              "all P0/P1 acceptances assert a behavioral postcondition",
          )]
      sample = "; ".join(problems[:3])
      more = f" (+{len(problems) - 3} more)" if len(problems) > 3 else ""
      return [_ok(
          "feature_spec_quality", False,
          f"feature-spec quality: {sample}{more}",
      )]
  ```

- [ ] **1.4 — Wire into gate_runner.** In `scripts/gate_runner.py`, extend the capability import block (currently lines 51-55, ends with `check_ios_capability_safe`). Add the two names. Change:
  ```python
  from gate_checks.capability import (  # noqa: E402,F401
      check_app_intent_declared,
      check_intent_anchors_in_ui,
      check_primary_cta_visibility,
      check_ios_capability_safe
  ```
  to:
  ```python
  from gate_checks.capability import (  # noqa: E402,F401
      check_app_intent_declared,
      check_feature_spec_declared,
      check_feature_spec_quality,
      check_intent_anchors_in_ui,
      check_primary_cta_visibility,
      check_ios_capability_safe
  ```
  Then in the `GATE_CHECKS` dict (Gate 1→2 block, after line 119 `"intent_anchors_in_ui": check_intent_anchors_in_ui,`), add:
  ```python
      "feature_spec_declared": check_feature_spec_declared,
      "feature_spec_quality": check_feature_spec_quality,
  ```

- [ ] **1.5 — Run, expect PASS:**
  ```bash
  python3 -m unittest tests.test_feature_spec_gates -v
  ```
  Expected: `OK` (6 tests).

- [ ] **1.6 — Commit:**
  ```bash
  git add scripts/gate_checks/capability.py scripts/gate_runner.py tests/test_feature_spec_gates.py
  git commit -m "feat(gate 1->2): feature_spec_declared + feature_spec_quality hard gates"
  ```

---

### Task 2: Generalize check_intent_anchors_in_ui to per-feature anchors

**Files:** `scripts/intent_spec.py` (new helper `find_missing_feature_anchors`), `scripts/gate_checks/capability.py` (rewrite `check_intent_anchors_in_ui`), `tests/test_intent_anchors_per_feature.py`

The current `check_intent_anchors_in_ui` only checks app-intent's flat `requiredAnchors`. Generalize it so that **when feature-spec is present**, EACH feature's `anchor` must appear in source, and the failure message names which FEATURE is missing UI. **Fall back to app-intent anchors when feature-spec is absent** (preserves the legacy path and the existing `test_intent_spec.py::TestFindUnusedAnchors` behavior — `find_unused_anchors` is untouched).

- [ ] **2.1 — Write failing test** at `tests/test_intent_anchors_per_feature.py`:
  ```python
  """Gate 4->5 intent_anchors_in_ui — generalized to per-feature anchors.
  When feature-spec.json is present, each feature's anchor must appear in the
  UI source; the failure names which FEATURE is missing its UI. Falls back to
  flat app-intent requiredAnchors when feature-spec is absent.
  """
  from __future__ import annotations

  import json
  import tempfile
  import unittest
  from pathlib import Path

  from conftest import import_runtime_modules

  import_runtime_modules()

  from gate_runner import check_intent_anchors_in_ui  # noqa: E402


  def _autobot(root: Path) -> Path:
      d = root / ".autobot"
      d.mkdir(parents=True, exist_ok=True)
      return d


  def _write_feature_spec(root: Path, features: list[dict]) -> None:
      _autobot(root)
      (root / ".autobot" / "feature-spec.json").write_text(
          json.dumps({"features": features}), encoding="utf-8")


  def _write_app_intent(root: Path, payload: dict) -> None:
      _autobot(root)
      (root / ".autobot" / "app-intent.json").write_text(
          json.dumps(payload), encoding="utf-8")


  def _write_view(root: Path, app: str, name: str, anchors: list[str]) -> None:
      vdir = root / app / "Views"
      vdir.mkdir(parents=True, exist_ok=True)
      body = "import SwiftUI\nstruct V: View { var body: some View { Text(\"x\")"
      for a in anchors:
          body += f'.accessibilityIdentifier("{a}")'
      body += " } }"
      (vdir / f"{name}.swift").write_text(body, encoding="utf-8")


  def _feat(fid, anchor, priority="P0") -> dict:
      return {"id": fid, "title": fid, "priority": priority, "screen": "Home",
              "anchor": anchor,
              "acceptance": [{"id": f"{fid}.a1", "kind": "flow",
                              "steps": [{"action": "tap", "anchor": anchor}],
                              "postcondition": {"kind": "navigated_to", "params": {}}}]}


  class TestPerFeatureAnchors(unittest.TestCase):
      def test_all_feature_anchors_present_passes(self):
          with tempfile.TemporaryDirectory() as tmp:
              root = Path(tmp)
              _write_feature_spec(root, [
                  _feat("log", "autobot.log.cta"),
                  _feat("share", "autobot.share.cta"),
              ])
              _write_view(root, "Demo", "Screens",
                          ["autobot.log.cta", "autobot.share.cta"])
              r = check_intent_anchors_in_ui(root, "Demo", {})
              self.assertTrue(r[0]["passed"], r[0]["message"])

      def test_missing_feature_anchor_names_feature(self):
          with tempfile.TemporaryDirectory() as tmp:
              root = Path(tmp)
              _write_feature_spec(root, [
                  _feat("log", "autobot.log.cta"),
                  _feat("share", "autobot.share.cta"),
              ])
              # only log's anchor is in the UI
              _write_view(root, "Demo", "Screens", ["autobot.log.cta"])
              r = check_intent_anchors_in_ui(root, "Demo", {})
              self.assertFalse(r[0]["passed"])
              # message must name the FEATURE (id), not just the anchor
              self.assertIn("share", r[0]["message"])
              self.assertIn("autobot.share.cta", r[0]["message"])

      def test_p2_feature_missing_anchor_still_fails(self):
          # generalized check asserts EVERY feature's anchor regardless of priority;
          # priority tiering is for acceptance/flows, not for anchor presence.
          with tempfile.TemporaryDirectory() as tmp:
              root = Path(tmp)
              _write_feature_spec(root, [_feat("opt", "autobot.opt.cta", priority="P2")])
              _write_view(root, "Demo", "Screens", [])
              r = check_intent_anchors_in_ui(root, "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertIn("opt", r[0]["message"])

      def test_falls_back_to_app_intent_when_no_feature_spec(self):
          with tempfile.TemporaryDirectory() as tmp:
              root = Path(tmp)
              _write_app_intent(root, {
                  "appName": "Demo", "promise": "p",
                  "primaryScreenTitle": "Home", "primaryCTA": "Go",
                  "requiredAnchors": ["autobot.root", "autobot.primaryCTA"],
              })
              _write_view(root, "Demo", "Screens",
                          ["autobot.root", "autobot.primaryCTA"])
              r = check_intent_anchors_in_ui(root, "Demo", {})
              self.assertTrue(r[0]["passed"], r[0]["message"])

      def test_falls_back_and_detects_missing_app_intent_anchor(self):
          with tempfile.TemporaryDirectory() as tmp:
              root = Path(tmp)
              _write_app_intent(root, {
                  "appName": "Demo", "promise": "p",
                  "primaryScreenTitle": "Home", "primaryCTA": "Go",
                  "requiredAnchors": ["autobot.root", "autobot.primaryCTA"],
              })
              _write_view(root, "Demo", "Screens", ["autobot.root"])
              r = check_intent_anchors_in_ui(root, "Demo", {})
              self.assertFalse(r[0]["passed"])
              self.assertIn("autobot.primaryCTA", r[0]["message"])

      def test_no_spec_at_all_skips(self):
          with tempfile.TemporaryDirectory() as tmp:
              r = check_intent_anchors_in_ui(Path(tmp), "Demo", {})
              self.assertTrue(r[0]["passed"])
              self.assertTrue(r[0].get("skipped"))


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **2.2 — Run, expect FAIL.** Until the rewrite, the current implementation (flat app-intent only) will fail several cases. Run:
  ```bash
  python3 -m unittest tests.test_intent_anchors_per_feature -v
  ```
  Expected: failures on `test_all_feature_anchors_present_passes`, `test_missing_feature_anchor_names_feature`, `test_p2_feature_missing_anchor_still_fails` (these reference feature-spec, which the current check ignores — it returns the app-intent skip path). The fallback tests may pass coincidentally; that's fine.

- [ ] **2.3 — Add the per-feature anchor helper** to `scripts/intent_spec.py`, immediately after the `find_unused_anchors` function (and after the FeatureSpec block from Task 0, before `_main`):
  ```python
  def find_missing_feature_anchors(
      project_root: Path, app_name: str
  ) -> list[tuple[str, str]]:
      """Return [(featureId, anchor), ...] for every feature whose anchor does NOT
      appear in the Phase 4 UI source tree. Empty list = all anchors present.

      Searches Views/, App/, and ViewModels/ — the same scope as
      find_unused_anchors — so anchors declared in the root composition count.
      """
      features = load_feature_spec(project_root)
      if not features:
          return []

      app_root = project_root / app_name
      files: list[Path] = []
      if app_root.is_dir():
          for sub in ("Views", "App", "ViewModels"):
              path = app_root / sub
              if path.is_dir():
                  files.extend(path.rglob("*.swift"))

      combined = "\n".join(
          f.read_text(encoding="utf-8", errors="replace") for f in files
      )

      missing: list[tuple[str, str]] = []
      for feat in features:
          anchor = feat.anchor.strip()
          if not anchor:
              # empty anchor is a validate_feature_spec problem, not an anchor-in-UI
              # problem; skip here so the message stays about UI wiring.
              continue
          pattern = re.compile(
              rf'accessibilityIdentifier\(\s*"{re.escape(anchor)}"\s*\)'
              rf'|"{re.escape(anchor)}"\s*as\s+AccessibilityIdentifier'
              rf'|accessibilityIdentifier:\s*"{re.escape(anchor)}"'
          )
          if not pattern.search(combined):
              missing.append((feat.id, anchor))
      return missing
  ```

- [ ] **2.4 — Rewrite `check_intent_anchors_in_ui`** in `scripts/gate_checks/capability.py`. Replace the entire current function body (lines 95-121) with:
  ```python
  def check_intent_anchors_in_ui(proj: Path, app: str, state: dict) -> list[dict]:
      """Phase 4→5 — every anchor the architect promised must appear in the UI tree.

      When `feature-spec.json` is present, assert EACH feature's `anchor` (the
      check the new spine is built around) and name the FEATURE that is missing
      its UI. When only legacy `app-intent.json` exists, fall back to the flat
      `requiredAnchors` set. Without either manifest, skip (benign).

      Without this, the UI test target launched at Phase 5 cannot find the views
      it is supposed to assert against, and runtime-smoke can pass while the
      actual happy path is broken.
      """
      from intent_spec import (
          find_missing_feature_anchors,
          find_unused_anchors,
          load_app_intent,
          load_feature_spec,
      )

      features = load_feature_spec(proj)
      if features:
          missing = find_missing_feature_anchors(proj, app)
          if not missing:
              return [_ok(
                  "intent_anchors_in_ui", True,
                  f"all {len(features)} feature anchor(s) present in UI tree",
              )]
          detail = ", ".join(f"{fid} ({anchor})" for fid, anchor in missing)
          return [_ok(
              "intent_anchors_in_ui", False,
              f"feature(s) missing UI anchors: {detail}",
          )]

      # Legacy fallback: flat app-intent requiredAnchors.
      intent = load_app_intent(proj)
      if intent is None:
          return [_ok(
              "intent_anchors_in_ui", True,
              "feature-spec.json and app-intent.json both absent — skipping",
              skipped=True,
          )]
      missing_a, present = find_unused_anchors(proj, app)
      if not missing_a:
          return [_ok(
              "intent_anchors_in_ui", True,
              f"all {len(present)} required anchors present in UI tree (app-intent fallback)",
          )]
      return [_ok(
          "intent_anchors_in_ui", False,
          f"missing accessibility identifiers in UI: {', '.join(missing_a)} "
          f"(present: {', '.join(present) or 'none'})",
      )]
  ```

- [ ] **2.5 — Run, expect PASS:**
  ```bash
  python3 -m unittest tests.test_intent_anchors_per_feature -v
  ```
  Expected: `OK` (6 tests).

- [ ] **2.6 — Regression: existing intent_spec tests still pass** (proves `find_unused_anchors` and the app-intent fallback are untouched):
  ```bash
  python3 -m unittest tests.test_intent_spec -v
  ```
  Expected: `OK` (all existing tests, unchanged).

- [ ] **2.7 — Commit:**
  ```bash
  git add scripts/intent_spec.py scripts/gate_checks/capability.py tests/test_intent_anchors_per_feature.py
  git commit -m "feat(gate 4->5): generalize intent_anchors_in_ui to per-feature anchors w/ app-intent fallback"
  ```

---

### Task 3: spec/pipeline.json wiring

**Files:** `spec/pipeline.json`, `tests/test_feature_spec_spec_wiring.py`

Append the two new procedural descriptors to Gate 1→2. Gate 4→5 already has `intent_anchors_in_ui` (lines 1119-1123) — no JSON change there, only a confirming assertion. Insert the new Gate 1→2 descriptors **after `app_intent_declared` (closes at line 980) and before the `architect_consumed_learnings` state check (opens at line 981)**.

- [ ] **3.1 — Write failing test** at `tests/test_feature_spec_spec_wiring.py`:
  ```python
  """spec/pipeline.json wiring for the feature-spec spine: Gate 1->2 must list
  feature_spec_declared + feature_spec_quality, Gate 4->5 keeps intent_anchors_in_ui,
  and every named procedural check must have an impl in the GATE_CHECKS registry.
  """
  from __future__ import annotations

  import json
  import unittest
  from pathlib import Path

  from conftest import import_runtime_modules

  import_runtime_modules()

  from gate_runner import GATE_CHECKS  # noqa: E402

  SPEC = Path(__file__).resolve().parent.parent / "spec" / "pipeline.json"


  def _names(gate: dict) -> list[str]:
      return [c.get("name") for c in gate.get("checks", []) if c.get("type") == "procedural"]


  class TestFeatureSpecSpecWiring(unittest.TestCase):
      def setUp(self):
          self.spec = json.loads(SPEC.read_text(encoding="utf-8"))
          self.gates = self.spec["gates"]

      def test_gate_1_2_lists_feature_spec_checks(self):
          names = _names(self.gates["1->2"])
          self.assertIn("feature_spec_declared", names)
          self.assertIn("feature_spec_quality", names)

      def test_gate_4_5_keeps_intent_anchors(self):
          names = _names(self.gates["4->5"])
          self.assertIn("intent_anchors_in_ui", names)

      def test_new_checks_have_impls(self):
          for name in ("feature_spec_declared", "feature_spec_quality", "intent_anchors_in_ui"):
              self.assertIn(name, GATE_CHECKS, f"{name} missing from GATE_CHECKS registry")

      def test_descriptor_shape(self):
          for c in self.gates["1->2"]["checks"]:
              if c.get("name") in ("feature_spec_declared", "feature_spec_quality"):
                  self.assertEqual(c["type"], "procedural")
                  self.assertEqual(c["label"], c["name"])


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **3.2 — Run, expect FAIL:**
  ```bash
  python3 -m unittest tests.test_feature_spec_spec_wiring -v
  ```
  Expected: `test_gate_1_2_lists_feature_spec_checks` fails (`'feature_spec_declared' not found`). `test_gate_4_5_keeps_intent_anchors` passes (already wired). `test_new_checks_have_impls` passes only if Task 1 already landed the registry entries; otherwise it fails too.

- [ ] **3.3 — Edit `spec/pipeline.json`.** Use the Edit tool. Replace this exact block (the `app_intent_declared` descriptor immediately followed by the `architect_consumed_learnings` descriptor, lines ~976-982):
  ```json
        {
          "type": "procedural",
          "name": "app_intent_declared",
          "label": "app_intent_declared"
        },
        {
          "type": "state_field_contains",
          "label": "architect_consumed_learnings",
  ```
  with:
  ```json
        {
          "type": "procedural",
          "name": "app_intent_declared",
          "label": "app_intent_declared"
        },
        {
          "type": "procedural",
          "name": "feature_spec_declared",
          "label": "feature_spec_declared"
        },
        {
          "type": "procedural",
          "name": "feature_spec_quality",
          "label": "feature_spec_quality"
        },
        {
          "type": "state_field_contains",
          "label": "architect_consumed_learnings",
  ```
  (Gate 4→5's `intent_anchors_in_ui` at lines 1119-1123 is left exactly as-is — confirmed present.)

- [ ] **3.4 — Validate JSON parses + schema/drift checks** (the CI checks added in commit `00bd582`):
  ```bash
  python3 -c "import json; json.load(open('spec/pipeline.json')); print('JSON OK')"
  python3 -m unittest tests.test_verify_spec_docs_contracts -v
  ```
  Expected: `JSON OK`, then `OK` for the spec/docs/contracts verification (every procedural `name` resolves to a `GATE_CHECKS` impl — this is why Task 1 must land before this test passes).

- [ ] **3.5 — Run, expect PASS:**
  ```bash
  python3 -m unittest tests.test_feature_spec_spec_wiring -v
  ```
  Expected: `OK` (4 tests).

- [ ] **3.6 — Commit:**
  ```bash
  git add spec/pipeline.json tests/test_feature_spec_spec_wiring.py
  git commit -m "spec(gate 1->2): wire feature_spec_declared + feature_spec_quality descriptors"
  ```

---

### Task 4: Agent prompt edits — ui-builder per-feature anchors + quality-engineer functional standard

**Files:** `agents/ui-builder.md`, `agents/quality-engineer.md`

No automated test (prompt docs). Verification is a grep assertion that the new instruction text is present, run as a tiny unittest so it's part of the suite.

- [ ] **4.1 — Write the doc-content assertion test** at `tests/test_agent_prompt_feature_anchors.py`:
  ```python
  """Agent prompts must instruct per-feature anchor attachment (ui-builder) and a
  functional-acceptance test standard (quality-engineer). These keep the prompts
  in sync with the feature-spec spine gates.
  """
  from __future__ import annotations

  import unittest
  from pathlib import Path

  AGENTS = Path(__file__).resolve().parent.parent / "agents"


  class TestAgentPrompts(unittest.TestCase):
      def test_ui_builder_mentions_feature_spec_anchor(self):
          text = (AGENTS / "ui-builder.md").read_text(encoding="utf-8")
          self.assertIn("feature-spec.json", text)
          self.assertIn("feature", text.lower())
          # the per-feature anchor field must be named so the agent attaches it
          self.assertIn(".accessibilityIdentifier", text)

      def test_quality_engineer_requires_functional_acceptance(self):
          text = (AGENTS / "quality-engineer.md").read_text(encoding="utf-8")
          self.assertIn("functional acceptance", text.lower())
          self.assertIn("P0", text)
          self.assertIn("compile", text.lower())


  if __name__ == "__main__":
      unittest.main()
  ```

- [ ] **4.2 — Run, expect FAIL:**
  ```bash
  python3 -m unittest tests.test_agent_prompt_feature_anchors -v
  ```
  Expected: `test_ui_builder_mentions_feature_spec_anchor` fails (`'feature-spec.json' not found` — current ui-builder.md says `app-intent.json` only) and `test_quality_engineer_requires_functional_acceptance` fails (no "functional acceptance" text).

- [ ] **4.3 — Edit `agents/ui-builder.md`.** Replace CRITICAL RULE 3 (lines 19-23, the block starting `3. **Accessibility identifiers from`) — replace this exact text:
  ```
  3. **Accessibility identifiers from `.autobot/app-intent.json` 는 반드시 부착**한다. Phase 5 의 `intent_anchors_in_ui` 게이트가 정확한 문자열을 grep 한다:
     - root NavigationStack 컨테이너에 `.accessibilityIdentifier("autobot.root")`
     - primary 화면 (architect 가 `primaryScreenTitle` 로 지정한 화면) 의 `navigationTitle` 직속 element 에 `.accessibilityIdentifier("autobot.primaryTitle")`
     - primary CTA 버튼에 `.accessibilityIdentifier("autobot.primaryCTA")`
     - app-intent.json 에 `autobot.primaryList` 가 있으면 해당 List/ScrollView 에도 부착
  ```
  with:
  ```
  3. **Accessibility identifiers 는 반드시 부착**한다. Phase 5 의 `intent_anchors_in_ui` 게이트가 정확한 문자열을 grep 한다. 두 출처를 모두 만족시켜라:
     - `.autobot/app-intent.json` (기본 골격):
       - root NavigationStack 컨테이너에 `.accessibilityIdentifier("autobot.root")`
       - primary 화면 (architect 가 `primaryScreenTitle` 로 지정한 화면) 의 `navigationTitle` 직속 element 에 `.accessibilityIdentifier("autobot.primaryTitle")`
       - primary CTA 버튼에 `.accessibilityIdentifier("autobot.primaryCTA")`
       - app-intent.json 에 `autobot.primaryList` 가 있으면 해당 List/ScrollView 에도 부착
     - **`.autobot/feature-spec.json` (per-feature spine — 반드시 부착)**: `features[]` 배열의 **모든 feature 마다 `anchor` 필드 문자열**을, 그 feature 를 트리거하는 인터랙티브 element (보통 acceptance.steps[0].anchor 와 동일한 버튼/탭/셀) 에 `.accessibilityIdentifier("<feature.anchor>")` 로 부착한다. primaryCTA 만으로는 부족하다 — Phase 5 의 `functional_flows_pass` 가 각 feature 의 anchor 를 AXe 로 탭하므로, feature 하나라도 anchor 가 UI 에 없으면 `intent_anchors_in_ui` 가 **그 feature id 를 지목하며 FAIL** 한다.
  ```

- [ ] **4.4 — Edit `agents/quality-engineer.md`.** Replace the "Quality Standards" block (lines 49-53):
  ```
  **Quality Standards:**
  - Build must succeed with zero errors
  - Zero force unwraps in production code
  - At least one test per data model
  - All warnings addressed (not just errors)
  ```
  with:
  ```
  **Quality Standards:**
  - Build must succeed with zero errors
  - Zero force unwraps in production code
  - At least one test per data model
  - All warnings addressed (not just errors)
  - **Authored tests MUST compile AND pass.** Phase 5→6 의 `logic_tests_pass` 가 `xcodebuild ... test` 결과(.xcresult)를 파싱한다. 컴파일만 되고 실패하는 테스트, 또는 `#expect(true)` 같은 빈 테스트는 게이트를 통과시키지 못한다.
  - **모든 P0 feature 마다 최소 1개의 functional acceptance 테스트를 작성한다.** `.autobot/feature-spec.json` 의 각 P0 feature 에 대해, 해당 feature 의 `acceptance[].postcondition` (예: `count_increased`, `value_persisted_after_relaunch`) 을 실제로 검증하는 테스트를 만든다 — anchor 가 화면에 존재한다는 사실만 단언하는 테스트는 functional acceptance 로 인정되지 않는다. flow 종류의 acceptance 는 Phase 5→6 의 `functional_flows_pass` 가 AXe 로 구동하고, logic 종류는 이 단계에서 작성한 단위/통합 테스트가 검증한다.
  ```

- [ ] **4.5 — Run, expect PASS:**
  ```bash
  python3 -m unittest tests.test_agent_prompt_feature_anchors -v
  ```
  Expected: `OK` (2 tests).

- [ ] **4.6 — Full suite sanity** (no regressions from any task):
  ```bash
  bash tests/run_tests.sh 2>&1 | tail -25
  ```
  Expected: trailing `OK` (entire stdlib unittest suite green).

- [ ] **4.7 — Commit:**
  ```bash
  git add agents/ui-builder.md agents/quality-engineer.md tests/test_agent_prompt_feature_anchors.py
  git commit -m "docs(agents): ui-builder per-feature anchors + quality-engineer functional-acceptance standard"
  ```

---

## WS3 — Logic tests (run authored tests, harness-verified build, unit-test target)

### Task 1: `check_logic_tests_pass` in NEW `scripts/gate_checks/functional.py` (parse `.xcresult` via xcresulttool)

**Goal**: Add a Gate 5→6 procedural check that runs the authored Swift Testing unit tests through `integration_build(test=True)`, parses the produced `Build.xcresult` with `xcrun xcresulttool get test-results summary`, and returns pass / hard-fail (tests failed) / degraded-skip (no xcodebuild or no simulator). Plus a NON-blocking soft completeness sub-check: warn when a P0 `logic` acceptance has no correspondingly-named authored test.

**Files**
- NEW: `/Users/louis/Code/Autobot/scripts/gate_checks/functional.py`
- EDIT: `/Users/louis/Code/Autobot/scripts/gate_checks/_helpers.py` (extend `_ok` per LOCKED CONTRACT)
- EDIT: `/Users/louis/Code/Autobot/scripts/gate_runner.py` (register in `GATE_CHECKS`)
- EDIT: `/Users/louis/Code/Autobot/spec/pipeline.json` (add to gate `5->6` checks)
- NEW test: `/Users/louis/Code/Autobot/tests/test_functional_logic.py`

> NOTE on ownership: the `_ok` `degraded=` extension and the three-valued `run_gate` verdict are SHARED CONTRACT. If another work-stream has already applied the `_helpers.py` `_ok` edit below verbatim, SKIP step 1.2 (the edit will be a no-op / already-present) and proceed. The signature MUST end up exactly: `_ok(check, passed, message, *, skipped=False, degraded=False) -> dict`.

---

**Step 1.1 — Write the failing pytest (unittest) FIRST.**

The suite runs via `python3 -m unittest discover` (see `tests/run_tests.sh`), so tests MUST be `unittest.TestCase` subclasses and import runtime via `conftest.import_runtime_modules()` (mirror `tests/test_visual_contract.py`). We parse a FIXTURE `.xcresult` by monkeypatching the `xcresulttool` invocation and `integration_build`, so no real simulator is needed.

Create `/Users/louis/Code/Autobot/tests/test_functional_logic.py`:

```python
"""Tests for scripts/gate_checks/functional.py::check_logic_tests_pass.

Drives the parser against synthetic xcresulttool-summary JSON (pass + fail)
and asserts the degraded-skip path when integration_build reports no
xcodebuild / no simulator. No real .xcresult or simulator is touched — the
xcresulttool subprocess and integration_build are both monkeypatched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import functional as fn  # scripts/gate_checks/functional.py  # noqa: E402


# ── Fixture builders mirroring `xcresulttool get test-results summary` ──
def _summary_json(*, result: str, total: int, passed: int, failed: int) -> str:
    return json.dumps({
        "title": "Test",
        "result": result,            # "Passed" | "Failed" | "Skipped"
        "totalTestCount": total,
        "passedTests": passed,
        "failedTests": failed,
        "skippedTests": 0,
        "expectedFailures": 0,
    })


def _tests_json(*test_names: str) -> str:
    """Mirror `get test-results tests`: nested testNodes tree whose leaf
    nodeType == 'Test Case' carries the authored test function name."""
    cases = [
        {"nodeType": "Test Case", "name": n, "result": "Passed"} for n in test_names
    ]
    return json.dumps({
        "testNodes": [
            {"nodeType": "Test Plan", "name": "Plan", "children": [
                {"nodeType": "Unit test bundle", "name": "DemoTests", "children": [
                    {"nodeType": "Test Suite", "name": "LogicTests", "children": cases},
                ]},
            ]},
        ],
    })


class _Patches:
    """Context object collecting monkeypatches; restored in tearDown."""

    def __init__(self) -> None:
        self._orig: list = []

    def set(self, obj, attr, value) -> None:
        self._orig.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, value)

    def restore(self) -> None:
        for obj, attr, value in reversed(self._orig):
            setattr(obj, attr, value)


class TestCheckLogicTestsPass(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        self.p = _Patches()

    def tearDown(self) -> None:
        self.p.restore()
        self._tmp.cleanup()

    def _patch_build(self, *, status: str, skip_reason: str | None = None) -> Path:
        bundle = self.proj / "Build.xcresult"
        def fake_build(project_root, app_name, *, attempt=1, test=False):
            out = {"phase": "5", "status": status}
            if status == "skipped":
                out["skipReason"] = skip_reason or "xcodebuild_unavailable"
            else:
                out["resultBundlePath"] = str(bundle)
                out["exitCode"] = 0 if status == "passed" else 65
            return out
        self.p.set(fn, "integration_build", fake_build)
        return bundle

    def _patch_xcresult(self, summary: str, tests: str | None = None) -> None:
        def fake_run(cmd, *, timeout=120):
            # cmd is the xcresulttool argv built by functional._xcresult_json
            if "summary" in cmd:
                return 0, summary
            if "tests" in cmd:
                return 0, tests if tests is not None else _tests_json()
            return 1, "unexpected"
        self.p.set(fn, "_run_xcresulttool", fake_run)

    # ── degraded skip: no xcodebuild ──
    def test_no_xcodebuild_is_degraded_skip(self):
        self._patch_build(status="skipped", skip_reason="xcodebuild_unavailable")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertEqual(primary["check"], "logic_tests_pass")
        self.assertFalse(primary["passed"])
        self.assertTrue(primary.get("skipped"))
        self.assertTrue(primary.get("degraded"))
        self.assertIn("xcodebuild_unavailable", primary["message"])

    def test_no_simulator_is_degraded_skip(self):
        # integration_build maps a missing sim to status="skipped"; we model the
        # xcodeproj_missing/sim skip reasons the same degraded way.
        self._patch_build(status="skipped", skip_reason="xcodeproj_missing")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertTrue(primary.get("skipped"))
        self.assertTrue(primary.get("degraded"))

    # ── pass ──
    def test_passed_xcresult_passes(self):
        self._patch_build(status="passed")
        self._patch_xcresult(_summary_json(result="Passed", total=3, passed=3, failed=0))
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertTrue(primary["passed"])
        self.assertFalse(primary.get("skipped", False))
        self.assertFalse(primary.get("degraded", False))
        self.assertIn("3", primary["message"])

    # ── hard fail: tests failed ──
    def test_failed_xcresult_hard_fails(self):
        self._patch_build(status="passed")  # xcodebuild ran; tests inside failed
        self._patch_xcresult(_summary_json(result="Failed", total=3, passed=2, failed=1))
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertFalse(primary["passed"])
        self.assertFalse(primary.get("skipped", False))   # NOT a skip — a real failure
        self.assertFalse(primary.get("degraded", False))  # hard fail, not degraded
        self.assertIn("failed", primary["message"].lower())

    # ── hard fail: integration_build itself reported test command failure ──
    def test_build_failed_status_hard_fails(self):
        self._patch_build(status="failed")
        # summary unparseable / absent → still a hard fail (build/test command failed)
        self._patch_xcresult("not json")
        results = fn.check_logic_tests_pass(self.proj, "Demo", {})
        primary = results[0]
        self.assertFalse(primary["passed"])
        self.assertFalse(primary.get("degraded", False))

    # ── completeness sub-check: P0 logic acceptance with NO matching test → WARNING (non-blocking) ──
    def test_missing_p0_test_is_nonblocking_warning(self):
        self._patch_build(status="passed")
        # authored tests do NOT include a test named after acceptance "addItem_increasesCount"
        self._patch_xcresult(
            _summary_json(result="Passed", total=1, passed=1, failed=0),
            _tests_json("appLaunches()"),
        )
        feature = fn._FeatureLite(
            feature_id="F1", priority="P0",
            logic_acceptance_ids=["addItem_increasesCount"],
        )
        results = fn.check_logic_tests_pass(
            self.proj, "Demo", {}, _features_override=[feature],
        )
        primary = results[0]
        completeness = next(r for r in results if r["check"] == "logic_test_completeness")
        # Primary still GREEN (build+tests passed); completeness is a warning, not a fail.
        self.assertTrue(primary["passed"])
        self.assertTrue(completeness["passed"])        # non-blocking
        self.assertFalse(completeness.get("degraded", False))
        self.assertIn("WARNING", completeness["message"])
        self.assertIn("addItem_increasesCount", completeness["message"])

    def test_matching_p0_test_completeness_clean(self):
        self._patch_build(status="passed")
        self._patch_xcresult(
            _summary_json(result="Passed", total=1, passed=1, failed=0),
            _tests_json("addItem_increasesCount()"),
        )
        feature = fn._FeatureLite(
            feature_id="F1", priority="P0",
            logic_acceptance_ids=["addItem_increasesCount"],
        )
        results = fn.check_logic_tests_pass(
            self.proj, "Demo", {}, _features_override=[feature],
        )
        completeness = next(r for r in results if r["check"] == "logic_test_completeness")
        self.assertTrue(completeness["passed"])
        self.assertNotIn("WARNING", completeness["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] Run it — expect FAIL (module missing):
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_functional_logic -v
```
Expected output: `ModuleNotFoundError: No module named 'functional'` (or `AttributeError: module 'functional' has no attribute 'check_logic_tests_pass'`).

---

**Step 1.2 — Extend `_ok` in `_helpers.py` per LOCKED CONTRACT (skip if already applied by shared work-stream).**

Replace the existing `_ok` in `/Users/louis/Code/Autobot/scripts/gate_checks/_helpers.py`:

```python
def _ok(check: str, passed: bool, message: str, *, skipped: bool = False, degraded: bool = False) -> dict[str, Any]:
    r: dict[str, Any] = {"check": check, "passed": passed, "message": message}
    if skipped:
        r["skipped"] = True
    if degraded:
        r["degraded"] = True
    return r
```

(Existing callers pass no `degraded` → behavior unchanged.)

---

**Step 1.3 — Create `scripts/gate_checks/functional.py` (FULL code).**

Grounded facts used here:
- `integration_build(project_root, app_name, *, attempt=1, test=True)` returns `{"status": "passed"|"failed"|"skipped", "resultBundlePath": <str when not skipped>, "skipReason": <str when skipped>, ...}` (see `scripts/xcodebuild_runner.py:217-254`). A missing simulator/xcodebuild surfaces as `status="skipped"` with `skipReason` in `{"xcodebuild_unavailable","xcodeproj_missing"}`.
- `xcrun xcresulttool get test-results summary --path <bundle> --compact` emits JSON `{"result": "Passed"|"Failed"|"Skipped"|..., "totalTestCount": int, "passedTests": int, "failedTests": int, ...}` (verified against `--schema`, schema 0.1.0, xcresulttool 24757).
- `xcrun xcresulttool get test-results tests --path <bundle> --compact` emits `{"testNodes": [recursive {nodeType,name,children,result}]}`; leaf `nodeType == "Test Case"` carries the authored test function name (e.g. `addItem_increasesCount()`).
- `load_feature_spec(project_root) -> list[FeatureSpec] | None` and the `Acceptance`/`FeatureSpec` shapes are LOCKED in `intent_spec.py` (added by the spec work-stream): `FeatureSpec.priority in {"P0","P1","P2"}`, `FeatureSpec.acceptance: tuple[Acceptance,...]`, `Acceptance.id: str`, `Acceptance.kind: str ("flow"|"logic")`.

Write `/Users/louis/Code/Autobot/scripts/gate_checks/functional.py`:

```python
"""Functional verification gate checks (Gate 5→6).

check_logic_tests_pass     — run authored Swift Testing unit tests via
                             xcodebuild test, parse the .xcresult.
check_functional_flows_pass — drive P0/P1 acceptance flows on a simulator via
                             AXe (implemented by the flow_runner work-stream).

All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
Results built with _ok(...). Degradable resources (no xcodebuild / no simulator)
return a DEGRADED skip: _ok(label, False, reason, skipped=True, degraded=True).
A check that ran and truly failed returns a hard fail: _ok(label, False, reason).
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from xcodebuild_runner import integration_build  # noqa: E402

from ._helpers import _ok  # noqa: E402


# ── Lightweight feature view so tests can inject without a full FeatureSpec ──
@dataclass
class _FeatureLite:
    feature_id: str
    priority: str
    logic_acceptance_ids: list[str] = field(default_factory=list)


def _run_xcresulttool(cmd: list[str], *, timeout: int = 120) -> tuple[int, str]:
    """Run an `xcrun xcresulttool ...` argv. Returns (rc, stdout).

    Isolated for monkeypatching in tests (no real .xcresult needed).
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""


def _xcresult_summary(bundle: Path) -> dict | None:
    """Parse `xcresulttool get test-results summary`. None on any parse error."""
    rc, out = _run_xcresulttool([
        "xcrun", "xcresulttool", "get", "test-results", "summary",
        "--path", str(bundle), "--compact",
    ])
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _authored_test_names(bundle: Path) -> set[str]:
    """Collect authored test-case names (function identifiers) from the .xcresult.

    Returns names both with and without the trailing "()" so an acceptance id
    matches whether the test is `func foo()` (Swift Testing) or a suite method.
    Empty set on any parse failure (completeness check then degrades to noise-free
    'could not introspect' note, never a hard fail).
    """
    rc, out = _run_xcresulttool([
        "xcrun", "xcresulttool", "get", "test-results", "tests",
        "--path", str(bundle), "--compact",
    ])
    if rc != 0 or not out.strip():
        return set()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return set()

    names: set[str] = set()

    def walk(node: dict) -> None:
        if node.get("nodeType") == "Test Case":
            raw = str(node.get("name") or "")
            names.add(raw)
            names.add(raw.rstrip("()"))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    for top in data.get("testNodes") or []:
        if isinstance(top, dict):
            walk(top)
    return names


def _p0_logic_features(project_dir: Path) -> list[_FeatureLite]:
    """Read the feature-spec and project P0 logic-acceptance ids.

    Returns [] when no feature-spec is present (completeness check then no-ops).
    """
    try:
        from intent_spec import load_feature_spec
    except ImportError:
        return []
    features = load_feature_spec(project_dir)
    if not features:
        return []
    out: list[_FeatureLite] = []
    for f in features:
        if getattr(f, "priority", "") != "P0":
            continue
        logic_ids = [
            a.id for a in getattr(f, "acceptance", ())
            if getattr(a, "kind", "") == "logic"
        ]
        if logic_ids:
            out.append(_FeatureLite(
                feature_id=getattr(f, "id", "?"),
                priority="P0",
                logic_acceptance_ids=logic_ids,
            ))
    return out


def _completeness_subcheck(
    project_dir: Path, bundle: Path | None, features: list[_FeatureLite],
) -> dict:
    """NON-blocking warning when a P0 logic acceptance has no matching test.

    Always passed=True (never blocks, never degraded). When a P0 logic
    acceptance id has no correspondingly-named authored test, the message is
    prefixed WARNING so run-summary surfaces it.
    """
    if not features:
        return _ok("logic_test_completeness", True, "no P0 logic acceptances declared")
    authored = _authored_test_names(bundle) if bundle is not None else set()
    missing: list[str] = []
    for f in features:
        for acc_id in f.logic_acceptance_ids:
            if acc_id not in authored and f"{acc_id}()" not in authored:
                missing.append(f"{f.feature_id}:{acc_id}")
    if missing:
        return _ok(
            "logic_test_completeness", True,
            f"WARNING: {len(missing)} P0 logic acceptance(s) without a named test: {missing}",
        )
    return _ok("logic_test_completeness", True,
               f"all {sum(len(f.logic_acceptance_ids) for f in features)} P0 logic acceptance(s) have a named test")


def check_logic_tests_pass(
    project_dir: Path, app: str, state: dict,
    *, _features_override: list[_FeatureLite] | None = None,
) -> list[dict]:
    """Gate 5→6 — run authored unit tests (xcodebuild test) and parse the result.

    Verdict:
      - integration_build status == "skipped"  → DEGRADED skip (no xcodebuild/sim)
      - .xcresult summary result == "Passed"    → PASS
      - anything else (Failed / unparseable / build status failed) → HARD FAIL
    Plus a non-blocking completeness WARNING sub-check.
    """
    build = integration_build(project_dir, app, test=True)
    status = build.get("status")

    if status == "skipped":
        reason = build.get("skipReason", "unknown")
        return [_ok(
            "logic_tests_pass", False,
            f"skipped (degraded): {reason} — cannot run authored unit tests here",
            skipped=True, degraded=True,
        )]

    bundle_str = build.get("resultBundlePath")
    bundle = Path(bundle_str) if bundle_str else None

    features = (
        _features_override if _features_override is not None
        else _p0_logic_features(project_dir)
    )

    summary = _xcresult_summary(bundle) if bundle is not None else None

    if status == "passed" and summary is not None and summary.get("result") == "Passed":
        total = summary.get("totalTestCount", 0)
        passed = summary.get("passedTests", 0)
        primary = _ok(
            "logic_tests_pass", True,
            f"xcodebuild test passed: {passed}/{total} authored test(s) green",
        )
        return [primary, _completeness_subcheck(project_dir, bundle, features)]

    # Tests ran but failed, or summary unparseable, or build/test command failed.
    if summary is not None:
        failed = summary.get("failedTests", "?")
        total = summary.get("totalTestCount", "?")
        msg = (
            f"authored unit tests failed: {failed}/{total} test(s) failed "
            f"(xcresult result={summary.get('result')}) — bundle: {bundle}"
        )
    else:
        msg = (
            f"authored unit tests failed (build status={status}; "
            f"could not parse .xcresult at {bundle})"
        )
    primary = _ok("logic_tests_pass", False, msg)
    return [primary, _completeness_subcheck(project_dir, bundle, features)]
```

---

**Step 1.4 — Register in `gate_runner.py` `GATE_CHECKS`.**

Add the import block after the `from gate_checks.deploy import (...)` block in `/Users/louis/Code/Autobot/scripts/gate_runner.py`:

```python
from gate_checks.functional import (  # noqa: E402,F401
    check_logic_tests_pass,
    check_functional_flows_pass,
)
```

> The `check_functional_flows_pass` import is the LOCKED contract symbol owned by the flow_runner work-stream; it lives in the same module. If that work-stream has not landed yet, import ONLY `check_logic_tests_pass` to keep the import resolvable, and add `check_functional_flows_pass` to the import when it lands. Do not invent a stub here.

Add to the `GATE_CHECKS` dict, in the `# Gate 5→6` section:

```python
    "logic_tests_pass": check_logic_tests_pass,
    "functional_flows_pass": check_functional_flows_pass,
```

---

**Step 1.5 — Add to `spec/pipeline.json` gate `5->6` checks.**

Append these two descriptors to the `gates["5->6"]["checks"]` array in `/Users/louis/Code/Autobot/spec/pipeline.json` (after the existing `metadata_readiness` entry, before `quality_engineer_consumed_learnings`):

```json
    {
      "type": "procedural",
      "name": "logic_tests_pass",
      "label": "logic_tests_pass"
    },
    {
      "type": "procedural",
      "name": "functional_flows_pass",
      "label": "functional_flows_pass"
    }
```

Use the exact JSON edit (anchor on the existing metadata_readiness object):

```
old:
    {
      "type": "procedural",
      "name": "metadata_readiness",
      "label": "metadata_readiness"
    },
    {
      "type": "state_field_contains",
      "label": "quality_engineer_consumed_learnings",

new:
    {
      "type": "procedural",
      "name": "metadata_readiness",
      "label": "metadata_readiness"
    },
    {
      "type": "procedural",
      "name": "logic_tests_pass",
      "label": "logic_tests_pass"
    },
    {
      "type": "procedural",
      "name": "functional_flows_pass",
      "label": "functional_flows_pass"
    },
    {
      "type": "state_field_contains",
      "label": "quality_engineer_consumed_learnings",
```

> If the spec-drift CI check (`.github` push checks) enforces "every procedural name has an impl", `functional_flows_pass` must be registered (Step 1.4). Coordinate landing order with the flow_runner work-stream so the drift check stays green.

---

**Step 1.6 — Run tests, expect PASS:**
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_functional_logic -v
```
Expected: `Ran 7 tests` ... `OK`.

Also verify `list-checks` sees the new procedural impls (and emits no "unimplemented" warning for `logic_tests_pass`):
```bash
cd /Users/louis/Code/Autobot && python3 scripts/gate_runner.py list-checks --gate "5->6"
```
Expected: a line `✓ logic_tests_pass` (and `✓ functional_flows_pass` once that work-stream lands).

Run the full suite to confirm no regression from the `_ok` extension:
```bash
cd /Users/louis/Code/Autobot && bash tests/run_tests.sh 2>&1 | tail -5
```
Expected: trailing `OK`.

- [ ] Commit:
```bash
cd /Users/louis/Code/Autobot && git add scripts/gate_checks/functional.py scripts/gate_checks/_helpers.py scripts/gate_runner.py spec/pipeline.json tests/test_functional_logic.py && git commit -m "feat(gate-5->6): logic_tests_pass — run authored unit tests, parse .xcresult, degraded-skip when no xcodebuild/sim"
```

---

### Task 2: Scaffold — verify + harden the unit-test target + scheme test action (so `xcodebuild test` works)

**Goal**: Guarantee the scaffold produces a `<App>Tests` unit-test target AND a scheme `TestAction` that runs it, so `integration_build(test=True)` (Task 1) can execute authored tests. The current scaffold (`generate-pbxproj.py`, `create-xcode-project.sh`, scheme XML) ALREADY emits all three. This task ADDS a guard test that fails loudly if any of those pieces regress, and makes one grounded hardening fix: the xcodegen-generated scheme does not currently mark the test target as a Testable, so add an explicit `scheme:` block to `project.yml` to match the pbxproj fallback's `TestAction`.

**Files**
- EDIT: `/Users/louis/Code/Autobot/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh` (add `schemes:` to xcodegen `project.yml`)
- NEW test: `/Users/louis/Code/Autobot/tests/test_scaffold_test_target.py`

> Grounding (do NOT re-add what already exists):
> - `generate-pbxproj.py` ALREADY emits: `TEST_TARGET` (`productType = "com.apple.product-type.bundle.unit-test"`, name `<App>Tests`, lines 205-224), its `TEST_CONFIG_LIST` + Debug/Release configs with `TEST_HOST`/`BUNDLE_LOADER` (lines 411-442), `TEST_FOLDER_REF` synchronized group (lines 125-129), a `PBXTargetDependency` (lines 288-296), AND a scheme `<TestAction>` with a `<TestableReference>` pointing at `<App>Tests.xctest` (lines 529-536). The pbxproj fallback is COMPLETE — do not modify it.
> - `create-xcode-project.sh` ALREADY: makes `${TESTS_DIR}` (`<App>Tests/`, line 153), writes a starter `<App>Tests.swift` using Swift Testing (`import Testing` + `@Suite`, lines 329-342), and the xcodegen `project.yml` ALREADY declares the `${APP_NAME}Tests` target (`type: bundle.unit-test`, lines 456-463).
> - GAP: the xcodegen `project.yml` declares the test TARGET but no `schemes:` block, so xcodegen auto-generates a scheme whose `TestAction` may not include the test target as a testable (xcodegen only auto-attaches test targets to a scheme when `scheme:` config or `gatherCoverageData`/target-test links are present). The pbxproj fallback hand-writes the TestAction; the xcodegen path should match it explicitly.

---

**Step 2.1 — Write the failing guard test FIRST.**

This test runs the generator/scaffold logic without xcodebuild: it (a) calls `generate-pbxproj.py` and asserts the unit-test target + scheme TestAction exist, and (b) asserts the xcodegen `project.yml` emitted by `create-xcode-project.sh` contains a `schemes:` block wiring the test target. It uses `subprocess` against the real scripts (mirrors how `conftest.run_pipeline` shells out).

Create `/Users/louis/Code/Autobot/tests/test_scaffold_test_target.py`:

```python
"""Guard tests: the scaffold MUST emit a unit-test target + a scheme TestAction
so `xcodebuild test` (and thus check_logic_tests_pass) can run authored tests.

Pure generation tests — no xcodebuild/simulator. We invoke generate-pbxproj.py
directly and inspect the xcodegen project.yml that create-xcode-project.sh writes.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCAFFOLD = PLUGIN_DIR / "skills" / "autobot-ios-scaffold" / "scripts"
GEN_PBXPROJ = SCAFFOLD / "generate-pbxproj.py"
CREATE_SH = SCAFFOLD / "create-xcode-project.sh"


class TestPbxprojTestTarget(unittest.TestCase):
    def test_pbxproj_has_unit_test_target_and_test_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources = Path(tmp) / "Demo"
            sources.mkdir(parents=True)
            proc = subprocess.run(
                ["python3", str(GEN_PBXPROJ),
                 "--name", "Demo", "--bundle-id", "com.axi.demo",
                 "--sources-dir", str(sources)],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            pbx = (Path(tmp) / "Demo.xcodeproj" / "project.pbxproj").read_text()
            # Unit-test target present
            self.assertIn("com.apple.product-type.bundle.unit-test", pbx)
            self.assertIn("DemoTests", pbx)
            self.assertIn("TEST_HOST", pbx)
            # Scheme test action present and references the test bundle
            scheme = (Path(tmp) / "Demo.xcodeproj" / "xcshareddata"
                      / "xcschemes" / "Demo.xcscheme").read_text()
            self.assertIn("<TestAction", scheme)
            self.assertIn("DemoTests.xctest", scheme)
            self.assertIn("<TestableReference", scheme)


class TestXcodegenProjectYmlScheme(unittest.TestCase):
    def test_project_yml_wires_test_scheme(self):
        # Force the xcodegen branch by faking an xcodegen on PATH that no-ops,
        # so create-xcode-project.sh writes project.yml then "generates".
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            (fake_bin / "xcodegen").write_text("#!/bin/bash\nexit 0\n")
            (fake_bin / "xcodegen").chmod(0o755)
            env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": tmp}
            proj = Path(tmp) / "out"
            proc = subprocess.run(
                ["bash", str(CREATE_SH),
                 "--name", "Demo", "--bundle-id", "com.axi.demo",
                 "--project-dir", str(proj)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            yml = (proj / "project.yml").read_text()
            self.assertIn("DemoTests", yml)
            self.assertIn("bundle.unit-test", yml)
            # GAP being closed: an explicit scheme wiring the test target.
            self.assertIn("schemes:", yml)
            self.assertIn("Demo:", yml.split("schemes:", 1)[1])
            self.assertIn("test:", yml.split("schemes:", 1)[1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] Run it — `TestPbxprojTestTarget` should PASS (pbxproj already complete), `TestXcodegenProjectYmlScheme` should FAIL (no `schemes:` block yet):
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_scaffold_test_target -v
```
Expected: `test_pbxproj_has_unit_test_target_and_test_action ... ok`, `test_project_yml_wires_test_scheme ... FAIL` with `AssertionError: 'schemes:' not found`.

---

**Step 2.2 — Add the `schemes:` block to the xcodegen `project.yml` (minimal fix).**

In `/Users/louis/Code/Autobot/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh`, the `project.yml` heredoc currently ends its `targets:` section with the `${APP_NAME}Tests` block then closes with `YAML_EOF`. Add a `schemes:` block immediately before `YAML_EOF`.

Edit — anchor on the existing test-target tail of the heredoc:

```
old:
  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
    dependencies:
      - target: ${APP_NAME}
YAML_EOF

new:
  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
    dependencies:
      - target: ${APP_NAME}

schemes:
  ${APP_NAME}:
    build:
      targets:
        ${APP_NAME}: all
        ${APP_NAME}Tests: [test]
    test:
      targets:
        - ${APP_NAME}Tests
      gatherCoverageData: false
    run:
      config: Debug
    archive:
      config: Release
YAML_EOF
```

This makes the xcodegen-generated `<App>.xcscheme` carry a `TestAction` with `<App>Tests` as a testable — matching the hand-written pbxproj fallback scheme so `xcodebuild test -scheme <App>` runs the authored tests under both generation paths.

---

**Step 2.3 — Run tests, expect PASS:**
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_scaffold_test_target -v
```
Expected: both tests `ok`, `Ran 2 tests` ... `OK`.

- [ ] Commit:
```bash
cd /Users/louis/Code/Autobot && git add skills/autobot-ios-scaffold/scripts/create-xcode-project.sh tests/test_scaffold_test_target.py && git commit -m "fix(scaffold): wire xcodegen test scheme + guard test for unit-test target/TestAction"
```

---

### Task 3: Update `autobot-integration-build/SKILL.md` Step 5 — authored tests must compile AND pass (named after acceptance ids)

**Goal**: Step 5 currently only shows a placeholder test and says "write basic tests". Make it require: (a) tests live in `<App>Tests/`, (b) tests COMPILE and PASS via `xcodebuild test`, (c) each P0 `logic` acceptance from `.autobot/feature-spec.json` has a test function NAMED after the acceptance id (so `check_logic_tests_pass`'s completeness sub-check is satisfied), and (d) the Gate 5→6 pass list adds "authored unit tests pass".

**Files**
- EDIT: `/Users/louis/Code/Autobot/skills/autobot-integration-build/SKILL.md`

> Grounding: SKILL.md Step 5 is lines 280-296. The Gate 5→6 pass-condition block is lines 347-373. `check_logic_tests_pass` (Task 1) matches an acceptance id `addItem_increasesCount` against authored test names `addItem_increasesCount` or `addItem_increasesCount()` — so the SKILL must instruct the agent to name `@Test func <acceptanceId>()`.

---

**Step 3.1 — Rewrite Step 5 (lines 280-296).**

Edit — replace the existing Step 5 body:

```
old:
## Step 5: Test 작성

`<AppName>Tests/` 디렉토리에 기본 테스트를 작성한다.

```swift
import Testing
@testable import AppName

@Suite("Item Model Tests")
struct ItemTests {
    @Test func createItem() {
        let item = Item(name: "Test")
        #expect(item.name == "Test")
        #expect(item.createdAt <= .now)
    }
}
```

최소 기준:
- 각 Data Model에 대해 생성 테스트 1개
- Repository에 대해 기본 CRUD 테스트 (가능하면)

new:
## Step 5: Authored 테스트 작성 (컴파일 + 통과 필수)

`<AppName>Tests/` 디렉토리에 Swift Testing 테스트를 작성한다. 이 테스트는 **반드시 컴파일되고 통과해야 한다** — Gate 5→6 의 `logic_tests_pass` 체크가 `xcodebuild test` 를 실행해 `.xcresult` 를 파싱하므로, 빌드만 성공하고 테스트가 깨지면 Gate 5→6 는 hard-fail 한다.

### 5a. P0 logic acceptance 당 1개 테스트 (이름 규칙 필수)

`.autobot/feature-spec.json` 의 각 P0 feature 에서 `kind == "logic"` 인 acceptance 마다, **acceptance id 와 동일한 이름의 `@Test func`** 를 작성한다. `check_logic_tests_pass` 의 completeness 서브체크가 authored 테스트 이름을 acceptance id 와 대조한다 (`addItem_increasesCount` ↔ `func addItem_increasesCount()`). 이름이 일치하지 않으면 비차단 WARNING 이 run-summary 에 남는다.

```swift
import Testing
@testable import <AppName>

@Suite("Logic acceptances")
struct LogicAcceptanceTests {
    // acceptance id "addItem_increasesCount" (P0, kind=logic) 에 대응
    @Test func addItem_increasesCount() throws {
        let store = ItemStore.inMemory()   // ServiceStubs / in-memory ModelContainer 사용
        let before = store.items.count
        store.add(Item(name: "X"))
        #expect(store.items.count == before + 1)   // postcondition: count_increased
    }
}
```

규칙:
- 테스트는 acceptance 의 `postcondition.kind` 를 실제로 검증한다 (`count_increased`, `value_persisted_after_relaunch` 등) — 단순 `#expect(true)` 금지.
- `flow` kind acceptance 는 여기서 다루지 않는다 (UI 구동은 Gate 5→6 의 `functional_flows_pass` 가 AXe 로 검증).
- 각 Data Model 생성 테스트 1개 + 가능하면 Repository CRUD 테스트도 추가.

### 5b. 컴파일 + 통과 확인

```bash
# Gate 와 동일 경로: integration_build(test=True) 가 호출하는 명령과 같다.
xcodebuild -project *.xcodeproj -scheme <AppName> \
  -destination "$SIM_DEST" \
  -resultBundlePath /tmp/Tests.xcresult \
  test 2>&1 | tail -30

# .xcresult 요약 파싱 (Gate 가 쓰는 것과 동일)
xcrun xcresulttool get test-results summary --path /tmp/Tests.xcresult --compact \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['result'], d['passedTests'],'/',d['totalTestCount'])"
# Expected: Passed N / N
```

테스트가 컴파일 실패하거나 1개라도 실패하면 Step 3 (Build-Fix Loop) 로 돌아가 수정한 뒤 재실행한다. `xcodebuild`/시뮬레이터가 없는 환경에서는 Gate 가 degraded-skip 으로 처리하므로 로컬 통과 여부를 기록만 한다.
```

---

**Step 3.2 — Add the authored-tests condition to the Gate 5→6 pass list (lines 347-373).**

Edit — insert a new numbered condition into the pass-condition fenced block. Anchor on the build-success line:

```
old:
# 1. 빌드 성공
xcodebuild build ... 2>&1 | tail -1 | grep -q "BUILD SUCCEEDED"

new:
# 1. 빌드 성공
xcodebuild build ... 2>&1 | tail -1 | grep -q "BUILD SUCCEEDED"

# 1b. Authored 테스트 컴파일 + 통과 (Gate logic_tests_pass)
#     xcodebuild test 가 .xcresult 를 만들고, Gate 가 summary 를 파싱한다.
#     xcodebuild/sim 부재 시 degraded-skip (DEGRADED verdict, hard-block 아님).
xcodebuild test ... -resultBundlePath /tmp/Tests.xcresult 2>&1 | tail -1
xcrun xcresulttool get test-results summary --path /tmp/Tests.xcresult --compact \
  | grep -q '"result":"Passed"'
```

Also append a line to the prose list of Gate 5→6 conditions (after the build-success bullet near line 349) noting that authored unit tests must pass:

```
old:
빌드 성공만으로는 부족하다. 다음 모두 충족해야 한다:

new:
빌드 성공만으로는 부족하다. 다음 모두 충족해야 한다 (authored 테스트 컴파일+통과 포함 — Gate `logic_tests_pass`):
```

---

**Step 3.3 — Verify the SKILL doc is internally consistent (no code to run; doc edit).**

Confirm the edited Step 5 references the LOCKED contract names exactly (`logic_tests_pass`, `functional_flows_pass`, `feature-spec.json`, postcondition kinds):
```bash
cd /Users/louis/Code/Autobot && grep -n "logic_tests_pass\|functional_flows_pass\|feature-spec.json\|count_increased" skills/autobot-integration-build/SKILL.md
```
Expected: matches in the rewritten Step 5 and Gate 5→6 block.

- [ ] Commit:
```bash
cd /Users/louis/Code/Autobot && git add skills/autobot-integration-build/SKILL.md && git commit -m "docs(integration-build): Step 5 — authored tests must compile+pass, named after P0 logic acceptance ids"
```

---

## WS4 — AXe flow runner + functional_flows_pass + axe preflight

## Work-stream: AXe-driven flow runner + functional_flows_pass + axe preflight

### Cross-stream dependencies (consumed, NOT authored here)
- `intent_spec.load_feature_spec(project_root) -> list[FeatureSpec] | None` and the `FeatureSpec`/`Acceptance`/`Postcondition` dataclasses are authored by the intent-spec work-stream. This work-stream **imports** them but does NOT define them. Tests in this stream construct `FeatureSpec` objects directly via the LOCKED dataclass signatures (no JSON file needed) so they do not block on the other stream's file format.
- `_ok(..., degraded=...)` extension and the three-valued `run_gate` verdict are authored by the gate-runner work-stream. This stream's `functional.py` **uses** `_ok(..., skipped=True, degraded=True)` and assumes that signature is live. Task 2 tests assert on the raw dict keys (`passed`, `skipped`, `degraded`) so they pass regardless of whether the `_ok` extension has landed yet (we set the keys directly through `_ok`; if `_ok` does not yet accept `degraded`, Task 2's import-time use will fail loudly — that is the intended ordering signal).

LOCKED names used verbatim: `FeatureSpec`, `Acceptance`, `Postcondition`, `Step` (plain dict `{"action","anchor"}`), `POSTCONDITION_KINDS`, `flow_runner.run_flows(project_dir, app, features)`, `check_functional_flows_pass(project_dir, app, state)`, `check_logic_tests_pass` (authored by functional work-stream sibling — registered here too), `_ok`.

---

### Task 1: scripts/flow_runner.py — AXe-driven semantic-wait flow runner

**Files**
- CREATE `/Users/louis/Code/Autobot/scripts/flow_runner.py`
- CREATE `/Users/louis/Code/Autobot/tests/test_flow_runner.py`

**TDD steps**

- [ ] 1.1 Write the failing test file FIRST. It exercises three pure-ish surfaces against FIXTURE describe-ui JSON, with `_run` and `shutil.which` monkeypatched so NO real simulator/axe is touched:
  - `_anchor_ready(elements, anchor, screen)` — element present AND enabled AND frame inside screen bounds.
  - `_evaluate_postcondition(kind, params, before_elements, after_elements)` — count_increased pass/fail, navigated_to pass/fail.
  - `run_flows(...)` returns `status="skipped"` + `degraded=True` when `axe` binary is absent (mock `shutil.which` -> None).
  - `run_flows(...)` returns `status="skipped"` + `degraded=True` when no sim UDID resolvable (mock `which` present, but `_pick_udid` -> None).

```python
# /Users/louis/Code/Autobot/tests/test_flow_runner.py
"""Tests for scripts/flow_runner.py — the AXe-driven functional flow runner.

We never touch a real simulator or the axe binary here: `_run` and
`shutil.which` are monkeypatched, and describe-ui responses are fed from
FIXTURE JSON arrays so the postcondition evaluation logic is exercised
deterministically.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import flow_runner  # noqa: E402
from intent_spec import Acceptance, FeatureSpec, Postcondition  # noqa: E402


SCREEN = {"x": 0, "y": 0, "width": 393, "height": 852}


def _el(identifier, *, label="", enabled=True, x=20, y=100, w=200, h=44, typ="Button"):
    return {
        "type": typ,
        "identifier": identifier,
        "label": label,
        "enabled": enabled,
        "frame": {"x": x, "y": y, "width": w, "height": h},
    }


class TestAnchorReady(unittest.TestCase):
    def test_present_enabled_in_bounds_is_ready(self):
        els = [_el("autobot.primaryCTA")]
        self.assertTrue(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_absent_is_not_ready(self):
        els = [_el("autobot.other")]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_disabled_is_not_ready(self):
        els = [_el("autobot.primaryCTA", enabled=False)]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))

    def test_offscreen_frame_is_not_ready(self):
        els = [_el("autobot.primaryCTA", x=5000, y=9000)]
        self.assertFalse(flow_runner._anchor_ready(els, "autobot.primaryCTA", SCREEN))


class TestEvaluatePostcondition(unittest.TestCase):
    def test_count_increased_pass(self):
        before = [_el("autobot.row", typ="Cell"), _el("autobot.row", typ="Cell")]
        after = before + [_el("autobot.row", typ="Cell")]
        ok, _ = flow_runner._evaluate_postcondition(
            "count_increased", {"anchor": "autobot.row"}, before, after
        )
        self.assertTrue(ok)

    def test_count_increased_fail_when_unchanged(self):
        before = [_el("autobot.row", typ="Cell")]
        after = [_el("autobot.row", typ="Cell")]
        ok, _ = flow_runner._evaluate_postcondition(
            "count_increased", {"anchor": "autobot.row"}, before, after
        )
        self.assertFalse(ok)

    def test_navigated_to_pass(self):
        before = [_el("autobot.home")]
        after = [_el("autobot.detail")]
        ok, _ = flow_runner._evaluate_postcondition(
            "navigated_to", {"anchor": "autobot.detail"}, before, after
        )
        self.assertTrue(ok)

    def test_navigated_to_fail_when_target_absent(self):
        before = [_el("autobot.home")]
        after = [_el("autobot.home")]
        ok, _ = flow_runner._evaluate_postcondition(
            "navigated_to", {"anchor": "autobot.detail"}, before, after
        )
        self.assertFalse(ok)


def _feature(priority="P0", post_kind="navigated_to", post_anchor="autobot.detail"):
    acc = Acceptance(
        id="acc1",
        kind="flow",
        steps=({"action": "tap", "anchor": "autobot.primaryCTA"},),
        postcondition=Postcondition(kind=post_kind, params={"anchor": post_anchor}),
    )
    return FeatureSpec(
        id="feat1",
        title="Open detail",
        priority=priority,
        screen="Home",
        anchor="autobot.primaryCTA",
        acceptance=(acc,),
    )


class TestRunFlowsDegradedPaths(unittest.TestCase):
    def test_axe_missing_is_skipped_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value=None):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature()])
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["skipReason"], "axe_unavailable")

    def test_sim_missing_is_skipped_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=(None, "no_ios_simulator_available")):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature()])
        self.assertEqual(result["status"], "skipped")
        self.assertTrue(result["degraded"])
        self.assertEqual(result["skipReason"], "no_ios_simulator_available")

    def test_empty_features_is_skipped_not_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = flow_runner.run_flows(Path(tmp), "Demo", [])
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(result.get("degraded", False))
        self.assertEqual(result["skipReason"], "no_features")


class TestRunFlowsHappyAndFail(unittest.TestCase):
    """Drive a full flow with describe-ui responses injected via a fake _run."""

    def _make_axe_driver(self, *, describe_sequence):
        """Return a fake _run that returns queued describe-ui payloads in order;
        `axe tap` and `simctl`/`boot`/`install`/`launch` all succeed silently."""
        seq = list(describe_sequence)

        def fake_run(cmd, *, timeout=flow_runner.DEFAULT_AXE_TIMEOUT):
            if "describe-ui" in cmd:
                payload = seq.pop(0) if seq else []
                return 0, json.dumps(payload), ""
            return 0, "", ""

        return fake_run

    def test_p0_flow_pass(self):
        cta = _el("autobot.primaryCTA")
        # describe-ui calls in order: wait-for-anchor, before-postcondition,
        # after-postcondition (target now visible).
        seq = [
            [cta],                       # _wait_for_anchor poll #1: ready
            [cta],                       # before snapshot
            [_el("autobot.detail")],     # after snapshot: navigated
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P0")])
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(len(result["results"]), 1)
        self.assertTrue(result["results"][0]["passed"])

    def test_p0_flow_fail_is_hard(self):
        cta = _el("autobot.primaryCTA")
        seq = [
            [cta],                       # wait: ready
            [cta],                       # before
            [cta],                       # after: NOT navigated (target absent)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P0")])
        self.assertEqual(result["status"], "failed", result)
        self.assertFalse(result["results"][0]["passed"])

    def test_p1_flow_fail_is_warning_not_failed(self):
        cta = _el("autobot.primaryCTA")
        seq = [[cta], [cta], [cta]]  # after: not navigated
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(flow_runner.shutil, "which", return_value="/usr/bin/axe"), \
                 mock.patch.object(flow_runner, "_pick_udid", return_value=("UDID-1", "test")), \
                 mock.patch.object(flow_runner, "_prepare_app", return_value=("com.x.Demo", None)), \
                 mock.patch.object(flow_runner, "_screen_bounds", return_value=SCREEN), \
                 mock.patch.object(flow_runner, "_run", side_effect=self._make_axe_driver(describe_sequence=seq)):
                result = flow_runner.run_flows(Path(tmp), "Demo", [_feature(priority="P1")])
        # P1 failure does NOT fail the suite (status passed), but the per-result
        # row records passed=False with a warning note.
        self.assertEqual(result["status"], "passed", result)
        self.assertFalse(result["results"][0]["passed"])
        self.assertIn("warning", result["results"][0]["message"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] 1.2 Run the test — expect FAIL (`ModuleNotFoundError: No module named 'flow_runner'`).
- [ ] 1.3 Create `scripts/flow_runner.py` with the COMPLETE implementation below.

```python
#!/usr/bin/env python3
"""AXe-driven functional flow runner (pillar 2b of the verification refit).

For each FeatureSpec acceptance of kind "flow", this module drives the booted
simulator through the declared steps using AXe (https://github.com/cameroncooke/AXe):

    axe describe-ui --udid U   -> JSON array of {type,identifier,label,frame,enabled}
    axe tap --id ANCHOR --udid U
    axe --version

The wait between steps is SEMANTIC, not a sleep: we poll `describe-ui` until the
target anchor is present AND enabled AND its frame lies inside the screen bounds,
bounded by DEFAULT_WAIT_TIMEOUT. After the tapping step(s) we re-query describe-ui
and assert the acceptance's postcondition (count_increased / navigated_to / etc.).

Simulator boot / install / launch is delegated to sim_runtime (the same helpers
runtime-smoke uses), so a flow run reuses the cached UDID and installed bundle.

Skip / degrade rules (LOCKED):
  - axe binary absent          -> status "skipped", degraded True
  - no resolvable sim UDID     -> status "skipped", degraded True
  - app artifact / bundle id missing or boot/install fails -> status "skipped", degraded True
  - no features at all         -> status "skipped", degraded False (benign N/A)
  - P0 acceptance fails        -> status "failed" (hard)
  - P1 acceptance fails        -> recorded as a per-result warning; suite stays "passed"
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sim_runtime  # noqa: E402

DEFAULT_AXE_TIMEOUT = 30          # seconds for a single axe subprocess
DEFAULT_WAIT_TIMEOUT = 8.0        # seconds to wait for an anchor to become ready
DEFAULT_WAIT_INTERVAL = 0.4       # poll interval for the semantic wait
DEFAULT_POSTCONDITION_SETTLE = 0.6  # brief settle so a SwiftUI transition can commit


def _axe_available() -> bool:
    if os.environ.get("AUTOBOT_DISABLE_AXE") == "1":
        return False
    return shutil.which("axe") is not None


def _run(cmd: list[str], *, timeout: int = DEFAULT_AXE_TIMEOUT) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", f"timeout after {timeout}s"


def _axe_version() -> str | None:
    rc, out, _ = _run(["axe", "--version"], timeout=10)
    if rc != 0:
        return None
    return out.strip() or None


def _pick_udid(project_root: Path) -> tuple[str | None, str]:
    """Resolve a booted/bootable sim UDID, reusing sim_runtime's picker."""
    return sim_runtime._pick_simulator_udid(project_root)


def _prepare_app(project_root: Path, app: str, udid: str) -> tuple[str | None, str | None]:
    """Boot + install + launch the freshly-built app, reusing sim_runtime.

    Returns (bundle_id, error). bundle_id is None when any prep step failed,
    in which case `error` carries a short reason.
    """
    app_path = sim_runtime._find_built_app(project_root, app)
    if app_path is None:
        return None, "app_artifact_missing"
    bundle_id = sim_runtime._resolve_bundle_id(project_root, app, app_path)
    if not bundle_id:
        return None, "bundle_id_unresolved"
    booted, detail = sim_runtime._boot(udid)
    if not booted:
        return None, f"boot_failed: {detail}"
    rc, _, install_err = sim_runtime._run(["xcrun", "simctl", "install", udid, str(app_path)])
    if rc != 0:
        return None, f"install_failed: {install_err.strip()[:120]}"
    rc, _, launch_err = sim_runtime._run(["xcrun", "simctl", "launch", udid, bundle_id])
    if rc != 0:
        return None, f"launch_failed: {launch_err.strip()[:120]}"
    return bundle_id, None


def _describe_ui(udid: str) -> list[dict]:
    rc, out, _ = _run(["axe", "describe-ui", "--udid", udid])
    if rc != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _screen_bounds(udid: str) -> dict:
    """Approximate screen bounds from the union of all element frames.

    AXe has no explicit screen-size query; the root frame is the largest
    element. We take the max extent across described elements and fall back to
    a generous default so the in-bounds test never rejects a real on-screen
    anchor.
    """
    els = _describe_ui(udid)
    max_w = 0.0
    max_h = 0.0
    for e in els:
        f = e.get("frame") or {}
        try:
            max_w = max(max_w, float(f.get("x", 0)) + float(f.get("width", 0)))
            max_h = max(max_h, float(f.get("y", 0)) + float(f.get("height", 0)))
        except (TypeError, ValueError):
            continue
    if max_w <= 0 or max_h <= 0:
        return {"x": 0, "y": 0, "width": 1366, "height": 1366}
    return {"x": 0, "y": 0, "width": max_w, "height": max_h}


def _frame_inside(frame: dict, screen: dict) -> bool:
    try:
        x = float(frame.get("x", 0))
        y = float(frame.get("y", 0))
        w = float(frame.get("width", 0))
        h = float(frame.get("height", 0))
    except (TypeError, ValueError):
        return False
    if w <= 0 or h <= 0:
        return False
    sx, sy = float(screen.get("x", 0)), float(screen.get("y", 0))
    sw, sh = float(screen.get("width", 0)), float(screen.get("height", 0))
    # Require the element's origin within bounds and at least partially visible.
    return (sx <= x <= sx + sw) and (sy <= y <= sy + sh)


def _anchor_ready(elements: list[dict], anchor: str, screen: dict) -> bool:
    for e in elements:
        if e.get("identifier") != anchor:
            continue
        if not e.get("enabled", True):
            return False
        return _frame_inside(e.get("frame") or {}, screen)
    return False


def _wait_for_anchor(udid: str, anchor: str, screen: dict,
                     *, timeout: float = DEFAULT_WAIT_TIMEOUT,
                     interval: float = DEFAULT_WAIT_INTERVAL) -> tuple[bool, list[dict]]:
    """Semantic wait: poll describe-ui until `anchor` is present+enabled+in-bounds.

    Returns (ready, last_elements). last_elements is the final describe-ui
    snapshot so the caller can reuse it as the postcondition "before" state.
    """
    deadline = time.monotonic() + timeout
    elements: list[dict] = []
    while True:
        elements = _describe_ui(udid)
        if _anchor_ready(elements, anchor, screen):
            return True, elements
        if time.monotonic() >= deadline:
            return False, elements
        time.sleep(interval)


def _count_anchor(elements: list[dict], anchor: str) -> int:
    return sum(1 for e in elements if e.get("identifier") == anchor)


def _present(elements: list[dict], anchor: str) -> bool:
    return any(e.get("identifier") == anchor for e in elements)


def _evaluate_postcondition(
    kind: str, params: dict, before: list[dict], after: list[dict],
) -> tuple[bool, str]:
    """Assert an acceptance postcondition by comparing before/after describe-ui.

    `params["anchor"]` names the element whose presence/count we inspect.
    Unknown kinds degrade to a navigated_to-style presence check on the anchor.
    """
    anchor = params.get("anchor") or ""

    if kind == "count_increased":
        b, a = _count_anchor(before, anchor), _count_anchor(after, anchor)
        return (a > b), f"count[{anchor}] {b}->{a}"

    if kind == "count_decreased":
        b, a = _count_anchor(before, anchor), _count_anchor(after, anchor)
        return (a < b), f"count[{anchor}] {b}->{a}"

    if kind == "navigated_to":
        ok = _present(after, anchor) and not _present(before, anchor) or (
            _present(after, anchor) and anchor != "" and not _anchor_ready(before, anchor, {"x": 0, "y": 0, "width": 1e9, "height": 1e9})
        )
        # Simpler robust rule: target visible after, regardless of before.
        ok = _present(after, anchor)
        return ok, f"navigated_to[{anchor}] present_after={ok}"

    if kind == "artifact_generated":
        ok = _present(after, anchor)
        return ok, f"artifact_generated[{anchor}] present_after={ok}"

    if kind == "setting_stored":
        ok = _present(after, anchor)
        return ok, f"setting_stored[{anchor}] present_after={ok}"

    if kind == "value_persisted_after_relaunch":
        # Handled out-of-band by the caller (needs a relaunch); here we only
        # compare snapshots: the anchor must still be present after relaunch.
        ok = _present(after, anchor)
        return ok, f"value_persisted_after_relaunch[{anchor}] present_after={ok}"

    # Unknown / anchor-only postcondition: presence check (lenient).
    ok = _present(after, anchor) if anchor else True
    return ok, f"{kind or 'unknown'}[{anchor}] present_after={ok}"


def _relaunch(udid: str, bundle_id: str) -> None:
    sim_runtime._run(["xcrun", "simctl", "terminate", udid, bundle_id])
    time.sleep(0.5)
    sim_runtime._run(["xcrun", "simctl", "launch", udid, bundle_id])


def _run_acceptance(
    udid: str, bundle_id: str, feature, acceptance,
) -> tuple[bool, str]:
    """Drive one acceptance: wait for entry anchor, run steps, assert postcondition.

    Returns (passed, message).
    """
    screen = _screen_bounds(udid)

    # 1) Wait for the feature's entry anchor (or the first step's anchor).
    entry_anchor = feature.anchor or (acceptance.steps[0]["anchor"] if acceptance.steps else "")
    ready, before = _wait_for_anchor(udid, entry_anchor, screen)
    if not ready:
        return False, f"entry anchor '{entry_anchor}' never ready within {DEFAULT_WAIT_TIMEOUT}s"

    # 2) Execute each step (cycle1 action == "tap").
    for step in acceptance.steps:
        step_anchor = step.get("anchor") or ""
        action = step.get("action") or "tap"
        ready, before = _wait_for_anchor(udid, step_anchor, screen)
        if not ready:
            return False, f"step anchor '{step_anchor}' never ready"
        if action == "tap":
            rc, _, err = _run(["axe", "tap", "--id", step_anchor, "--udid", udid])
            if rc != 0:
                return False, f"tap '{step_anchor}' failed: {err.strip()[:80]}"
        else:
            return False, f"unsupported step action '{action}'"

    # 3) Settle, then assert postcondition.
    post = acceptance.postcondition
    if post.kind == "value_persisted_after_relaunch":
        time.sleep(DEFAULT_POSTCONDITION_SETTLE)
        _relaunch(udid, bundle_id)
        ready, _ = _wait_for_anchor(
            udid, post.params.get("anchor", entry_anchor), screen,
        )
        after = _describe_ui(udid)
    else:
        time.sleep(DEFAULT_POSTCONDITION_SETTLE)
        after = _describe_ui(udid)

    ok, detail = _evaluate_postcondition(post.kind, post.params, before, after)
    return ok, detail


def run_flows(project_dir: Path, app: str, features: list) -> dict:
    """Drive every flow-kind acceptance of `features` through AXe on a sim.

    See module docstring for skip/degrade/pass/fail semantics. Return shape:
        {"status": "passed"|"failed"|"skipped",
         "skipReason"?: str, "degraded"?: bool,
         "results": [ {featureId, acceptanceId, priority, passed, message} ]}
    """
    flow_features = [f for f in (features or []) if any(a.kind == "flow" for a in f.acceptance)]
    if not flow_features:
        return {"status": "skipped", "skipReason": "no_features", "degraded": False, "results": []}

    if not _axe_available():
        return {"status": "skipped", "skipReason": "axe_unavailable", "degraded": True, "results": []}

    udid, udid_source = _pick_udid(project_dir)
    if not udid:
        return {"status": "skipped", "skipReason": udid_source, "degraded": True, "results": []}

    bundle_id, prep_err = _prepare_app(project_dir, app, udid)
    if bundle_id is None:
        return {"status": "skipped", "skipReason": prep_err or "app_prep_failed",
                "degraded": True, "results": []}

    results: list[dict] = []
    hard_failed = False

    for feature in flow_features:
        for acceptance in feature.acceptance:
            if acceptance.kind != "flow":
                continue
            # Reset to a clean launch before each acceptance so flows don't
            # contaminate each other's UI state.
            _relaunch(udid, bundle_id)
            passed, message = _run_acceptance(udid, bundle_id, feature, acceptance)
            if not passed and feature.priority == "P0":
                hard_failed = True
            row = {
                "featureId": feature.id,
                "acceptanceId": acceptance.id,
                "priority": feature.priority,
                "passed": passed,
                "message": message,
            }
            if not passed and feature.priority != "P0":
                row["message"] = f"WARNING ({feature.priority}): {message}"
            results.append(row)

    status = "failed" if hard_failed else "passed"
    return {"status": status, "udid": udid, "udidSource": udid_source,
            "bundleId": bundle_id, "results": results}


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--app-name", required=True)
    args = parser.parse_args()

    from intent_spec import load_feature_spec

    proj = Path(args.project_dir).resolve()
    features = load_feature_spec(proj) or []
    result = run_flows(proj, args.app_name, features)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("passed", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
```

Note on the `navigated_to` branch: the first `ok = ...` line is dead-on-arrival and intentionally overwritten by the robust `ok = _present(after, anchor)` on the next line — collapse to the single line below in the real file to avoid the lint warning:

```python
    if kind == "navigated_to":
        ok = _present(after, anchor)
        return ok, f"navigated_to[{anchor}] present_after={ok}"
```

- [ ] 1.4 Run the test — expect PASS (8 assertions across anchor-ready, postcondition, and degraded/happy/fail flow paths).
- [ ] 1.5 Commit.

**Commands & expected output**
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_flow_runner -v
# expected before impl: ERROR (No module named 'flow_runner')
# expected after impl:  OK  (12 tests)
```

---

### Task 2: scripts/gate_checks/functional.py — check_functional_flows_pass (+ register, + spec)

**Files**
- CREATE `/Users/louis/Code/Autobot/scripts/gate_checks/functional.py`
- EDIT  `/Users/louis/Code/Autobot/scripts/gate_runner.py` (import + register two names)
- EDIT  `/Users/louis/Code/Autobot/spec/pipeline.json` (add two procedural checks to gate 5->6)
- CREATE `/Users/louis/Code/Autobot/tests/test_functional_flows_gate.py`

**TDD steps**

- [ ] 2.1 Write the failing test FIRST. It monkeypatches `flow_runner.run_flows` and `intent_spec.load_feature_spec` and asserts the `_ok` dict shape (passed/skipped/degraded) for: passed, P0-hard-fail, degraded-skip, and no-feature-spec skip.

```python
# /Users/louis/Code/Autobot/tests/test_functional_flows_gate.py
"""Tests for check_functional_flows_pass — maps flow_runner.run_flows output
to the three-valued gate verdict via _ok(..., skipped=, degraded=)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks import functional  # noqa: E402


class TestCheckFunctionalFlowsPass(unittest.TestCase):
    def _run(self, *, features, run_result):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(functional, "load_feature_spec", return_value=features), \
                 mock.patch.object(functional, "run_flows", return_value=run_result):
                return functional.check_functional_flows_pass(Path(tmp), "Demo", {})

    def test_no_feature_spec_is_benign_skip(self):
        out = self._run(features=None, run_result=None)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertFalse(r.get("degraded", False))

    def test_passed_flows(self):
        out = self._run(
            features=[object()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P0",
                 "passed": True, "message": "navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertFalse(r.get("degraded", False))

    def test_p0_failure_is_hard_fail(self):
        out = self._run(
            features=[object()],
            run_result={"status": "failed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P0",
                 "passed": False, "message": "entry anchor never ready"}]},
        )
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))   # ran and truly failed = hard fail
        self.assertFalse(r.get("degraded", False))

    def test_degraded_skip_when_axe_missing(self):
        out = self._run(
            features=[object()],
            run_result={"status": "skipped", "skipReason": "axe_unavailable",
                        "degraded": True, "results": []},
        )
        r = out[0]
        self.assertFalse(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertTrue(r["degraded"])

    def test_benign_skip_when_no_flow_features(self):
        out = self._run(
            features=[object()],
            run_result={"status": "skipped", "skipReason": "no_features",
                        "degraded": False, "results": []},
        )
        r = out[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertFalse(r.get("degraded", False))

    def test_p1_warning_does_not_fail(self):
        out = self._run(
            features=[object()],
            run_result={"status": "passed", "results": [
                {"featureId": "f1", "acceptanceId": "a1", "priority": "P1",
                 "passed": False, "message": "WARNING (P1): not navigated"}]},
        )
        r = out[0]
        self.assertTrue(r["passed"])      # suite passed; P1 fail is a warning
        self.assertIn("warning", r["message"].lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] 2.2 Run the test — expect FAIL (`No module named 'gate_checks.functional'`).
- [ ] 2.3 Create `scripts/gate_checks/functional.py` with COMPLETE code. (Includes `check_logic_tests_pass` per LOCKED contract; its detailed `.xcresult` parsing is owned by the functional sibling stream — here it is implemented minimally via `xcodebuild_runner.integration_build(test=True)` so the registry/spec wiring is complete and importable.)

```python
"""Functional verification gate checks (Gate 5->6).

  check_logic_tests_pass     — runs the unit/integration test target via
                               xcodebuild_runner.integration_build(test=True);
                               degraded when xcodebuild / sim is unavailable.
  check_functional_flows_pass — drives declared FeatureSpec flows through AXe
                               via flow_runner.run_flows; P0 fail is hard, P1
                               fail is a warning, axe/sim missing is a degraded
                               skip, absent feature-spec is a benign skip.

All check signatures: (project_dir: Path, app: str, state: dict) -> list[dict].
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from intent_spec import load_feature_spec  # noqa: E402
from flow_runner import run_flows  # noqa: E402

from ._helpers import _ok  # noqa: E402


def check_logic_tests_pass(proj: Path, app: str, state: dict) -> list[dict]:
    """Run the app's logic/unit test target. Degrade (not fail) when the host
    has no xcodebuild or simulator, so CI/Linux unit runs of Autobot itself
    don't false-fail this behavioral gate."""
    import xcodebuild_runner

    result = xcodebuild_runner.integration_build(proj, app, test=True)
    status = result.get("status")
    if status == "skipped":
        return [_ok(
            "logic_tests_pass", False,
            f"logic tests not run: {result.get('skipReason', 'unavailable')}",
            skipped=True, degraded=True,
        )]
    if status == "passed":
        return [_ok("logic_tests_pass", True,
                    f"logic test target passed ({result.get('durationSeconds', 0)}s)")]
    return [_ok(
        "logic_tests_pass", False,
        f"logic tests failed (exit {result.get('exitCode')}): "
        f"{result.get('errorSignature', '')[:160]}",
    )]


def check_functional_flows_pass(proj: Path, app: str, state: dict) -> list[dict]:
    """Drive declared P0/P1 feature flows through AXe and assert postconditions.

    - feature-spec absent          -> benign skip (passed=True, skipped=True)
    - axe/sim missing / boot fails -> degraded skip (passed=False, skipped+degraded)
    - no flow-kind acceptances      -> benign skip
    - a P0 acceptance fails         -> hard fail (passed=False)
    - only P1 acceptances fail      -> suite passes, message carries the warning
    """
    features = load_feature_spec(proj)
    if not features:
        return [_ok(
            "functional_flows_pass", True,
            ".autobot/feature-spec.json absent — skipping (no declared flows)",
            skipped=True,
        )]

    result = run_flows(proj, app, features)
    status = result.get("status")
    results = result.get("results", [])

    if status == "skipped":
        reason = result.get("skipReason", "unavailable")
        if result.get("degraded"):
            return [_ok(
                "functional_flows_pass", False,
                f"functional flows not run: {reason}",
                skipped=True, degraded=True,
            )]
        # benign skip (e.g. no_features)
        return [_ok(
            "functional_flows_pass", True,
            f"functional flows skipped: {reason}",
            skipped=True,
        )]

    failed = [r for r in results if not r["passed"]]
    p0_failed = [r for r in failed if r.get("priority") == "P0"]
    p1_warned = [r for r in failed if r.get("priority") != "P0"]

    if status == "failed" or p0_failed:
        detail = "; ".join(f"{r['featureId']}/{r['acceptanceId']}: {r['message']}"
                           for r in p0_failed) or "P0 flow failed"
        return [_ok("functional_flows_pass", False, f"P0 flow failure: {detail}")]

    note = ""
    if p1_warned:
        note = " | warnings: " + "; ".join(
            f"{r['featureId']}/{r['acceptanceId']}" for r in p1_warned
        )
    passed_count = sum(1 for r in results if r["passed"])
    return [_ok(
        "functional_flows_pass", True,
        f"{passed_count}/{len(results)} flow acceptances passed{note}",
    )]
```

- [ ] 2.4 Register both checks in `gate_runner.py`. Add this import block after the `from gate_checks.deploy import (...)` block (around line 98):

```python
from gate_checks.functional import (  # noqa: E402,F401
    check_logic_tests_pass,
    check_functional_flows_pass
)
```

  And add to the `GATE_CHECKS` dict under the `# Gate 5→6` section (after the `"service_stubs_preserved": check_service_stubs_preserved,` line, before the `# Gate 6→7` comment):

```python
    "logic_tests_pass": check_logic_tests_pass,
    "functional_flows_pass": check_functional_flows_pass,
```

- [ ] 2.5 Add the two procedural checks to gate `5->6` in `spec/pipeline.json`. Insert into the `"checks"` array (place after the `runtime_smoke` procedural entry and before `visual_contract`):

```json
    {
      "type": "procedural",
      "name": "logic_tests_pass",
      "label": "logic_tests_pass"
    },
    {
      "type": "procedural",
      "name": "functional_flows_pass",
      "label": "functional_flows_pass"
    },
```

- [ ] 2.6 Run the gate test and the list-checks self-validation — expect PASS / no missing impls.

```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_functional_flows_gate -v
# expected before impl: ERROR (No module named 'gate_checks.functional')
# expected after impl:  OK  (6 tests)

cd /Users/louis/Code/Autobot && python3 scripts/gate_runner.py list-checks --gate "5->6"
# expected: every line prefixed "✓"; specifically
#   ✓ logic_tests_pass
#   ✓ functional_flows_pass
# (no "WARNING: N unimplemented procedural checks")

cd /Users/louis/Code/Autobot && python3 -c "import json; json.load(open('spec/pipeline.json')); print('spec parses')"
# expected: spec parses
```

- [ ] 2.7 Commit.

---

### Task 3: Phase-0 axe preflight in scripts/env_snapshot.py

**Files**
- EDIT  `/Users/louis/Code/Autobot/scripts/env_snapshot.py`
- CREATE `/Users/louis/Code/Autobot/tests/test_env_snapshot_axe.py`

**Goal**: `capture()` (hence `ensure()`) records `snapshot["environment"]["axe"]` (bool) and `snapshot["environment"]["axeVersion"]` (str | None). Existing `simulator` field is untouched, so sim_runtime's `(snap.get("simulator") or {}).get("udid")` cache reuse keeps working.

**TDD steps**

- [ ] 3.1 Write the failing test FIRST (mocks `shutil.which` + `_run` so no real axe needed).

```python
# /Users/louis/Code/Autobot/tests/test_env_snapshot_axe.py
"""Phase-0 axe preflight: env_snapshot.capture records axe availability+version."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

import env_snapshot  # noqa: E402


class TestAxePreflight(unittest.TestCase):
    def test_axe_present_records_true_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            def fake_which(name):
                return "/usr/local/bin/axe" if name == "axe" else None
            def fake_run(cmd, *, timeout=15):
                if cmd[:2] == ["axe", "--version"]:
                    return 0, "axe 1.2.3\n"
                return 127, ""
            with mock.patch.object(env_snapshot.shutil, "which", side_effect=fake_which), \
                 mock.patch.object(env_snapshot, "_run", side_effect=fake_run):
                snap = env_snapshot.capture(proj)
        self.assertIn("environment", snap)
        self.assertTrue(snap["environment"]["axe"])
        self.assertEqual(snap["environment"]["axeVersion"], "axe 1.2.3")
        # round-trips to disk
        on_disk = json.loads((proj / env_snapshot.SNAPSHOT_PATH).read_text())
        self.assertTrue(on_disk["environment"]["axe"])

    def test_axe_absent_records_false_and_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(env_snapshot.shutil, "which", return_value=None):
                snap = env_snapshot.capture(Path(tmp))
        self.assertFalse(snap["environment"]["axe"])
        self.assertIsNone(snap["environment"]["axeVersion"])

    def test_simulator_field_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(env_snapshot.shutil, "which", return_value=None):
                snap = env_snapshot.capture(Path(tmp))
        self.assertIn("simulator", snap)  # still present (None on this host)


if __name__ == "__main__":
    unittest.main()
```

- [ ] 3.2 Run — expect FAIL (`KeyError: 'environment'`).
- [ ] 3.3 Apply the EXACT edit to `scripts/env_snapshot.py`. Add a `_detect_axe()` helper after `_pick_simulator()` (after line 60), then add the `environment` key inside `capture()`.

Add this helper (insert after the `return fallback` line that closes `_pick_simulator`, before `def _udid_still_available`):

```python
def _detect_axe() -> tuple[bool, str | None]:
    """Phase-0 preflight: is the AXe UI-automation CLI installed?

    AXe (https://github.com/cameroncooke/AXe) is what flow_runner uses to drive
    functional flows. When it is absent, functional_flows_pass degrades rather
    than hard-fails, so recording availability here lets the operator see *why*
    the gate degraded without re-shelling out at gate time.
    """
    if shutil.which("axe") is None:
        return False, None
    rc, out = _run(["axe", "--version"], timeout=10)
    if rc != 0:
        return True, None
    return True, (out.strip() or None)
```

Then change the `capture()` body. Replace this exact block:

```python
def capture(project_root: Path) -> dict:
    snapshot = {
        "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "simulator": _pick_simulator(),
    }
```

with:

```python
def capture(project_root: Path) -> dict:
    axe_present, axe_version = _detect_axe()
    snapshot = {
        "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "simulator": _pick_simulator(),
        "environment": {
            "axe": axe_present,
            "axeVersion": axe_version,
        },
    }
```

The existing `_run` in env_snapshot returns a 2-tuple `(rc, stdout)` (NOT the 3-tuple flow_runner uses) — `_detect_axe()` matches that 2-tuple signature exactly. No other change needed; `ensure()` calls `capture()` so it inherits the new field, and `load()` just reads the file back.

- [ ] 3.4 Run — expect PASS (3 tests).
- [ ] 3.5 Commit.

**Commands & expected output**
```bash
cd /Users/louis/Code/Autobot && python3 -m unittest tests.test_env_snapshot_axe -v
# expected before impl: FAIL (KeyError: 'environment')
# expected after impl:  OK  (3 tests)
```

---

### Final: full-suite regression + commit gate

- [ ] F.1 Run the whole stdlib suite to confirm no regression in sibling streams' tests:
```bash
cd /Users/louis/Code/Autobot && bash tests/run_tests.sh 2>&1 | tail -25
# expected: OK (existing count + 12 + 6 + 3 new tests)
```
- [ ] F.2 Confirm the gate self-validator is clean across all gates:
```bash
cd /Users/louis/Code/Autobot && python3 scripts/gate_runner.py list-checks
# expected: no "WARNING: ... unimplemented procedural checks" line
```
- [ ] F.3 Commit any remaining staged changes (one commit per task is preferred; squash only if the workflow asks):
```bash
cd /Users/louis/Code/Autobot && git add scripts/flow_runner.py scripts/gate_checks/functional.py scripts/gate_runner.py scripts/env_snapshot.py spec/pipeline.json tests/test_flow_runner.py tests/test_functional_flows_gate.py tests/test_env_snapshot_axe.py && git commit -m "feat(verify): AXe flow_runner + functional_flows_pass gate + axe preflight"
```

---

## WS6 — Shipping hard-block (anti-laundering) + DEGRADED surfacing

## Work-stream: Shipping hard-block / anti-laundering + DEGRADED surfacing

Context grounding (verified in repo):
- `state["gates"]["5->6"]["status"]` is written by `build_gate_evidence` (scripts/gate_persistence.py:43) as one of `"passed" | "soft_failed" | "failed"`, and (once the DEGRADED work-stream lands) `"degraded"`.
- Tests run via `python3 -m unittest discover -s tests` (tests/run_tests.sh). Each test module calls `from conftest import import_runtime_modules; import_runtime_modules()` to put `scripts/` on `sys.path`. unittest.TestCase tests also run under pytest, satisfying the "pytest" contract requirement. Use unittest to match the repo (test_run_summary.py, test_intent_spec.py).
- Check signature is always `(project_dir: Path, app: str, state: dict) -> list[dict]`, results built with `_ok(...)`.
- `scripts/gate_checks/functional.py` does NOT exist yet (it is created by the functional-tests work-stream too). Task 1 creates it idempotently with a header + `_ok` import and appends only the one function this work-stream owns. The other work-stream MUST merge its two functions into the same file (see contractNotes).

---

### Task 1: `check_functional_verification_passed` (anti-laundering check) + registration

**Files:**
- `scripts/gate_checks/functional.py` (create if absent; else append the function)
- `scripts/gate_runner.py` (import + register)
- `tests/test_functional_verification.py` (new)

**TDD steps:**

- [ ] 1.1 Write the failing test `tests/test_functional_verification.py`:

```python
"""Anti-laundering: shipping must re-require a fresh functional PASS.

check_functional_verification_passed reads state.gates['5->6'].status and
HARD-FAILS (not a benign skip) when it is anything other than 'passed' —
including 'degraded'. A degraded 5->6 (functional flows unverified because no
simulator / axe / xcodebuild) must never be allowed to ship.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.functional import check_functional_verification_passed  # noqa: E402


def _state(status):
    if status is None:
        return {"gates": {}}
    return {"gates": {"5->6": {"status": status}}}


class TestFunctionalVerificationPassed(unittest.TestCase):
    def _result(self, status):
        results = check_functional_verification_passed(Path("/tmp"), "App", _state(status))
        self.assertEqual(len(results), 1, msg=f"expected exactly one sub-check, got {results}")
        return results[0]

    def test_passed_status_is_green(self):
        r = self._result("passed")
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_degraded_status_is_hard_fail(self):
        r = self._result("degraded")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False), msg="degraded must be a HARD fail, never a benign skip")
        self.assertIn("degraded", r["message"].lower())

    def test_soft_failed_status_is_hard_fail(self):
        r = self._result("soft_failed")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_failed_status_is_hard_fail(self):
        r = self._result("failed")
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))

    def test_missing_gate_is_hard_fail(self):
        r = self._result(None)
        self.assertFalse(r["passed"])
        self.assertFalse(r.get("skipped", False))
        self.assertIn("missing", r["message"].lower())

    def test_registered_in_gate_checks(self):
        from gate_runner import GATE_CHECKS
        self.assertIs(GATE_CHECKS.get("functional_verification_passed"),
                      check_functional_verification_passed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] 1.2 Run it, expect FAIL (ModuleNotFoundError: gate_checks.functional, or ImportError):

```bash
python3 -m unittest -v tests.test_functional_verification 2>&1 | tail -20
```
Expected: `ModuleNotFoundError: No module named 'gate_checks.functional'` (or `ImportError: cannot import name 'check_functional_verification_passed'` if the file already exists from the other work-stream).

- [ ] 1.3 Create/extend `scripts/gate_checks/functional.py`. If the file does NOT exist, create it with this full content. If it ALREADY exists (other work-stream landed first), append ONLY the `check_functional_verification_passed` function (skip the header/imports — they will already be present):

```python
"""Functional verification gate checks (logic tests, flows, shipping block).

Carved per the gate_checks package convention. All check signatures:
``(project_dir: Path, app: str, state: dict) -> list[dict]``, results via _ok().
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ._helpers import _ok  # noqa: E402


def check_functional_verification_passed(proj: Path, app: str, state: dict) -> list[dict]:
    """Anti-laundering shipping block.

    Reads the recorded verdict of gate 5->6 (state.gates['5->6'].status).
    Shipping is permitted ONLY when that verdict is a full 'passed'.

    A 'degraded' 5->6 means the functional flows could not be verified
    (no simulator / no axe / no xcodebuild). Allowing such a build to ship
    would launder an unverified app past the gate, so this is a HARD fail
    (passed=False, NOT a benign skip). 'soft_failed', 'failed', and a missing
    gate are likewise hard fails — there is no fresh proof the app works.
    """
    gate = state.get("gates", {}).get("5->6")
    if not isinstance(gate, dict) or "status" not in gate:
        return [_ok(
            "functional_verification_passed", False,
            "gate 5->6 status missing — no functional verification on record; "
            "re-run gate 5->6 before shipping",
        )]
    status = gate.get("status")
    if status == "passed":
        return [_ok("functional_verification_passed", True,
                    "gate 5->6 status=passed (functional verification on record)")]
    if status == "degraded":
        return [_ok(
            "functional_verification_passed", False,
            "gate 5->6 status=degraded — functional flows UNVERIFIED "
            "(simulator/axe/xcodebuild unavailable). Refusing to ship an "
            "unverified build (anti-laundering).",
        )]
    return [_ok(
        "functional_verification_passed", False,
        f"gate 5->6 status={status!r} — not a clean pass; refusing to ship.",
    )]
```

- [ ] 1.4 Register in `scripts/gate_runner.py`. Add the import after the existing `from gate_checks.deploy import (...)` block (lines ~96-98):

```python
from gate_checks.functional import (  # noqa: E402,F401
    check_functional_verification_passed,
)
```
NOTE: the functional-tests work-stream will widen this import to also include `check_logic_tests_pass, check_functional_flows_pass` — keep all three in one import block when merging.

Then add to the `GATE_CHECKS` dict. Insert immediately after the `# Gate 6→7` line (after `"deployment_attempt_recorded": check_deployment_attempt_recorded,`):

```python
    "functional_verification_passed": check_functional_verification_passed,
```

- [ ] 1.5 Run, expect PASS:

```bash
python3 -m unittest -v tests.test_functional_verification 2>&1 | tail -20
```
Expected: `Ran 6 tests` ... `OK`.

- [ ] 1.6 Sanity-check the registry has no unimplemented procedurals:

```bash
python3 scripts/gate_runner.py list-checks 2>&1 | tail -5
```
Expected: no `WARNING: ... unimplemented procedural checks` line that includes `functional_verification_passed`.

- [ ] 1.7 Commit:

```bash
git add scripts/gate_checks/functional.py scripts/gate_runner.py tests/test_functional_verification.py
git commit -m "feat(gate): functional_verification_passed — hard-block shipping a degraded 5->6 verdict"
```

---

### Task 2: Wire `functional_verification_passed` into gate 6->7 + add the shipping preflight to the command files

**Files:**
- `spec/pipeline.json` (add the check to gate `6->7`)
- `commands/testflight.md` (preflight before deployer dispatch)
- `commands/app-review.md` (preflight before deployer dispatch / archive)
- `tests/test_functional_verification.py` (extend: spec wiring assertion)

Why two places (grounded): gate `6->7` is `soft:true` and only runs at `advance-phase` AFTER archive/upload — too late to block shipping. So 6->7 records the verdict for the audit trail / run-summary, and the COMMAND PREFLIGHT (a fresh `run-gate --gate "5->6"` + status check placed BEFORE the deployer Agent dispatch) is the actual hard block. The preflight re-requires a fresh PASS and never trusts the stale `phases.5.metadata.build_succeeded`.

**TDD steps:**

- [ ] 2.1 Extend `tests/test_functional_verification.py` with a spec-wiring test (append before `if __name__`):

```python
class TestSpecWiring(unittest.TestCase):
    def test_gate_6to7_lists_functional_verification_passed_first(self):
        import json
        from pathlib import Path as _P
        spec_path = _P(__file__).resolve().parent.parent / "spec" / "pipeline.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        checks = spec["gates"]["6->7"]["checks"]
        names = [c.get("name") for c in checks if isinstance(c, dict)]
        self.assertIn("functional_verification_passed", names,
                      msg="gate 6->7 must record the functional verification verdict")
        self.assertEqual(names[0], "functional_verification_passed",
                         msg="functional_verification_passed must be the FIRST check in 6->7")
```

- [ ] 2.2 Run, expect FAIL:

```bash
python3 -m unittest -v tests.test_functional_verification.TestSpecWiring 2>&1 | tail -15
```
Expected: `AssertionError: 'functional_verification_passed' not found in [...]` (current 6->7 only has `deployment_attempt_recorded`).

- [ ] 2.3 Edit `spec/pipeline.json` gate `6->7` `checks` array. Current value is exactly:

```json
    "checks": [
      {
        "type": "procedural",
        "name": "deployment_attempt_recorded",
        "label": "deployment_attempt_recorded"
      }
    ]
```
Replace with (functional verification FIRST, deployment recording after):

```json
    "checks": [
      {
        "type": "procedural",
        "name": "functional_verification_passed",
        "label": "functional_verification_passed"
      },
      {
        "type": "procedural",
        "name": "deployment_attempt_recorded",
        "label": "deployment_attempt_recorded"
      }
    ]
```
Keep `"soft": true` on gate 6->7 unchanged — advance-phase must still proceed to the retrospective even when deployment failed. The hard block is the command preflight (steps below), not this soft gate.

- [ ] 2.4 Run, expect the spec-wiring test PASS and verify the spec still parses + the gate registry is complete:

```bash
python3 -m unittest -v tests.test_functional_verification.TestSpecWiring 2>&1 | tail -10
python3 -c "import json; json.load(open('spec/pipeline.json')); print('spec OK')"
python3 scripts/gate_runner.py list-checks --gate "6->7" 2>&1
```
Expected: `OK`; `spec OK`; the list-checks output shows both `✓ functional_verification_passed` and `✓ deployment_attempt_recorded`.

- [ ] 2.5 Add the shipping preflight to `commands/testflight.md`. Insert a new `## Step 1.5: 기능 검증 사전 차단 (anti-laundering)` block immediately AFTER the existing `## Step 1: Phase 6 시작` fenced block (after line ~99, before `## Step 2: deployer 에이전트 디스패치`). Full content to insert:

```markdown
## Step 1.5: 기능 검증 사전 차단 (anti-laundering)

archive/upload 시작 **전에** gate 5→6 을 신선하게 재실행하고 그 verdict 를 확인한다. 이는 `phases.5.metadata.build_succeeded` 같은 과거 플래그를 신뢰하지 않고, 빌드가 실제로 기능 검증(logic tests + functional flows)을 통과했는지 매 배포마다 다시 요구한다. verdict 가 `degraded`(시뮬레이터/axe/xcodebuild 부재로 flow 미검증)이면 **업로드를 거부**한다 — 미검증 빌드를 게이트 너머로 세탁(laundering)하지 않는다.

```bash
# 5→6 게이트를 신선하게 재실행 (evidence 를 state.gates["5->6"] 에 갱신 기록)
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "5->6" || true

FUNC_STATUS=$(python3 -c "
import json
s = json.load(open('.autobot/build-state.json'))
print(s.get('gates', {}).get('5->6', {}).get('status', 'missing'))
")
if [ "$FUNC_STATUS" != "passed" ]; then
  echo "ERROR: functional verification not passed (gate 5->6 status: $FUNC_STATUS)."
  if [ "$FUNC_STATUS" = "degraded" ]; then
    echo "       Functional flows were UNVERIFIED (simulator/axe/xcodebuild unavailable)."
    echo "       Refusing to ship an unverified build. Re-run /autobot:resume 5 on a host"
    echo "       with a booted simulator + axe + xcodebuild, then retry /autobot:testflight."
  else
    echo "       Re-run /autobot:resume to fix Phase 5 before shipping."
  fi
  exit 1
fi
echo "INFO: functional verification passed (gate 5->6 = passed) — proceeding to deploy"
```
```

- [ ] 2.6 Add the same preflight to `commands/app-review.md`. Insert a `### Phase F-0 — 기능 검증 사전 차단 (anti-laundering)` block at the START of `### Phase F` (immediately after the `### Phase F — 빌드가 ASC 에 없으면 deployer 에이전트 디스패치` heading line ~245, before the `/autobot:testflight 와 동일한 패턴.` sentence). Full content to insert:

```markdown
### Phase F-0 — 기능 검증 사전 차단 (anti-laundering)

deployer 디스패치 **전에** gate 5→6 을 신선하게 재실행하고 verdict 를 확인한다. `degraded`(시뮬레이터/axe/xcodebuild 부재로 functional flow 미검증)면 archive/upload 와 review 제출을 **모두 중단**한다 — 미검증 빌드 세탁 방지. 과거 `build_succeeded` 플래그를 신뢰하지 않고 매 제출마다 신선한 PASS 를 다시 요구한다.

```bash
bash "$CLAUDE_PLUGIN_ROOT/scripts/pipeline.sh" run-gate --gate "5->6" || true

FUNC_STATUS=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('gates',{}).get('5->6',{}).get('status','missing'))")
if [ "$FUNC_STATUS" != "passed" ]; then
  echo "ERROR: functional verification not passed (gate 5->6 status: $FUNC_STATUS). Refusing to submit for review."
  [ "$FUNC_STATUS" = "degraded" ] && echo "       Functional flows UNVERIFIED — re-run /autobot:resume 5 on a host with simulator + axe + xcodebuild."
  exit 1
fi
echo "INFO: functional verification passed — proceeding with Phase F"
```
```

- [ ] 2.7 Verify the command edits are well-formed (markdown fences balanced) and the preflight bash snippets parse:

```bash
python3 - <<'PY'
import re, pathlib
for f in ["commands/testflight.md", "commands/app-review.md"]:
    t = pathlib.Path(f).read_text(encoding="utf-8")
    assert "run-gate --gate \"5->6\"" in t, f"{f}: preflight run-gate missing"
    assert "anti-laundering" in t, f"{f}: anti-laundering rationale missing"
    assert t.count("```") % 2 == 0, f"{f}: unbalanced code fences"
    print(f, "OK")
PY
```
Expected: both files print `OK`.

- [ ] 2.8 Commit:

```bash
git add spec/pipeline.json commands/testflight.md commands/app-review.md tests/test_functional_verification.py
git commit -m "feat(ship): preflight 5->6 re-run + functional_verification_passed blocks shipping a degraded/unverified build"
```

---

### Task 3: run_summary.py VERIFIED / DEGRADED badge (prominent in JSON + Markdown)

**Files:**
- `scripts/run_summary.py` (add `_functional_verification` helper + wire into `build_summary` + `render_markdown`)
- `tests/test_run_summary_badge.py` (new)

**TDD steps:**

- [ ] 3.1 Write failing test `tests/test_run_summary_badge.py`:

```python
"""run-summary surfaces a loud VERIFIED / DEGRADED badge from gate 5->6."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from run_summary import build_summary, render_markdown  # noqa: E402


def _seed(project_root: Path, *, gate56_status):
    (project_root / ".autobot").mkdir()
    state = {"buildId": "b1", "appName": "X", "phases": {"5": {"status": "completed"}}}
    if gate56_status is not None:
        state["gates"] = {"5->6": {"status": gate56_status}}
    (project_root / ".autobot" / "build-state.json").write_text(json.dumps(state))
    (project_root / ".autobot" / "build-log.jsonl").write_text("")


class TestFunctionalVerificationBadge(unittest.TestCase):
    def _summary(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status=status)
            return build_summary(proj)

    def test_passed_yields_verified_badge(self):
        fv = self._summary("passed")["functionalVerification"]
        self.assertEqual(fv["badge"], "VERIFIED")
        self.assertEqual(fv["gate56Status"], "passed")
        self.assertTrue(fv["shippable"])

    def test_degraded_yields_degraded_badge_not_shippable(self):
        fv = self._summary("degraded")["functionalVerification"]
        self.assertEqual(fv["badge"], "DEGRADED")
        self.assertFalse(fv["shippable"])

    def test_missing_gate_yields_unverified(self):
        fv = self._summary(None)["functionalVerification"]
        self.assertEqual(fv["badge"], "UNVERIFIED")
        self.assertFalse(fv["shippable"])

    def test_markdown_renders_loud_degraded_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status="degraded")
            md = render_markdown(build_summary(proj))
        self.assertIn("## Verification", md)
        self.assertIn("DEGRADED", md)
        self.assertIn("functional unverified", md.lower())

    def test_markdown_renders_verified_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status="passed")
            md = render_markdown(build_summary(proj))
        self.assertIn("## Verification", md)
        self.assertIn("VERIFIED", md)


if __name__ == "__main__":
    unittest.main()
```

- [ ] 3.2 Run, expect FAIL:

```bash
python3 -m unittest -v tests.test_run_summary_badge 2>&1 | tail -20
```
Expected: `KeyError: 'functionalVerification'` (build_summary has no such key yet).

- [ ] 3.3 Edit `scripts/run_summary.py`. Add the helper after `_overall_status` (after line ~179, before `def build_summary`):

```python
def _functional_verification(state: dict) -> dict:
    """Derive the shipping-verification badge from gate 5->6's recorded verdict.

    badge:
      VERIFIED   — gate 5->6 status == 'passed' (functional flows ran + passed)
      DEGRADED   — gate 5->6 status == 'degraded' (flows unverified: no sim/axe)
      UNVERIFIED — gate 5->6 status is soft_failed/failed/absent
    Only VERIFIED is shippable. This mirrors check_functional_verification_passed.
    """
    status = (state.get("gates", {}).get("5->6") or {}).get("status")
    if status == "passed":
        badge = "VERIFIED"
    elif status == "degraded":
        badge = "DEGRADED"
    else:
        badge = "UNVERIFIED"
    return {
        "badge": badge,
        "gate56Status": status,
        "shippable": badge == "VERIFIED",
    }
```

Then wire it into `build_summary` — add the key to the `summary` dict (insert after the `"status": _overall_status(state),` line):

```python
        "functionalVerification": _functional_verification(state),
```

- [ ] 3.4 Edit `render_markdown` to emit a loud `## Verification` section. Insert immediately after the header block — find the line `lines.append("")` that follows the `environment` block (right before `lines.append("## Phase Ledger")`, ~line 217) and insert this block BEFORE `lines.append("## Phase Ledger")`:

```python
    fv = summary.get("functionalVerification") or {}
    badge = fv.get("badge", "UNVERIFIED")
    lines.append("## Verification")
    lines.append("")
    if badge == "VERIFIED":
        lines.append("- **functional verification**: ✅ VERIFIED "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — shippable")
    elif badge == "DEGRADED":
        lines.append("- **functional verification**: ⚠️ **DEGRADED (functional unverified)** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable: "
                     "flows could not run (simulator/axe/xcodebuild unavailable)")
    else:
        lines.append("- **functional verification**: ❌ **UNVERIFIED** "
                     f"(gate 5->6 = `{fv.get('gate56Status')}`) — NOT shippable")
    lines.append("")
```

- [ ] 3.5 Run, expect PASS:

```bash
python3 -m unittest -v tests.test_run_summary_badge 2>&1 | tail -20
```
Expected: `Ran 5 tests` ... `OK`.

- [ ] 3.6 Regression: existing run_summary tests still pass (the new key/section must not break them):

```bash
python3 -m unittest -v tests.test_run_summary 2>&1 | tail -10
```
Expected: `OK`. (TestRenderMarkdown builds summaries WITHOUT a `functionalVerification` key — `render_markdown` uses `summary.get("functionalVerification") or {}` so it defaults to the UNVERIFIED branch and does not KeyError.)

- [ ] 3.7 Commit:

```bash
git add scripts/run_summary.py tests/test_run_summary_badge.py
git commit -m "feat(run-summary): VERIFIED/DEGRADED functional-verification badge in run-summary.{json,md}"
```

---

### Task 4: Surface DEGRADED loudly in the MVP / CLI completion output

**Files:**
- `commands/mvp.md` (완료 보고 section — read the badge and print it loudly)
- `commands/testflight.md` (Step 4 user report — show the verification badge)

Grounding: `commands/mvp.md` "## 완료 보고" (line ~67-77) delegates the format to `autobot-build-report` + the orchestrator, and `run-summary.json` is written at Phase 7 (`pipeline.sh write-run-summary`). The completion output must read `functionalVerification.badge` and shout it when not VERIFIED. There is no runnable unit here (markdown command spec); the verification is a doc-content assertion test reused from Task 2's pattern.

**TDD steps:**

- [ ] 4.1 Add a content-assertion test to `tests/test_run_summary_badge.py` (append before `if __name__`):

```python
class TestCommandDocsSurfaceBadge(unittest.TestCase):
    def test_mvp_completion_reads_functional_verification_badge(self):
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        mvp = (root / "commands" / "mvp.md").read_text(encoding="utf-8")
        self.assertIn("functionalVerification", mvp,
                      msg="mvp completion report must read the verification badge")
        self.assertIn("DEGRADED", mvp)

    def test_testflight_report_shows_verification(self):
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent.parent
        tf = (root / "commands" / "testflight.md").read_text(encoding="utf-8")
        self.assertIn("Verification", tf)
```

- [ ] 4.2 Run, expect FAIL:

```bash
python3 -m unittest -v tests.test_run_summary_badge.TestCommandDocsSurfaceBadge 2>&1 | tail -15
```
Expected: `AssertionError: 'functionalVerification' not found in ...` (mvp.md does not mention it yet).

- [ ] 4.3 Edit `commands/mvp.md` "## 완료 보고" section. Append a new bullet + note after the existing bullet list (after the `- TestFlight 업로드 옵션 안내 (\`/autobot:testflight\`)` line, ~line 75), before the `자세한 출력 포맷은 ...` paragraph:

```markdown
- **기능 검증 배지 (필수, 크게 표시)**: `artifacts/latest/run-summary.json` 의 `functionalVerification.badge` 를 읽어 완료 화면 최상단에 출력한다:
  - `VERIFIED` → `✅ 기능 검증 통과 (functional flows passed)`
  - `DEGRADED` → `⚠️ DEGRADED — 기능 검증 미완료 (functional unverified). 시뮬레이터/axe/xcodebuild 부재로 flow 를 실행하지 못함. /autobot:testflight 는 이 상태에서 업로드를 거부합니다.`
  - `UNVERIFIED` → `❌ 기능 미검증 — /autobot:resume 5 로 Phase 5 를 재실행하세요.`

  `DEGRADED`/`UNVERIFIED` 는 초록색 완료 메시지에 묻히지 않도록 **별도 줄에 경고 아이콘과 함께** 크게 출력한다. 사용자가 미검증 빌드를 검증된 것으로 오인하지 않게 하는 것이 목적이다.
```

- [ ] 4.4 Edit `commands/testflight.md` Step 4 success report. In the first success example fenced block (the `✅ TestFlight 업로드 완료` block, ~lines 133-145), add a `Verification:` line right after the `Build status:` line:

Find:
```
Build status: uploaded (upload_success: true)
Testers:      alice@x.com (invited), bob@x.com (already in group)
```
Replace with:
```
Build status: uploaded (upload_success: true)
Verification: ✅ VERIFIED (gate 5->6 passed)   ← 업로드는 functional_verification_passed 통과 시에만 도달
Testers:      alice@x.com (invited), bob@x.com (already in group)
```

- [ ] 4.5 Run, expect PASS:

```bash
python3 -m unittest -v tests.test_run_summary_badge.TestCommandDocsSurfaceBadge 2>&1 | tail -10
```
Expected: `OK`.

- [ ] 4.6 Full suite regression — confirm nothing else broke:

```bash
bash tests/run_tests.sh 2>&1 | tail -15
```
Expected: final line `OK` (all tests pass). If the functional-tests work-stream has NOT yet landed its `check_logic_tests_pass`/`check_functional_flows_pass`, the `gate_runner.py list-checks` may warn about THOSE two names — that is their work-stream, not a regression of this one; the unittest suite itself must still report `OK`.

- [ ] 4.7 Commit:

```bash
git add commands/mvp.md commands/testflight.md tests/test_run_summary_badge.py
git commit -m "feat(report): surface DEGRADED/UNVERIFIED functional-verification badge loudly in mvp + testflight completion output"
```

---

## WS7 — Verifier immutability (anti-Goodhart, minimal cycle-1 defense)

codex's top-2 risk was **verifier mutability**: a fixer "passing" the gate by weakening the spec instead of fixing the app. The cheapest, highest-value cycle-1 defense is to make `.autobot/feature-spec.json` immutable to everyone except the architect, reusing the existing `fileOwnership.forbiddenInfra` + sandbox mechanism. (Full functional-fix-loop test-file immutability is a follow-on; see the Recovery section.)

### Task 7.1: forbid non-architect writes to feature-spec.json

**Files:**
- Modify: `spec/pipeline.json` (`fileOwnership.forbiddenInfra` array)
- Test: `tests/test_feature_spec_immutable.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_feature_spec_immutable.py
import json
import unittest
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "spec" / "pipeline.json"


class TestFeatureSpecImmutable(unittest.TestCase):
    def setUp(self):
        self.fo = json.loads(SPEC.read_text(encoding="utf-8"))["fileOwnership"]

    def test_feature_spec_is_forbidden_infra(self):
        self.assertIn(".autobot/feature-spec.json", self.fo["forbiddenInfra"])

    def test_only_architect_is_exempt(self):
        # architect produces it; no Phase 4/5 agent may rewrite the verifier spec.
        self.assertEqual(self.fo["forbiddenInfraExempt"], ["architect"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_feature_spec_immutable -v`
Expected: FAIL on `test_feature_spec_is_forbidden_infra` (`.autobot/feature-spec.json` not yet in the list).

- [ ] **Step 3: Add the entry to spec/pipeline.json**

In `spec/pipeline.json`, the `fileOwnership.forbiddenInfra` array is currently:

```json
"forbiddenInfra": [
  ".autobot/build-state.json",
  ".autobot/architecture.md",
  ".autobot/contracts/",
  ".autobot/build-log.jsonl",
  ".autobot/build.lock",
  ".autobot/learnings.json",
  ".autobot/active-learnings.md",
  ".autobot/phase-learnings/"
],
```

Add `".autobot/feature-spec.json"` (architect is already the sole `forbiddenInfraExempt`, so it remains writable by the producer):

```json
"forbiddenInfra": [
  ".autobot/build-state.json",
  ".autobot/architecture.md",
  ".autobot/feature-spec.json",
  ".autobot/contracts/",
  ".autobot/build-log.jsonl",
  ".autobot/build.lock",
  ".autobot/learnings.json",
  ".autobot/active-learnings.md",
  ".autobot/phase-learnings/"
],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_feature_spec_immutable -v`
Expected: PASS (both tests).

Then confirm the spec still validates and existing sandbox enforcement coverage stays green (the `forbiddenInfra` list is iterated by `scripts/sandbox_guard.py` / `scripts/agent-sandbox.sh`; adding an entry needs no enforcement-code change — see existing `tests/test_sandbox_enforcement.py`):

Run: `bash scripts/pipeline.sh schema && python3 -m unittest tests.test_sandbox_enforcement -v`
Expected: schema OK, sandbox tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec/pipeline.json tests/test_feature_spec_immutable.py
git commit -m "feat(sandbox): make feature-spec.json forbiddenInfra (architect-only) to block verifier weakening"
```

---

## Open issues & accepted risks (cycle 1)

**WS2 — DEGRADED three-valued verdict in the gate engine**
- The LOCKED CONTRACT says 'pytest' but the actual harness is stdlib unittest (tests/run_tests.sh -> python3 -m unittest discover). New tests are written as unittest.TestCase to match the real suite; -k filters work with unittest's discover. If the orchestrator truly requires pytest invocation, the same files run under `pytest tests/test_degraded_verdict.py` unchanged (pytest collects unittest.TestCase).
- Task 5 drives the gate-result -> build_gate_evidence -> mutate_state_with_validation path in-process rather than spawning a fully-degraded gate 5->6 via pipeline.sh, because gate 5->6 has no degradable check registered yet (functional.py is a sibling work-stream). Once check_functional_flows_pass lands, an additional end-to-end `advance-phase` test that produces a real degraded 5->6 (no simulator) should be added to confirm the phase status becomes 'completed' while gates['5->6'].status='degraded'.
- format_text uses non-ASCII glyphs (⚠ ⊘ ✓ ✗) already present in the file; tests assert on the ⚠ substring. If any CI runs with a non-UTF-8 locale this could mis-encode, but the existing ⊘/✓/✗ assertions in the codebase already rely on UTF-8 so this matches current practice.
- The shipping hard-block check functional_verification_passed (reads state.gates['5->6'].status, FAIL if 'degraded') is a separate work-stream; this work-stream only guarantees the 'degraded' status is minted and durably stored so that gate can read it.

**WS1 — feature-spec schema + validators (scripts/intent_spec.py) + architect **
- spec/pipeline.json has NO architectureSchema key (verified by JSON parse). The architect.md line ~93 'spec/pipeline.json.architectureSchema 가 SSOT' was a dead reference; Task 2 repoints it to the inline (d) block. If another work-stream planned to ADD an architectureSchema key to pipeline.json, coordinate — Task 2 instead documents that the key does not exist.
- scripts/verify_spec_docs.py:check_prose_contract_drift does not currently scan architect.md for feature-spec terms, so the new prose is not drift-protected. If the team wants the new (f) section's contract terms (e.g. POSTCONDITION_KINDS membership) enforced against intent_spec.py, that would be a separate drift-check addition — out of scope for this stream.
- The gate-wiring (register check_feature_spec_declared / check_feature_spec_quality in capability.py + GATE_CHECKS dict + spec/pipeline.json gate 1->2 procedural entries) is OWNED BY THE CAPABILITY/GATE work-stream, not this one. This stream only provides the validators they call. The skip-vs-hard-fail policy for an absent feature-spec.json must be decided there (recommend benign skip when absent for legacy-build compatibility, matching check_app_intent_declared).
- feature-spec acceptance 'anchor' grounding is advisory in the schema layer — validate_feature_spec only checks the FEATURE-level anchor is non-empty, NOT that step/postcondition anchors actually exist in the UI tree. Cross-checking step anchors against the rendered UI is the job of the generalized intent_anchors_in_ui (gate 4->5) and flow_runner (gate 5->6), owned by other streams.

**WS5 — Gate 1->2 spec checks + generalize intent_anchors_in_ui + spec/pipelin**
- The LOCKED CONTRACT says tests are 'pytest under tests/', but the ACTUAL repo (tests/run_tests.sh, conftest.py docstring) runs stdlib unittest with no pytest installed. I wrote unittest TestCases to match reality. If the orchestrator literally shells out to `pytest`, confirm pytest is on PATH; otherwise the contract's pytest claim is wrong for this repo.
- The _ok degraded extension (scripts/gate_checks/_helpers.py adding `*, degraded: bool = False`) is owned by another work-stream and is NOT yet present (current _helpers.py line 35 has only `skipped`). My Gate 1->2 checks never pass `degraded=`, so they work against BOTH the current and extended _ok. But my test test_feature_spec_gates.py asserts `r[0].get('degraded')` is falsy — that's safe either way (absent key => None => falsy). No blocker, just noting the ordering independence.
- Task 0 risks a merge collision with the intent_spec work-stream if BOTH land the FeatureSpec dataclasses. The grep guard in 0.1 mitigates this but requires whoever executes to actually check. If both streams run blind in parallel, dedupe at integration.
- find_missing_feature_anchors searches Views/, App/, ViewModels/ — same scope as the legacy find_unused_anchors. If a feature anchor is attached in a Swift file outside those three dirs (e.g. a top-level `Components/` not under Views/), it would be falsely reported missing. Current ui-builder.md mandates all UI under <App>/Views|ViewModels|App, so this matches convention, but it's a coupling worth noting for the functional.py/flow_runner work-stream which drives the same anchors at runtime.
- The agent-prompt test (Task 4) asserts substring presence ('functional acceptance', 'feature-spec.json'). It is intentionally loose — if another work-stream rewrites these agent files with different wording but same intent, the substring asserts could break. Kept minimal to avoid brittle exact-text coupling, but coordinate if quality-engineer.md is edited by the functional.py stream too (both streams touch Phase 5 quality-engineer expectations).

**WS3 — Pillar 2a — authored Swift Testing tests (logic_tests_pass) + harness-**
- .xcresult parsing risk: xcresulttool's `get test-results summary/tests` subcommands are version-gated. On the verified machine (xcresulttool 24757, schema 0.1.0) they exist, but older Xcode (<15.x) only has the deprecated `get object --format json --legacy` path with a totally different schema (Actions[].actionResult.testsRef -> ActionTestPlanRunSummaries). functional.py treats any rc!=0 or unparseable JSON from _run_xcresulttool as: primary -> hard fail (if build status was passed/failed) and completeness -> empty authored-name set (silent, non-blocking). It does NOT fall back to the legacy command. If Autobot must support older Xcode, add a legacy-format fallback in _xcresult_summary/_authored_test_names.
- Hard-fail-on-unparseable could mask a degradable condition: if xcodebuild test produces NO .xcresult on a transient infra hiccup but integration_build still returns status!='skipped', the primary check hard-fails rather than degrades. This is intentional (a missing/empty .xcresult after a non-skipped test run is a real problem), but means an xcresulttool that is itself missing on a machine that HAS xcodebuild would wrongly hard-fail. Mitigation if observed: detect rc==127 from _run_xcresulttool and convert to a degraded skip.
- Task 2 GAP assumption: xcodegen auto-generates a scheme without a populated TestAction when no `schemes:` block is present. This is xcodegen-version-dependent; some versions DO auto-attach test targets linked via target dependencies. The added explicit `schemes:` block is harmless either way (it overrides auto-generation), but the guard test test_project_yml_wires_test_scheme only checks the project.yml text, NOT the resulting .xcscheme (it stubs xcodegen as a no-op). A fuller check would require a real xcodegen + xcodebuild, which is out of scope for the unittest suite.
- completeness sub-check name matching is purely lexical (acceptance id == test fn name). If teams name tests like `test_addItem_increasesCount` or use Swift Testing display names via @Test("..."), the matcher misses them and emits a (non-blocking) WARNING. SKILL.md Step 5 instructs the exact naming, but this is a convention, not enforced by the compiler.
- Landing order coupling: spec/pipeline.json referencing `functional_flows_pass` while gate_runner.py only imports `check_logic_tests_pass` (if flow_runner work-stream hasn't landed) will make `list-checks` report an unimplemented procedural and exit 1, which the push-checks CI may treat as failure. Either land both work-streams together or temporarily omit the functional_flows_pass spec descriptor + import until flow_runner lands.

**WS4 — AXe-driven flow runner (pillar 2b): scripts/flow_runner.py + check_fun**
- AXe timing/SwiftUI-transition flake: the semantic wait polls describe-ui until the anchor is present+enabled+in-bounds, but a SwiftUI push/sheet transition can leave the OLD screen's anchor briefly satisfying the readiness test mid-animation, causing a tap on a view that is animating out. Mitigation shipped: DEFAULT_POSTCONDITION_SETTLE (0.6s) before re-querying for the postcondition + a _relaunch() reset before each acceptance. This is a heuristic, not a guarantee; matrix/parallax transitions or long custom animations may still need a per-feature settle override (not yet plumbed through FeatureSpec).
- _screen_bounds() approximates screen size from the union of element frames because AXe exposes no explicit screen-size query. On a sparse screen (few/large overlay elements) the computed bounds can be smaller than the real device, which could falsely reject an in-bounds anchor near the bottom edge. Falls back to a generous 1366x1366 default when no frames are found. A real device-dimension lookup (via simctl device type) would be more robust.
- navigated_to postcondition uses 'target anchor present AFTER' (presence-only), not 'present after AND absent before'. This is deliberately lenient to avoid flaking when the source screen and destination share an anchor in a NavigationStack, but it means a flow that taps and lands on a screen that ALREADY showed the target anchor would false-pass. count_increased/count_decreased are the stricter, recommended postconditions for list-mutating flows.
- value_persisted_after_relaunch terminates+relaunches via simctl and re-queries describe-ui for anchor presence — it verifies the VIEW renders post-relaunch, not that the underlying VALUE (e.g. a specific label text) survived. Asserting persisted text/value would require comparing element.label across relaunch, which the current postcondition params schema ({'anchor': ...}) does not carry. Flag for the intent-spec stream if value-level assertions are needed.
- check_logic_tests_pass here is a placeholder-grade impl (status->verdict) and does NOT parse the .xcresult for individual failing test names. If the functional sibling stream does not replace it, gate failures will report only the xcodebuild error signature, not which test failed — adequate for the hard-block but weak for diagnosis.
- run_flows installs+launches+relaunches a real app per acceptance; on a cold sim this is slow (boot can be 30-60s) and the per-acceptance _relaunch adds ~1s each. With many P0/P1 features the gate could approach the orchestrator's phase timeout. No global wall-clock budget is enforced inside run_flows yet — only per-axe-call DEFAULT_AXE_TIMEOUT and the 8s per-anchor wait. Consider a total-flow-budget guard if feature counts grow.

**WS6 — shipping hard-block / anti-laundering + DEGRADED surfacing**
- STALE-FLAG TRUST (root anti-laundering finding): commands/testflight.md Step 0b and commands/app-review.md Step 0 gate shipping ONLY on `phases.5.status == 'completed'`. They never re-evaluate gate 5->6 — so a build whose 5->6 was recorded as 'degraded' (functional flows skipped: no sim/axe) can be archived+uploaded+submitted. Worse, commands/testflight.md Step 3 advances Phase 6 with the comment 'Gate 6->7 검증은 soft — deployment_attempt_recorded 만 본다', meaning the ONLY thing checked at deploy time is that a deploy was attempted, never that the app was functionally verified. This is the exact laundering path the preflight must close.
- Gate 6->7 is soft:true (spec/pipeline.json) and only runs at advance-phase, AFTER archive/upload already happened — so adding functional_verification_passed to 6->7's checks alone does NOT block shipping (the binary is already on ASC by then). The real block MUST be the preflight run-gate in the command files placed BEFORE the deployer Agent dispatch (testflight Step 2 / app-review Phase F). I wire both: 6->7 records the verdict for the run-summary/audit trail, and the command preflight is the actual gate.
- check_build_succeeded (scripts/gate_checks/build.py) trusts phases.5.metadata.build_succeeded with no freshness check — if source changed after Phase 5 recorded true, the flag is stale. The preflight re-runs the FULL 5->6 gate (which re-evaluates build_succeeded + runtime_smoke + visual_contract + functional flows live where possible), partially mitigating staleness, but build_succeeded itself is still a recorded metadata flag not a live rebuild. Out of scope to fix here; flagged.
- DEPENDENCY ON OTHER WORK-STREAM: scripts/gate_checks/functional.py and the 'degraded' value of build_gate_evidence status (gate_persistence.py:43) are produced by the functional-tests / DEGRADED-verdict work-stream. My tests stub state.gates['5->6'].status directly so they pass independently, but the END-TO-END degraded path only works once that work-stream lands the three-valued run_gate verdict and the status='degraded' branch in build_gate_evidence. If those are not merged, 5->6 can never be 'degraded' and functional_verification_passed degenerates to (passed iff 5->6 passed) — still correct, just never triggers the degraded block.
- _ok in tests: my new check uses the EXISTING _ok signature for hard fail (no skipped/degraded kwargs), so my tests do not depend on the _helpers.py _ok extension landing first. Safe to merge in any order.

---

## Deferred (NOT cycle 1)

- Per-screen visual assertions / screenshot diffing as gate truth (screenshots stay debug-only).
- XCUITest-target generation (cycle 1 uses AXe; XCUITest is the documented future shipping verifier).
- Interactive intent checkpoint with the user (cluster B's interactive half — "질문 없이" stays inviolable).
- Recovery-robustness overhaul beyond the bounded functional-fix loop; learning-noise correction (#10).
- Value-level (label text) persistence assertions and per-feature settle overrides in flow_runner (params schema is anchor-only in cycle 1).

## Recovery (functional-fix loop) — apply when logic_tests_pass / functional_flows_pass fails

Per spec §7: a failing functional check routes to a **separate bounded functional-fix loop (max 2)**, NOT the Phase 5 build-fix loop. Ownership by failure type — compile/test-infra → quality-engineer; data assertion → data-engineer + quality-engineer; anchor/navigation → ui-builder + quality-engineer; spec ambiguity → FAIL (no auto-weaken). **Invariant:** during a functional-fix retry, `.autobot/feature-spec.json` and the generated test files are forbidden to edit (enforced via `fileOwnership.forbiddenInfra` + sandbox). Wiring this loop policy into `spec/pipeline.json policies` + `autobot-orchestrator` is a follow-on task tracked here; cycle-1 minimum is: a failed functional gate triggers normal Phase 5 retry with the verifier files sandbox-locked.
