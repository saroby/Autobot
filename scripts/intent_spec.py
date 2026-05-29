#!/usr/bin/env python3
"""App Intent contract — the bridge between "what the architect promised the
user's idea would do" and "what actually shows up on screen".

The architect emits `.autobot/app-intent.json` next to `architecture.json`:

    {
      "appName": "FitnessTracker",
      "promise": "Track daily workouts and share progress with friends.",
      "primaryScreenTitle": "Today",
      "primaryCTA": "Log a Workout",
      "requiredAnchors": [
        "autobot.root",
        "autobot.primaryTitle",
        "autobot.primaryCTA"
      ],
      "happyPath": [
        {"id": "autobot.primaryCTA", "action": "tap"},
        {"id": "autobot.root", "action": "assertVisible"}
      ]
    }

Only `requiredAnchors` is hard-required — every other field is informational and
makes downstream skill agents (`ui-builder`, runtime-smoke summarization,
visual-contract reports) more concrete.

This module is reused by gate checks and by `ui-builder` skill helpers; both
import the loader / validator instead of duplicating schema knowledge.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_REQUIRED_ANCHORS = (
    "autobot.root",
    "autobot.primaryTitle",
    "autobot.primaryCTA",
)


@dataclass
class AppIntent:
    app_name: str
    promise: str
    primary_screen_title: str
    primary_cta: str
    required_anchors: tuple[str, ...]
    happy_path: tuple[dict, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict) -> "AppIntent":
        required = data.get("requiredAnchors") or list(DEFAULT_REQUIRED_ANCHORS)
        if not isinstance(required, list) or not required:
            required = list(DEFAULT_REQUIRED_ANCHORS)
        return cls(
            app_name=str(data.get("appName") or ""),
            promise=str(data.get("promise") or ""),
            primary_screen_title=str(data.get("primaryScreenTitle") or ""),
            primary_cta=str(data.get("primaryCTA") or ""),
            required_anchors=tuple(str(x) for x in required),
            happy_path=tuple(data.get("happyPath") or ()),
        )


def load_app_intent(project_root: Path) -> AppIntent | None:
    """Return the parsed intent, or None if the manifest is absent / unparseable."""
    path = project_root / ".autobot" / "app-intent.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return AppIntent.from_dict(data)


def validate_manifest(project_root: Path) -> tuple[bool, list[str]]:
    """Hard validation for Gate 1→2 — returns (ok, problems)."""
    intent = load_app_intent(project_root)
    if intent is None:
        return False, ["app-intent.json absent or unparseable"]

    problems: list[str] = []
    if not intent.app_name:
        problems.append("appName missing")
    if not intent.promise:
        problems.append("promise missing — describe what one-line value the app delivers")
    if not intent.primary_screen_title:
        problems.append("primaryScreenTitle missing")
    if not intent.primary_cta:
        problems.append("primaryCTA missing")
    if not intent.required_anchors:
        problems.append("requiredAnchors missing or empty")
    return (not problems), problems


def find_unused_anchors(project_root: Path, app_name: str) -> tuple[list[str], list[str]]:
    """Return (missing_anchors, present_anchors) for the Phase 4 UI source tree."""
    intent = load_app_intent(project_root)
    if intent is None:
        return [], []

    app_root = project_root / app_name
    if not app_root.is_dir():
        return list(intent.required_anchors), []

    missing: list[str] = []
    present: list[str] = []
    files = list((app_root / "Views").rglob("*.swift")) if (app_root / "Views").is_dir() else []
    # Also accept anchors declared in App/ (root composition) and ViewModels/.
    for extra_dir in ("App", "ViewModels"):
        path = app_root / extra_dir
        if path.is_dir():
            files.extend(path.rglob("*.swift"))

    combined = "\n".join(
        f.read_text(encoding="utf-8", errors="replace") for f in files
    )

    for anchor in intent.required_anchors:
        pattern = re.compile(
            rf'accessibilityIdentifier\(\s*"{re.escape(anchor)}"\s*\)'
            rf'|"{re.escape(anchor)}"\s*as\s+AccessibilityIdentifier'
            rf'|accessibilityIdentifier:\s*"{re.escape(anchor)}"'
        )
        if pattern.search(combined):
            present.append(anchor)
        else:
            missing.append(anchor)
    return missing, present


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

    Two rules:

    1. Every P0/P1 acceptance postcondition.kind must be one of
       POSTCONDITION_KINDS. An empty kind ("anchor-only" acceptance — it only
       asserts the anchor rendered, never that behavior occurred) is invalid: a
       postcondition is what makes the flow checkable at runtime.
    2. Every P0 feature must declare at least one ``kind == "flow"`` acceptance.
       Gate 5->6 only drives ``flow`` acceptances on a simulator via AXe; a
       logic-only P0 feature would let a build earn the VERIFIED badge while no
       UI flow ever runs — the "intact logic alone is enough" hole that makes a
       broken-UI app look verified. P1 is exempt because P1 flow failures only
       warn, never block, so requiring a P1 flow would add no enforced coverage.
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
        if feat.priority == "P0" and not any(a.kind == "flow" for a in feat.acceptance):
            problems.append(
                f"{label} (P0): no 'flow' acceptance — a P0 feature MUST declare "
                f"at least one kind:'flow' acceptance so its UI is driven on a "
                f"simulator at Gate 5->6 (logic-only acceptances are never clicked "
                f"at runtime, so the VERIFIED badge would not actually exercise the UI)"
            )
    return (not problems), problems


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


def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_v = sub.add_parser("validate")
    p_v.add_argument("--project-dir", required=True)
    p_a = sub.add_parser("anchors")
    p_a.add_argument("--project-dir", required=True)
    p_a.add_argument("--app-name", required=True)
    args = parser.parse_args()

    if args.cmd == "validate":
        ok, problems = validate_manifest(Path(args.project_dir).resolve())
        print(json.dumps({"ok": ok, "problems": problems}, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    missing, present = find_unused_anchors(
        Path(args.project_dir).resolve(), args.app_name
    )
    print(json.dumps(
        {"missing": missing, "present": present},
        ensure_ascii=False, indent=2,
    ))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(_main())
