"""iOS 26 capability + AppIntent + primary-CTA visibility checks.

Carved out of scripts/gate_runner.py during the gate_checks package split.
All check signatures: ``(project_dir: Path, app: str, state: dict) -> list[dict]``.
"""
from __future__ import annotations

import json
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
    _agent_writes_dirs
)


_IOS26_SYMBOLS = (
    (re.compile(r"\bimport\s+FoundationModels\b"), "FoundationModels framework"),
    (re.compile(r"\b@Generable\b"), "@Generable macro"),
    (re.compile(r"\bLanguageModelSession\b"), "LanguageModelSession"),
    (re.compile(r"\bSystemLanguageModel\b"), "SystemLanguageModel"),
    (re.compile(r"\.glassEffect\("), "Liquid Glass .glassEffect()"),
    (re.compile(r"\bGlassEffectContainer\b"), "GlassEffectContainer"),
    (re.compile(r"\bWritingToolsCoordinator\b"), "WritingToolsCoordinator"),
    (re.compile(r"\bAlarmKit\b"), "AlarmKit"),
)


def _parse_ios_major(target: str | None) -> int | None:
    """Extract the major version number from a deployment target like '26.0'."""
    if not isinstance(target, str):
        return None
    match = re.match(r"\s*(\d+)", target)
    return int(match.group(1)) if match else None


def _has_available_guard_above(lines: list[str], hit_line: int, *, window: int = 6) -> bool:
    """Return True if any of the `window` lines above contains an iOS 26 `#available` guard."""
    start = max(0, hit_line - window)
    for line in lines[start:hit_line]:
        if re.search(r"#available\([^)]*iOS\s+26", line):
            return True
        if re.search(r"@available\([^)]*iOS\s+26", line):
            return True
    return False


def check_app_intent_declared(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 1→2 — architect must promise something concrete enough to test.

    Soft when `app-intent.json` is absent (legacy build), strict when present
    but missing required fields.
    """
    from intent_spec import load_app_intent, validate_manifest

    intent = load_app_intent(proj)
    if intent is None:
        return [_ok(
            "app_intent_declared", True,
            ".autobot/app-intent.json absent — skipping (legacy build)",
            skipped=True,
        )]
    ok, problems = validate_manifest(proj)
    if ok:
        return [_ok(
            "app_intent_declared", True,
            f"promise='{intent.promise[:60]}', primaryCTA='{intent.primary_cta}', "
            f"{len(intent.required_anchors)} anchors",
        )]
    return [_ok(
        "app_intent_declared", False,
        f"app-intent.json invalid: {'; '.join(problems)}",
    )]


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


def check_intent_anchors_in_ui(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 4→5 — every anchor the architect promised must appear in the UI tree.

    Without this, the UI test target launched at Phase 5 cannot find the views
    it is supposed to assert against, and runtime-smoke can pass while the
    actual happy path is broken.
    """
    from intent_spec import find_unused_anchors, load_app_intent

    intent = load_app_intent(proj)
    if intent is None:
        return [_ok(
            "intent_anchors_in_ui", True,
            "app-intent.json absent — skipping",
            skipped=True,
        )]
    missing, present = find_unused_anchors(proj, app)
    if not missing:
        return [_ok(
            "intent_anchors_in_ui", True,
            f"all {len(present)} required anchors present in UI tree",
        )]
    return [_ok(
        "intent_anchors_in_ui", False,
        f"missing accessibility identifiers in UI: {', '.join(missing)} "
        f"(present: {', '.join(present) or 'none'})",
    )]


def check_primary_cta_visibility(proj: Path, app: str, state: dict) -> list[dict]:
    """Phase 4→5 — primary CTAs must remain visible in their disabled state.

    Regression captured in build-20260526-solos: the Onboarding "시작하기" CTA
    used `.background(canContinue ? Theme.primary : Theme.surface)` and rendered
    as the page background when no nickname was typed — first-time users
    couldn't see the only forward path. `app_intent_declared` and
    `intent_anchors_in_ui` only verify the identifier exists; neither catches
    the contrast collision.

    Heuristic: locate every `.accessibilityIdentifier("autobot.*primaryCTA…")`
    in Views/ and reject the surrounding block when its disabled-state
    background ties to `Theme.surface` / `Theme.background` (page surface
    colors). The rule lives at file level, not the strict enclosing Button
    scope, to keep the regex simple while still catching the recurring bug.
    """
    views = proj / app / "Views"
    if not views.is_dir():
        return [_ok(
            "primary_cta_visibility", True,
            "no Views/ dir — skipping",
            skipped=True,
        )]

    anchor_pat = re.compile(r'\.accessibilityIdentifier\("autobot\.[a-zA-Z.]*primaryCTA[a-zA-Z.]*"\)')
    # Conservative disabled-state-collision pattern: a ternary background that
    # resolves to Theme.surface / Theme.background in the off branch. Use
    # non-greedy `.*?` (no DOTALL) so we walk only within the line, but still
    # skip past nested `Color("Theme/Primary")` parens in the truthy branch.
    surface_collision = re.compile(
        r'\.background\(.*?:\s*(Theme\.(?:surface|background)|Color\(\s*"Theme/(?:Surface|Background)"\s*\))'
    )

    offenders: list[str] = []
    anchors_seen = 0
    for swift in views.rglob("*.swift"):
        try:
            text = swift.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not anchor_pat.search(text):
            continue
        anchors_seen += 1
        if surface_collision.search(text):
            offenders.append(str(swift.relative_to(proj)))

    if anchors_seen == 0:
        return [_ok(
            "primary_cta_visibility", True,
            "no primary CTA anchor found — skipping",
            skipped=True,
        )]
    if offenders:
        return [_ok(
            "primary_cta_visibility", False,
            "primary CTA disabled-state background ties to page surface (invisible button risk): "
            + ", ".join(offenders),
        )]
    return [_ok(
        "primary_cta_visibility", True,
        f"{anchors_seen} primary CTA anchor(s) inspected — no surface-collision pattern detected",
    )]


def check_ios_capability_safe(proj: Path, app: str, state: dict) -> list[dict]:
    """Verify iOS 26+ APIs are either supported by the deployment target or
    properly `#available(iOS 26, *)` guarded.

    Soft when `architecture.json` is absent — Phase 1 may pre-date the
    capability manifest contract.
    """
    arch_json = proj / ".autobot" / "architecture.json"
    deployment_major: int | None = None
    if arch_json.is_file():
        try:
            data = load_json(arch_json)
            caps = data.get("iosCapabilities") if isinstance(data, dict) else None
            if isinstance(caps, dict):
                deployment_major = _parse_ios_major(caps.get("deploymentTarget"))
        except (json.JSONDecodeError, OSError):
            pass

    # No manifest → skip (architect output predates this gate).
    if deployment_major is None:
        return [_ok(
            "ios_capability_safe", True,
            "architecture.json missing iosCapabilities — skipping (legacy build)",
            skipped=True,
        )]

    # Deployment target already covers iOS 26 → no guards required.
    if deployment_major >= 26:
        return [_ok(
            "ios_capability_safe", True,
            f"deploymentTarget=iOS {deployment_major} — modern APIs always available",
        )]

    # Lower deployment target → every iOS 26+ symbol must be guarded.
    app_root = proj / app
    if not app_root.is_dir():
        return [_ok("ios_capability_safe", True, "no app source tree yet", skipped=True)]

    unguarded: list[str] = []
    for swift in app_root.rglob("*.swift"):
        try:
            text = swift.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            for pattern, label in _IOS26_SYMBOLS:
                if pattern.search(line) and not _has_available_guard_above(lines, idx):
                    unguarded.append(
                        f"{swift.relative_to(proj)}:{idx+1}: {label} unguarded "
                        f"(deploymentTarget=iOS {deployment_major})"
                    )
                    break  # one finding per line is enough

    if unguarded:
        sample = "; ".join(unguarded[:3])
        more = f" (+{len(unguarded)-3} more)" if len(unguarded) > 3 else ""
        return [_ok("ios_capability_safe", False, f"{sample}{more}")]
    return [_ok(
        "ios_capability_safe", True,
        f"all iOS 26+ symbol usages are #available-guarded (target=iOS {deployment_major})",
    )]
