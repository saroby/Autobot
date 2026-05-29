#!/usr/bin/env python3
"""End-to-end verification PROOF harness.

Runs the SHIPPED functional verification checks (check_logic_tests_pass +
check_functional_flows_pass) against a committed fixture iOS app on a real,
booted iOS 26 simulator — the thing cycle-1 only ever exercised with mocks.

  GreenApp (working)  -> both checks PASS        => VERIFIED
  RedApp   (broken UI)-> functional_flows_pass    => HARD FAIL  (the detector detects)

This is the "light the fire, watch the smoke detector go off" test. It is run
both locally (observable proof on a dev Mac) and in CI (.github/workflows/e2e-verify.yml).

Usage:
  python3 scripts/e2e_verify.py --fixture tests/e2e/fixtures/GreenApp --app GreenApp --expect verified
  python3 scripts/e2e_verify.py --fixture tests/e2e/fixtures/RedApp   --app RedApp   --expect flow-fail
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _run(cmd: list[str], *, timeout: int = 900) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def _result_state(r: dict) -> str:
    if r.get("skipped") and r.get("degraded"):
        return "DEGRADED"
    if r.get("skipped"):
        return "skipped"
    return "passed" if r.get("passed") else "failed"


def evaluate(logic: list[dict], flow: list[dict], expect: str) -> tuple[bool, str]:
    """Pure verdict logic (unit-tested). `logic`/`flow` are the check result lists.

    expect == "verified":  logic_tests_pass AND functional_flows_pass both truly passed.
    expect == "flow-fail": functional_flows_pass HARD-failed (ran and failed; not a skip).
    """
    lp = logic[0] if logic else {"passed": False, "message": "no logic result"}
    fp = flow[0] if flow else {"passed": False, "message": "no flow result"}
    logic_pass = bool(lp.get("passed")) and not lp.get("skipped")
    flow_pass = bool(fp.get("passed")) and not fp.get("skipped")
    flow_hardfail = (not fp.get("passed")) and (not fp.get("skipped"))

    if expect == "verified":
        ok = logic_pass and flow_pass
        return ok, f"logic={_result_state(lp)}, flow={_result_state(fp)} (expected both passed)"
    if expect == "flow-fail":
        return flow_hardfail, f"flow={_result_state(fp)} (expected hard-fail)"
    return False, f"unknown --expect {expect!r}"


def _pick_ios26_iphone() -> tuple[str | None, str]:
    """Pick an available iPhone on an iOS 26 runtime, preferring an already-booted
    one. The generic sim_runtime picker falls back to ANY iOS runtime (e.g. iOS 17),
    which fails to build an iOS-26-deployment-target app, so select 26 explicitly.
    """
    rc, out, _ = _run(["xcrun", "simctl", "list", "devices", "available", "--json"])
    if rc != 0:
        return None, "simctl_list_failed"
    try:
        devices = json.loads(out).get("devices", {})
    except json.JSONDecodeError:
        return None, "simctl_unparseable"
    booted = None
    first = None
    for runtime, devs in devices.items():
        if "iOS-26" not in runtime:
            continue
        for d in devs:
            if "iPhone" not in d.get("name", ""):
                continue
            if d.get("state") == "Booted":
                booted = (d["udid"], f"booted-{d['name']}")
            if first is None:
                first = (d["udid"], f"available-{d['name']}")
    if booted:
        return booted
    if first:
        return first
    # Create one on the newest iOS 26 runtime if none exist.
    rc, rt_out, _ = _run(["xcrun", "simctl", "list", "runtimes", "iOS"])
    runtime_id = ""
    for line in rt_out.splitlines():
        m = re.search(r"com\.apple\.CoreSimulator\.SimRuntime\.iOS-26-\d+", line)
        if m:
            runtime_id = m.group(0)
    rc, dt_out, _ = _run(["xcrun", "simctl", "list", "devicetypes"])
    dtype = ""
    for line in dt_out.splitlines():
        m = re.search(r"com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-1[0-9][A-Za-z0-9-]*", line)
        if m and "iPhone" in line:
            dtype = m.group(0)
    if runtime_id and dtype:
        rc, cr_out, _ = _run(["xcrun", "simctl", "create", "autobot-e2e", dtype, runtime_id])
        if rc == 0 and cr_out.strip():
            return cr_out.strip(), "created"
    return None, "no_ios26_simulator"


def _pin_simulator(project_root: Path) -> tuple[str | None, str]:
    """Boot an iOS 26 sim and pin it in env_snapshot so both checks share it."""
    import sim_runtime

    udid, source = _pick_ios26_iphone()
    if not udid:
        return None, source

    booted, detail = sim_runtime._boot(udid)
    if not booted:
        return None, f"boot_failed: {detail}"
    _run(["xcrun", "simctl", "bootstatus", udid, "-b"], timeout=300)

    snap_path = project_root / ".autobot" / "env_snapshot.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps({"simulator": {"udid": udid, "source": source}}), encoding="utf-8")
    return udid, source


def _prepare_fixture(fixture: Path, app: str, udid: str) -> tuple[bool, str]:
    """Generate the project, copy the feature-spec, build the app where
    sim_runtime._find_built_app will look (`.autobot/phase-5/attempt-1`)."""
    if shutil.which("xcodegen") is None:
        return False, "xcodegen_unavailable"
    rc, _, err = _run(["xcodegen", "generate", "--spec", str(fixture / "project.yml"),
                       "--project", str(fixture)], timeout=120)
    if rc != 0:
        return False, f"xcodegen_failed: {err.strip()[:160]}"

    # feature-spec.json lives at the fixture top level (.autobot/ is gitignored);
    # copy it where load_feature_spec reads it.
    spec_src = fixture / "feature-spec.json"
    spec_dst = fixture / ".autobot" / "feature-spec.json"
    spec_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec_src, spec_dst)

    # Build the .app into the path _find_built_app globs (phase-5/attempt-1).
    dd = fixture / ".autobot" / "phase-5" / "attempt-1"
    rc, _, err = _run([
        "xcodebuild", "-project", str(fixture / f"{app}.xcodeproj"),
        "-scheme", app, "-destination", f"id={udid}",
        "-derivedDataPath", str(dd),
        "-quiet", "CODE_SIGNING_ALLOWED=NO", "ONLY_ACTIVE_ARCH=YES", "build",
    ], timeout=900)
    if rc != 0:
        return False, f"app_build_failed: {err.strip()[:200]}"
    return True, "prepared"


def run_fixture(fixture: Path, app: str, expect: str) -> dict:
    from gate_checks.functional import check_functional_flows_pass, check_logic_tests_pass

    fixture = fixture.resolve()
    udid, sim_src = _pin_simulator(fixture)
    if not udid:
        return {"ok": False, "reason": f"simulator unavailable: {sim_src}",
                "logic": None, "flow": None, "udid": None}

    ok_prep, prep = _prepare_fixture(fixture, app, udid)
    if not ok_prep:
        return {"ok": False, "reason": f"fixture prep failed: {prep}",
                "logic": None, "flow": None, "udid": udid}

    logic = check_logic_tests_pass(fixture, app, {})
    flow = check_functional_flows_pass(fixture, app, {})
    ok, detail = evaluate(logic, flow, expect)
    return {
        "ok": ok, "reason": detail, "udid": udid, "simSource": sim_src,
        "logic": logic, "flow": flow, "expect": expect, "app": app,
    }


def _print_report(res: dict) -> None:
    print("=" * 70)
    print(f"E2E VERIFY  app={res.get('app')}  expect={res.get('expect')}  udid={res.get('udid')}")
    for name in ("logic", "flow"):
        rs = res.get(name)
        if rs:
            r0 = rs[0]
            print(f"  {name:6} [{_result_state(r0)}] {r0.get('message', '')[:120]}")
    print(f"  VERDICT: {'PASS ✅' if res['ok'] else 'FAIL ❌'} — {res['reason']}")
    print("=" * 70)


def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--expect", required=True, choices=["verified", "flow-fail"])
    args = ap.parse_args()
    res = run_fixture(Path(args.fixture), args.app, args.expect)
    _print_report(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
