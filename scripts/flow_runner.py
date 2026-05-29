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


def _anchor_id(e: dict) -> str:
    """Accessibility identifier of an AXe element.

    Real AXe (≥1.7) carries the accessibilityIdentifier in `AXUniqueId`; we keep
    `identifier` as a tolerant fallback. SwiftUI `.accessibilityIdentifier("x")`
    surfaces as AXUniqueId in `axe describe-ui`.
    """
    return str(e.get("AXUniqueId") or e.get("identifier") or "")


def _anchor_ready(elements: list[dict], anchor: str, screen: dict) -> bool:
    for e in elements:
        if _anchor_id(e) != anchor:
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
    return sum(1 for e in elements if _anchor_id(e) == anchor)


def _present(elements: list[dict], anchor: str) -> bool:
    return any(_anchor_id(e) == anchor for e in elements)


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
