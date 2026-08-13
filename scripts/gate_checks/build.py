"""Final-build verification: build, runtime, visual contract, metadata.

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from spec_loader import resolve_app_template  # noqa: E402

from ._helpers import (
    load_json,
    load_spec,
    _ok,
    _file_exists,
    _dir_exists,
    _dir_has_swift,
    _file_nonempty,
    _file_grep,
    _run_cmd,
    _markdown_heading_present,
    _agent_writes_dirs,
    strip_swift_noncode,
)


def check_build_succeeded(proj: Path, app: str, state: dict) -> list[dict]:
    """Truth source: phases.5.metadata.build_succeeded only.

    The Phase 5 build flow (quality-engineer / autobot-integration-build skill)
    is required to record this via:
      pipeline.sh advance-phase --phase 5 --metadata build_succeeded=true
    build-log.jsonl is audit-only and must not influence gate decisions.
    """
    p5 = state.get("phases", {}).get("5", {})
    meta = p5.get("metadata", {})
    recorded = meta.get("build_succeeded")
    if recorded is True:
        return [_ok("build_result", True, "phases.5.metadata.build_succeeded=true")]
    if recorded is False:
        return [_ok("build_result", False, "phases.5.metadata.build_succeeded=false")]
    return [_ok(
        "build_result", False,
        "phases.5.metadata.build_succeeded missing — Phase 5 must record build outcome via metadata",
    )]


def check_visual_contract(proj: Path, app: str, state: dict) -> list[dict]:
    """Compare the runtime screenshot against the design-spec palette/anchors.

    Skipped when no screenshot is available yet (runtime_smoke also skipped) or
    when no palette can be derived. Otherwise it catches blank screens, broken
    root views, and "design said warm coral, app shipped system blue" regressions.
    """
    from visual_contract import evaluate

    result = evaluate(proj)
    status = result.get("status")
    if status == "skipped":
        reason = result.get("skipReason", "unknown")
        if reason == "visual_contract_disabled":
            # Env kill-switch is standing + unaudited (unlike the buildId-scoped
            # --allow-visual-drift waiver) — surface it as DEGRADED, never a
            # benign skip, so preflight-ship refuses to launder it.
            return [_ok(
                "visual_contract", False,
                "AUTOBOT_DISABLE_VISUAL_CONTRACT=1 — visual contract disabled by "
                "env kill-switch. DEGRADED (not shippable); use the audited "
                "--allow-visual-drift build-scoped waiver instead.",
                skipped=True, degraded=True,
            )]
        return [_ok(
            "visual_contract", True,
            f"skipped: {reason}",
            skipped=True,
        )]
    if status == "passed":
        match = result.get("paletteMatch")
        if match:
            extra = f" — dominant matches '{match['closestToken']}' (ΔE={match['deltaE']})"
        else:
            extra = " — no palette tokens declared, structural checks only"
        results = [_ok(
            "visual_contract", True,
            f"screenshot OK{extra} ({result.get('notes')})",
        )]
        # Dark-mode render verification (design-spec darkMode consumer).
        # DEGRADED-only, never a hard fail: the dark capture is a secondary
        # heuristic render check and must not trip the circuit breaker.
        dark = result.get("darkMode")
        if isinstance(dark, dict):
            dark_status = dark.get("status")
            if dark_status == "failed":
                results.append(_ok(
                    "visual_contract_dark", False,
                    f"dark-mode render violated: {dark.get('reason', 'unknown')} "
                    f"— DEGRADED (not shippable)",
                    skipped=True, degraded=True,
                ))
            elif dark_status == "passed":
                results.append(_ok(
                    "visual_contract_dark", True,
                    f"dark-mode screenshot OK ({dark.get('notes', 'variance check')})",
                ))
            else:
                results.append(_ok(
                    "visual_contract_dark", True,
                    f"dark-mode check skipped: {dark.get('skipReason', 'unknown')}",
                    skipped=True,
                ))
        return results
    return [_ok(
        "visual_contract", False,
        f"visual contract violated: {result.get('reason', 'unknown')}",
    )]


def check_visual_judge(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — multimodal design-fidelity verdict on the built app.

    Where check_visual_contract is a deterministic Pillow/deltaE structural pass
    (blank/monochrome → fail, colour-match → informational), this check reads the
    verdict of a *vision judge*: a multimodal agent (Phase 5 / integration-build
    Step 9) that Reads the runtime screenshot and compares it against the design
    intent (design-spec), then records the result. The LLM work
    is done by the agent; this gate check only reads what it recorded — the same
    "agent records metadata → deterministic check reads it" pattern as
    check_build_succeeded.

    Truth source: ``phases.5.metadata.visualJudge`` (a dict)::

        {"verdict": "pass" | "fail",
         "highCount": int,            # number of HIGH-severity fidelity violations
         "summary": str,              # one-line human summary
         "violations": [ ... ]}       # optional detail (severity/axis/title/evidence)

    Verdict → gate mapping (DEGRADED-only, NEVER a hard fail):
      - state.allowVisualDrift set        → pass (operator waived visual gating)
      - verdict == 'pass'                 → pass
      - verdict == 'fail'                 → DEGRADED (skipped+degraded)
      - no/garbled verdict, screenshot on disk  → DEGRADED (anti-laundering: the
        screen WAS verifiable but Step 9 recorded nothing — refuse to launder it
        to VERIFIED, mirroring functional_flows_pass / peer_review_acceptable)
      - no/garbled verdict, NO screenshot → benign skip (no simulator → not
        verifiable here; runtime_smoke degrades that case on its own)

    Why DEGRADED and never a hard fail: gate 5→6 is soft=False, so a hard fail
    here marks Phase 5 failed and increments retryCount (phase_advance.py) — a
    nondeterministic, uncalibrated judge could trip the global circuit breaker
    and halt the autonomous /mvp build ("질문 없이 끝까지"). DEGRADED still blocks
    *shipping*: it drives functionalVerification → DEGRADED, and the upload paths
    (/autobot:testflight Step 1.5, /autobot:app-review) refuse any non-'passed'
    gate 5→6 via check_functional_verification_passed (anti-laundering). The
    operator overrides with ``/autobot:resume 5 --allow-visual-drift`` which
    persists the top-level ``allowVisualDrift`` flag (via pipeline.sh set-flag,
    logged as flag_changed) so the flagless upload re-run honours it.
    """
    p5 = state.get("phases", {}).get("5", {})
    meta = p5.get("metadata", {}) if isinstance(p5, dict) else {}
    verdict_obj = meta.get("visualJudge")
    has_verdict = isinstance(verdict_obj, dict) and bool(verdict_obj.get("verdict"))
    verdict = str(verdict_obj.get("verdict")).lower() if has_verdict else None
    summary = str(verdict_obj.get("summary") or "").strip() if has_verdict else ""
    high = verdict_obj.get("highCount") if has_verdict else None
    high_note = f" ({high} high-severity)" if isinstance(high, int) and high else ""

    # Operator opt-out: --allow-visual-drift binds the waiver to THIS build's id
    # (release-scoped, NOT a permanent flag). It holds only while
    # state.allowVisualDrift == state.buildId: /autobot:testflight re-runs the gate
    # on the SAME build so the waiver still applies through upload, but a fresh
    # build gets a new id → the waiver auto-expires and cannot silently launder
    # later builds. (Legacy boolean `true` is intentionally NOT honored — a
    # permanent waiver is exactly the laundering risk this scoping removes.)
    build_id = state.get("buildId") or "unknown-build"
    if state.get("allowVisualDrift") == build_id:
        return [_ok(
            "visual_judge", True,
            f"visual gating waived for build {build_id} via --allow-visual-drift{high_note}"
            f"{f': {summary}' if summary else ''}",
        )]

    if verdict == "pass":
        # Anti-laundering: integration-build Step 9 always writes the judge
        # artifact before recording the metadata verdict, so a metadata-only
        # 'pass' (one --metadata line) must not roll up green.
        artifact = proj / ".autobot" / "artifacts" / "visual-judge.json"
        if not artifact.is_file():
            return [_ok(
                "visual_judge", False,
                "metadata verdict=pass but .autobot/artifacts/visual-judge.json "
                "is absent — PASS self-report without the judge artifact is not "
                "auditable. DEGRADED (not shippable).",
                skipped=True, degraded=True,
            )]
        try:
            disk = load_json(artifact)
            disk_verdict = str(disk.get("verdict", "")).lower() if isinstance(disk, dict) else ""
            disk_build = str(disk.get("buildId", "")) if isinstance(disk, dict) else ""
        except (json.JSONDecodeError, OSError):
            disk_verdict = ""
            disk_build = ""
        if disk_verdict != "pass":
            return [_ok(
                "visual_judge", False,
                f"metadata verdict=pass but visual-judge.json verdict={disk_verdict!r} "
                "— artifact missing/garbled/contradicting the self-report. "
                "DEGRADED (not shippable).",
                skipped=True, degraded=True,
            )]
        # Build-scope the artifact: a pass verdict left over from a PREVIOUS build
        # must not roll up green for this one. The judge writes buildId alongside
        # the verdict (integration-build Step 9c); absent or mismatched → DEGRADED.
        if disk_build != build_id:
            return [_ok(
                "visual_judge", False,
                f"metadata verdict=pass but visual-judge.json buildId={disk_build!r} "
                f"!= state buildId={build_id!r} — stale/unscoped judge artifact is "
                "not auditable for this build. DEGRADED (not shippable).",
                skipped=True, degraded=True,
            )]
        return [_ok(
            "visual_judge", True,
            f"design fidelity confirmed{f': {summary}' if summary else ''}",
        )]

    if verdict == "fail":
        return [_ok(
            "visual_judge", False,
            f"built app diverges from design intent{high_note}"
            f"{f': {summary}' if summary else ''} — DEGRADED (not shippable). "
            "Review .autobot/artifacts/visual-judge.json, fix the UI and "
            "/autobot:resume 5, or /autobot:resume 5 --allow-visual-drift to ship as-is.",
            skipped=True, degraded=True,
        )]

    # No usable verdict (absent or unrecognized). Anti-laundering: if a runtime
    # screenshot exists, fidelity WAS verifiable but the judge recorded nothing —
    # do not launder to VERIFIED. If no screenshot exists, the simulator was
    # unavailable, so design fidelity is genuinely not verifiable here → benign
    # skip (runtime_smoke already degrades the no-simulator case separately).
    screenshot_exists = (
        (proj / "artifacts" / build_id / "phase-5" / "runtime-smoke" / "screenshot.png").is_file()
        or (proj / ".autobot" / "phase-5" / "runtime-smoke" / "screenshot.png").is_file()
    )
    if screenshot_exists:
        reason = (
            f"unrecognized visual-judge verdict {verdict!r}" if verdict
            else "no visual-judge verdict on record"
        )
        return [_ok(
            "visual_judge", False,
            f"{reason} but a runtime screenshot exists — design fidelity unverified "
            "(integration-build Step 9 recorded no verdict). DEGRADED (not shippable).",
            skipped=True, degraded=True,
        )]
    return [_ok(
        "visual_judge", True,
        "skipped: no runtime screenshot (simulator unavailable) — fidelity not verifiable here",
        skipped=True,
    )]


def check_runtime_smoke(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 5→6 — boot a simulator, install the .app, launch it, confirm the
    process stays alive a few seconds, and capture a screenshot.

    Skips are DEGRADED (shipping-blocked), not benign: a build whose app was
    never launched must not roll up as a clean pass ("the binary compiled" is
    not "the app starts"). The ONLY benign skip is the explicit CI opt-out
    `AUTOBOT_DISABLE_SIMULATOR=1` — an operator decision, not a missing
    resource. Hard failures (boot/install/launch/process-death) fail the gate.
    """
    from sim_runtime import smoke

    result = smoke(proj, app)
    status = result.get("status")
    if status == "skipped":
        reason = result.get("skipReason", "unknown")
        if os.environ.get("AUTOBOT_DISABLE_SIMULATOR") == "1":
            return [_ok(
                "runtime_smoke", True,
                f"skipped: {reason} (explicit AUTOBOT_DISABLE_SIMULATOR opt-out)",
                skipped=True,
            )]
        return [_ok(
            "runtime_smoke", False,
            f"skipped (degraded): {reason} — the app was never launched, so "
            f"this build cannot roll up as a clean pass",
            skipped=True, degraded=True,
        )]
    if status == "passed":
        screenshot = result.get("screenshotPath") or "no screenshot"
        provenance = result.get("artifactDigest") or "missing"
        return [_ok(
            "runtime_smoke", True,
            f"app launched on {result.get('udidSource')} — {result.get('processDetail')} "
            f"— artifact {provenance[:12]} — screenshot: {screenshot}",
        )]
    return [_ok(
        "runtime_smoke", False,
        f"runtime smoke failed: {result.get('reason', 'unknown')}",
    )]


def check_metadata_readiness(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — App Store / TestFlight metadata is ready before archive.

    Skipped on the /autobot:mvp path (no ASC) so local builds aren't blocked;
    hard-required on the /autobot:testflight path (ascConfigured=true).
    """
    from metadata_validator import evaluate

    env = state.get("environment") or {}
    result = evaluate(proj, asc_configured=bool(env.get("ascConfigured")))
    status = result.get("status")
    if status == "skipped":
        reason = result.get("skipReason", "unknown")
        if reason == "metadata_gate_disabled":
            # Env kill-switch (e.g. left in a shell profile) must not roll up
            # as a benign skip with zero audit trail — DEGRADED blocks shipping.
            return [_ok(
                "metadata_readiness", False,
                "AUTOBOT_DISABLE_METADATA_GATE=1 — metadata validation disabled "
                "by env kill-switch. DEGRADED (not shippable); unset the env var "
                "or fix the metadata instead.",
                skipped=True, degraded=True,
            )]
        return [_ok(
            "metadata_readiness", True,
            f"skipped: {reason}",
            skipped=True,
        )]
    if status == "passed":
        counts = result.get("screenshotCounts") or {}
        total_shots = sum(counts.values())
        return [_ok(
            "metadata_readiness", True,
            f"locale={result.get('locale')} category={result.get('category')} "
            f"age={result.get('age_rating')} export={result.get('export_compliance')} "
            f"screenshots={total_shots}",
        )]
    return [_ok(
        "metadata_readiness", False,
        f"metadata not ready for upload: {result.get('reason', 'unknown')}",
    )]


def check_app_uses_real_repositories(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — production wiring must not instantiate preview stubs.

    Scans ALL of ``{app}/App/*.swift`` (entry point AND CompositionRoot — stub
    wiring moved to another composition file must not slip through), except
    ``ServiceStubs.swift`` itself (that file legitimately defines the preview
    stubs). Comments AND string literals are stripped first (strip_swift_noncode),
    so a `// previews use ServiceStubs` comment or a `"MockRepo()"` string can no
    longer hard-fail the gate (false-positive breaker risk). The denylist covers
    the common stub-naming conventions, not just ``Stub`` — an in-memory store
    renamed ``InMemoryRepository()`` must not ship as production wiring.

    ``has_real_services`` requires an INSTANTIATION (``FooRepository(``), not a
    bare type annotation (``var repo: ItemRepository?``); ``has_model_container``
    runs on the SAME comment/string-stripped App/*.swift union (documented
    contract puts production wiring in CompositionRoot.swift, not only the entry
    file), so a `// TODO: wire FooRepository` comment cannot satisfy them.
    """
    app_dir = proj / app / "App"
    stub_call = re.compile(r"\b(Stub|Mock|Fake|InMemory|Dummy|Preview)[A-Z]\w*\s*\(")
    violations: list[str] = []
    stripped_sources: list[str] = []
    swift_files = sorted(app_dir.glob("*.swift")) if app_dir.is_dir() else []
    for swift in swift_files:
        if swift.name == "ServiceStubs.swift":
            continue  # preview-stub definitions live here by contract
        try:
            source = swift.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Strip comments AND string literals before scanning — this is a
        # HARD-FAIL check, so a commented-out or stringified Stub call must
        # never trip it. Newlines are preserved to keep line numbers accurate.
        source = strip_swift_noncode(source)
        for lineno, line in enumerate(source.splitlines(), 1):
            if stub_call.search(line):
                violations.append(f"{swift.name}:{lineno}")
        stripped_sources.append(source)
    if violations:
        detail = ", ".join(violations[:5])
        no_stubs = _ok(
            "no_stubs_in_app", False,
            f"Stub/Mock/Fake/InMemory instantiation in production composition: {detail}",
        )
    elif not swift_files:
        no_stubs = _ok("no_stubs_in_app", False, f"MISSING: {app_dir}/*.swift")
    else:
        no_stubs = _ok(
            "no_stubs_in_app", True,
            f"no stub-family instantiations in {len(swift_files)} App/*.swift file(s)",
        )
    combined = "\n".join(stripped_sources)
    # Require instantiation `\bXxxRepository(` / `\bXxxService(`, not a bare
    # `var repo: ItemRepository?` type annotation — the composition root MUST
    # construct the real service, so a type reference alone is not production wiring.
    has_services = bool(re.search(r"\b[A-Z]\w*(?:Repository|Service)\s*\(", combined))
    has_container = bool(re.search(r"ModelContainer", combined, re.IGNORECASE))
    scope = "App/*.swift (comments+strings stripped, ServiceStubs excluded)"
    return [
        no_stubs,
        _ok("has_real_services", has_services,
            f"{'matched' if has_services else 'no match'} instantiation "
            f"/[A-Z]\\w*(Repository|Service)\\(/ in {scope}"),
        _ok("has_model_container", has_container,
            f"{'matched' if has_container else 'no match'} /ModelContainer/ in {scope}"),
    ]


def check_service_stubs_preserved(proj: Path, app: str, state: dict) -> list[dict]:
    """Preview-only contract.

    ServiceStubs.swift keeps SwiftUI previews alive, but production safety is
    enforced separately by check_app_uses_real_repositories. Missing preview
    stubs should not hard-fail Phase 5 or trip the build-fix circuit breaker.
    """
    path = proj / app / "App" / "ServiceStubs.swift"
    if path.is_file():
        return [_ok("stubs_for_preview", True, "ServiceStubs.swift preserved (preview contract)")]
    qmax = bool(state.get("qualityMax"))
    return [_ok(
        "stubs_for_preview",
        True,
        "ServiceStubs.swift absent — SwiftUI previews may break; app production wiring "
        "is checked separately"
        + (" — quality-max: DEGRADED" if qmax else ""),
        skipped=True,
        degraded=qmax,
    )]


def check_backend_deploy_readiness(proj: Path, app: str, state: dict) -> list[dict]:
    """For backend_required apps, is the Release build pointed at a real host?

    The scaffold writes ``Release.xcconfig`` as ``API_BASE_URL = https://$(PRODUCTION_HOST)``
    — a placeholder the operator must fill after deploying the server. If it's
    still the placeholder (or localhost, or empty) the shipped app's auth/AI calls
    fail — fatal for an AI/LLM app.

    Default mode: benign (the autonomous build legitimately ends pre-deploy;
    capability_coverage already reports the localhost caveat). quality-max:
    DEGRADED (shipping-blocked) — deterministic xcconfig check, NOT a hard fail.
    Skips entirely when the app needs no backend.
    """
    if not state.get("backend_required"):
        return [_ok("backend_deploy_readiness", True,
                    "backend not required", skipped=True)]
    qmax = bool(state.get("qualityMax"))
    rel = proj / "Release.xcconfig"
    if not rel.is_file():
        return [_ok("backend_deploy_readiness", True,
                    "backend_required but Release.xcconfig missing — cannot confirm deploy host",
                    skipped=True, degraded=qmax)]
    content = rel.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"API_BASE_URL\s*=\s*(.+)", content)
    val = m.group(1).strip() if m else ""
    not_ready = (not val) or ("localhost" in val) or ("$(PRODUCTION_HOST)" in val) or ("PRODUCTION_HOST" in val)
    if not_ready:
        return [_ok("backend_deploy_readiness", True,
                    f"Release API_BASE_URL not deploy-ready ({val or 'empty'}) — set PRODUCTION_HOST "
                    f"to the deployed server before shipping"
                    + (" — quality-max: DEGRADED" if qmax else ""),
                    skipped=True, degraded=qmax)]
    return [_ok("backend_deploy_readiness", True, f"Release API_BASE_URL points at {val}")]


def check_first_launch_seeded(proj: Path, app: str, state: dict) -> list[dict]:
    """Enforce the architect's seed policy on the built app.

    The architect classifies each app in ``.autobot/architecture.json`` as either
    ``seedPolicy: "seeded"`` (content/dashboard/social — a blank first launch reads
    as broken) or ``"empty"`` (todo/journal — a blank start is the whole point).

    When the policy is ``"seeded"``, the app entry point wired by quality-engineer
    (autobot-integration-build) MUST call the data-engineer's runtime seed factory
    so a fresh install lands on a populated primary screen. The contract function
    name is ``seedIfNeeded`` (data-engineer.md + wiring-patterns.md SSOT).

    ``"empty"`` and legacy builds with no seedPolicy field are skipped — a blank
    install is correct there and ``visual_contract`` only hard-fails fill when the
    idea actually asks for it, so empty apps are never penalised.
    """
    try:
        arch = load_json(proj / ".autobot" / "architecture.json") or {}
        policy = arch.get("seedPolicy")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        policy = None

    if policy != "seeded":
        return [_ok(
            "first_launch_seeded", True,
            f"seedPolicy={policy!r} — runtime seeding not required",
            skipped=True,
        )]

    app_dir = proj / app / "App"
    swift = sorted(app_dir.glob("*.swift")) if app_dir.is_dir() else []
    combined = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in swift)
    found = bool(re.search(r"seedIfNeeded", combined))
    return [_ok(
        "first_launch_seeded", found,
        f"seedPolicy=seeded → seedIfNeeded() {'found' if found else 'MISSING'} "
        f"in {app}/App/*.swift",
    )]


def check_no_swallowed_errors(proj: Path, app: str, state: dict) -> list[dict]:
    """Gate 5→6 — `try?` / `try!` in ViewModels/Services swallow errors.

    The agent prompts (ui-builder/data-engineer/quality-engineer) declare
    "zero new try?/try!" as a checklist item; this is the runtime enforcement
    of that prose contract (dead-policy elimination). A ViewModel that renders
    a load failure as an empty list shows the user "no data" instead of an
    error state — a quality defect, not a crash.

    DEGRADED-only, NEVER a hard fail (heuristic grep — a hard fail could trip
    the circuit breaker on a false positive and halt the autonomous build).
    DEGRADED still blocks shipping via the anti-laundering path. Comment lines
    are excluded; `#Preview` blocks are not parsed (known ceiling).
    """
    # ponytail: line-based grep, no Swift parsing — upgrade to a syntax-aware
    # scan only if preview-block false positives show up in real builds.
    pattern = re.compile(r"\btry[?!]")
    violations: list[str] = []
    for sub in ("ViewModels", "Services"):
        root = proj / app / sub
        if not root.is_dir():
            continue
        for swift in sorted(root.rglob("*.swift")):
            try:
                lines = swift.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                if line.strip().startswith("//"):
                    continue
                if pattern.search(line):
                    violations.append(f"{swift.relative_to(proj)}:{lineno}")
    if not violations:
        return [_ok(
            "no_swallowed_errors", True,
            "no try?/try! in ViewModels/Services (errors surface to the UI)",
        )]
    detail = ", ".join(violations[:5])
    if len(violations) > 5:
        detail += f" (+{len(violations) - 5} more)"
    return [_ok(
        "no_swallowed_errors", False,
        f"{len(violations)} try?/try! occurrence(s) swallow errors in "
        f"ViewModels/Services: {detail} — replace with do/catch surfacing an "
        f"errorMessage state. DEGRADED (not shippable, not a hard fail).",
        skipped=True, degraded=True,
    )]
