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
from intent_spec import load_feature_spec  # noqa: E402
from flow_runner import run_flows  # noqa: E402

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
    # `xcodebuild test` needs a CONCRETE simulator destination (the generic
    # "platform=iOS Simulator" is rejected for the test action). Resolve a sim
    # UDID; if none is available, integration_build degrades-skips.
    destination = None
    try:
        import sim_runtime
        udid, _ = sim_runtime._pick_simulator_udid(project_dir)
        if udid:
            destination = f"id={udid}"
    except Exception:
        destination = None
    build = integration_build(project_dir, app, test=True, destination=destination)
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


def check_functional_flows_pass(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — drive declared P0/P1 feature flows through AXe and assert
    postconditions.

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
        # A non-degraded skip means "nothing to drive". That is only legitimate
        # when there is no P0 feature: if a P0 feature exists but declared no
        # kind:'flow' acceptance, the spec slipped past Gate 1->2's
        # assess_feature_spec_quality, and benign-skipping here would let a
        # logic-only build earn VERIFIED with the simulator flow never run.
        # Refuse it as a hard fail (defense-in-depth for the same hole).
        if reason == "no_features" and any(
            getattr(f, "priority", None) == "P0" for f in features
        ):
            return [_ok(
                "functional_flows_pass", False,
                "P0 feature(s) declared but none has a kind:'flow' acceptance to "
                "drive — cannot functionally verify the app (logic-only spec is "
                "not shippable; add a flow acceptance for each P0 feature)",
            )]
        # benign skip (no P0 features that need a runtime flow)
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
