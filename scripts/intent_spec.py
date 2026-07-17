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
    # Spatial / visual postconditions. The original six are all data-state
    # deltas — there was no grammar for "the UI must LOOK like X / FILL the
    # screen", so layout/fidelity requirements (e.g. "탭없이 화면을 꽉 채우는")
    # had nowhere to live and silently dropped to un-checked P2 stubs. These
    # let a layout requirement be a first-class, runtime-checkable acceptance.
    "occupies_screen_fraction",   # params: {min: 0..1, axis: "both"|"width"|"height"}
    "matches_visual_reference",   # params: {reference: "<path or design clause>"}
)

_POLICED_PRIORITIES = ("P0", "P1")
# The complete priority enum. A value outside this set (a "P3" typo, an empty
# string) is not "unpoliced" — it silently bypasses EVERY P0/P1/P2 rule, so
# structural validation rejects it (hard, same level as the other structure checks).
VALID_PRIORITIES = ("P0", "P1", "P2")

# Feature roles (cross-agent contract): why each feature exists in the plan.
# Required on P0/P1 by the architect prompt; absence is tolerated as legacy
# (warning, never a fail) so pre-role specs keep building.
FEATURE_ROLES = ("table-stakes", "hook", "retention", "insight")

# Depth floors for Gate 1->2 `feature_spec_depth`. Policy thresholds, not
# invariants — kept in one dict so the gate message can print the current
# values and a policy change never hides inside a comparison.
DEPTH_THRESHOLDS = {
    "min_p0_p1_features": 5,
    "min_p0_p1_features_quality_max": 7,
    "min_p0_features": 2,
    "min_distinct_screens": 3,
    "min_postcondition_kinds": 3,
}

# Keyword families (KR + EN) that signal the user asked for a SPECIFIC layout /
# screen-occupancy / fidelity property — the class of requirement the CRUD
# postconditions cannot express. Guarded so we never impose a layout acceptance
# on an app that didn't ask for one.
# NOTE on narrowness: these must fire ONLY on a true layout/fill/fidelity
# clause. A bare `fill` / `그대로` / `픽셀` is far too common in unrelated ideas
# ("fill out the form", "메모를 그대로 저장", "픽셀 아트 드로잉") — a false match
# forces a bogus occupies_screen_fraction P0 at gate 1->2 (HARD FAIL if the
# architect omits it) and a 0.6 fill floor at gate 5->6 (UNVERIFIED), halting an
# app that never asked to fill the screen. So `그대로`/`픽셀` are admitted only in
# an explicit layout context, and `fill` only as `fill(s) [the] screen`.
_LAYOUT_INTENT_PATTERNS = (
    r"꽉\s*찬", r"꽉\s*채", r"가득", r"전체\s*화면", r"화면.{0,6}채",
    r"풀\s*스크린", r"full[\s-]?screen", r"fills?\s+(?:the\s+)?screen",
    r"edge[\s-]?to[\s-]?edge", r"전체를\s*차지",
    r"(?:화면|UI|레이아웃|디자인|스킨|모양)\s*[를을]?\s*.{0,4}그대로",
    r"픽셀\s*(?:완벽|단위|동일|충실|퍼펙트)",
    r"pixel[\s-]?(?:perfect|exact)",
    # `exactly like` is a fidelity clause ("looks exactly like Winamp"); the
    # `exactly the` branch was dropped — it fired on "save exactly the same data".
    r"exact(?:ly)?\s+like",
)
_LAYOUT_POSTCONDITION_KINDS = ("occupies_screen_fraction", "matches_visual_reference")


def layout_intent_signal(*texts: str) -> str | None:
    """Return the first matched layout-intent phrase across `texts`, or None.

    A non-None result means the user's own words asked for a screen-occupancy /
    pixel-fidelity property — so the build must ENCODE that as an acceptance
    (gate 1->2) and VERIFY it on the screen (gate 5->6 occupancy), rather than
    letting it evaporate into prose nobody checks.
    """
    import re as _re
    for text in texts:
        if not text:
            continue
        for pat in _LAYOUT_INTENT_PATTERNS:
            m = _re.search(pat, text, _re.IGNORECASE)
            if m:
                return m.group(0)
    return None


# Keyword families (KR + EN) that signal the idea involves free-text entry
# (search / notes / logging / input). Sibling of _LAYOUT_INTENT_PATTERNS, but
# advisory-only: a match never forces an acceptance, it only warns when no
# flow acceptance exercises a text_input step.
_INPUT_INTENT_PATTERNS = (
    r"검색", r"메모", r"기록", r"입력",
    r"\badd\b", r"\bsearch\b", r"\blog\b",
)


def input_intent_signal(*texts: str) -> str | None:
    """Return the first matched text-entry-intent phrase across `texts`, or None.

    A non-None result means the user's own words imply typing (search box,
    note body, logging an entry) — so a spec whose flows never use a
    text_input step leaves the core interaction unproven at Gate 5->6.
    """
    for text in texts:
        if not text:
            continue
        for pat in _INPUT_INTENT_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(0)
    return None


def _raw_idea(project_root: Path) -> str:
    """The user's verbatim one-line idea, the SSOT oracle for what was asked.

    Read from build-state.json `idea`; fall back to app-intent.json `promise`.
    """
    state = project_root / ".autobot" / "build-state.json"
    if state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            idea = data.get("idea")
            if isinstance(idea, str) and idea.strip():
                return idea
        except (json.JSONDecodeError, OSError):
            pass
    intent = load_app_intent(project_root)
    return intent.promise if intent else ""


def assess_idea_layout_capture(project_root: Path) -> tuple[bool, list[str]]:
    """Gate 1->2 INTAKE check — catch the requirement-capture loss at the source.

    If the user's verbatim idea contains an explicit layout / screen-occupancy /
    pixel-fidelity clause, the feature-spec MUST encode at least one acceptance
    with a spatial postcondition (occupies_screen_fraction / matches_visual_
    reference). Otherwise the requirement that defines the app ("화면을 꽉 채우는")
    has no carrier and will never be checked — exactly how the 13%-of-screen
    Winamp shipped with every gate green.

    Returns (ok, problems). Benign-passes (ok=True) when no layout clause is
    detected — we never force a layout acceptance on an app that didn't ask.
    """
    signal = layout_intent_signal(_raw_idea(project_root))
    if signal is None:
        return True, []

    features = load_feature_spec(project_root)
    if not features:
        return False, [
            f"idea has a layout/fidelity clause ('{signal}') but feature-spec.json "
            f"is absent — it must carry it as an acceptance"
        ]
    for feat in features:
        for acc in feat.acceptance:
            if acc.postcondition.kind in _LAYOUT_POSTCONDITION_KINDS:
                return True, []
    return False, [
        f"idea explicitly asks for a layout/screen-fill/fidelity property "
        f"('{signal}') but NO feature acceptance encodes it (need a postcondition "
        f"kind in {list(_LAYOUT_POSTCONDITION_KINDS)}, e.g. occupies_screen_fraction "
        f"{{min:0.85, axis:'both'}}). Without it the look/fill requirement is never "
        f"verified — add a P0 feature acceptance that carries it."
    ]


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
    role: str = ""  # one of FEATURE_ROLES; "" = legacy spec (pre-role)

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
            role=str(data.get("role") or ""),
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

    Every feature's priority must be a valid enum value (P0/P1/P2) — an unknown
    value bypasses every downstream rule. Every P0/P1 feature must declare >=1
    acceptance criterion AND a non-empty anchor. P2 features are not policed
    (they may be aspirational stubs).
    """
    features = load_feature_spec(project_root)
    if features is None:
        return False, ["feature-spec.json absent or unparseable"]

    problems: list[str] = []
    for feat in features:
        label = feat.id or "<unnamed feature>"
        if feat.priority not in VALID_PRIORITIES:
            problems.append(
                f"{label}: invalid priority {feat.priority!r} "
                f"(allowed: {', '.join(VALID_PRIORITIES)})"
            )
            continue
        if feat.priority not in _POLICED_PRIORITIES:
            continue
        if not feat.acceptance:
            problems.append(f"{label} ({feat.priority}): no acceptance criteria")
        if not feat.anchor:
            problems.append(f"{label} ({feat.priority}): empty anchor")
    return (not problems), problems


def assess_feature_spec_quality(project_root: Path) -> tuple[bool, list[str]]:
    """Quality assessment for Gate 1->2 — returns (ok, problems).

    Three rules:

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
    3. At least one P0 feature must exist. Every flow-enforcement rule above is
       keyed on P0 presence (P1 flow failures only warn), so an all-P1/P2 spec
       would let every flow fail and STILL earn the VERIFIED badge — the
       zero-P0 laundering hole. Counting P0 features is deterministic, so this
       is safe as a gate 1->2 hard fail.

    P2 title/screen grounding is NOT policed here — it lives in
    assess_feature_spec_depth (DEGRADED-default), so a missing P2 title cannot
    hard-fail Gate 1->2 (which would only pressure the architect to omit P2s
    entirely — a Goodhart trap).
    """
    features = load_feature_spec(project_root)
    if features is None:
        return False, ["feature-spec.json absent or unparseable"]

    problems: list[str] = []
    if not any(feat.priority == "P0" for feat in features):
        problems.append(
            "no P0 feature declared — every feature is P1/P2, so no flow is "
            "ever enforced at Gate 5->6 (P1 failures only warn) and the "
            "VERIFIED badge would be laundered. Declare at least one P0 "
            "feature with a kind:'flow' acceptance."
        )
    for feat in features:
        label = feat.id or "<unnamed feature>"
        if feat.priority not in _POLICED_PRIORITIES:
            continue
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


def assess_feature_spec_depth(
    project_root: Path, *, quality_max: bool = False,
) -> dict:
    """Depth / composition floor for Gate 1->2 ``feature_spec_depth``.

    This measures "is there enough plan", never "is the plan attractive" —
    counts are deterministic and gameable with filler, so real depth stays
    owned by the architect prompt self-checks and the /plan critique; this
    only stops the bottom falling out. Returns verdict buckets the gate maps
    onto severities:

      hard_problems : one-tap degenerate spec (P0 == 1 AND total acceptance
                      steps <= 2) — a demo, not a plan; hard even in default
                      mode (same deterministic class as the zero-P0 rule).
      problems      : DEPTH_THRESHOLDS shortfalls + role composition
                      (hook >= 1, retention >= 1 among P0/P1) + P2 grounding
                      (non-empty title AND screen) — DEGRADED in default mode,
                      hard fail under quality-max.
      advisories    : journey depth (>= 1 multi-step flow), input-intent
                      (idea implies typing but no text_input step),
                      setting_stored without a P0/P1-flow persistence pair,
                      P0/P1 features missing a role while others declare one,
                      P0 flow navigated_to acceptances using allow_preexisting,
                      P2 > P0+P1 downgrade pressure — warning in default mode,
                      DEGRADED under quality-max.
      p2_features   : declared P2 ids (quality-max downgrade pressure row).
      metrics       : measured counts for the gate message.

    Back-compat: a spec with NO role fields at all is legacy — composition is
    reported as an advisory, never a problem.
    """
    features = load_feature_spec(project_root)
    if features is None:
        return {
            "hard_problems": [],
            "problems": ["feature-spec.json absent or unparseable"],
            "advisories": [],
            "p2_features": [],
            "metrics": {},
        }

    policed = [f for f in features if f.priority in _POLICED_PRIORITIES]
    p0 = [f for f in policed if f.priority == "P0"]
    p2_ids = [f.id or "<unnamed>" for f in features if f.priority == "P2"]
    screens = {f.screen.strip() for f in policed if f.screen.strip()}
    kinds = {
        a.postcondition.kind
        for f in policed for a in f.acceptance
        if a.postcondition.kind
    }
    total_steps = sum(len(a.steps) for f in policed for a in f.acceptance)
    flow_accs = [a for f in policed for a in f.acceptance if a.kind == "flow"]

    min_p0_p1 = DEPTH_THRESHOLDS[
        "min_p0_p1_features_quality_max" if quality_max else "min_p0_p1_features"
    ]

    problems: list[str] = []
    if len(policed) < min_p0_p1:
        problems.append(f"P0+P1 features {len(policed)} < {min_p0_p1}")
    if len(p0) < DEPTH_THRESHOLDS["min_p0_features"]:
        problems.append(
            f"P0 features {len(p0)} < {DEPTH_THRESHOLDS['min_p0_features']}"
        )
    if len(screens) < DEPTH_THRESHOLDS["min_distinct_screens"]:
        problems.append(
            f"distinct P0/P1 screens {len(screens)} < "
            f"{DEPTH_THRESHOLDS['min_distinct_screens']}"
        )
    if len(kinds) < DEPTH_THRESHOLDS["min_postcondition_kinds"]:
        problems.append(
            f"distinct postcondition kinds {len(kinds)} < "
            f"{DEPTH_THRESHOLDS['min_postcondition_kinds']}"
        )

    # P2 grounding (moved here from feature_spec_quality): a name-less/screen-less
    # P2 is the zero-cost hole hard features evaporate into. DEGRADED-default,
    # hard under quality-max — not a Gate 1->2 hard fail that would only pressure
    # the architect to drop P2s entirely (Goodhart).
    for feat in features:
        if feat.priority != "P2":
            continue
        label = feat.id or "<unnamed feature>"
        if not feat.title.strip():
            problems.append(
                f"{label} (P2): empty title — even a deferred stub must be a "
                f"named feature"
            )
        if not feat.screen.strip():
            problems.append(
                f"{label} (P2): empty screen — ground every P2 to a screen so it "
                f"stays a designed deferral, not an evaporation"
            )

    advisories: list[str] = []
    declared_roles = [f.role for f in policed if f.role]
    invalid_roles = sorted({r for r in declared_roles if r not in FEATURE_ROLES})
    if invalid_roles:
        problems.append(
            f"invalid role value(s) {invalid_roles} "
            f"(allowed: {', '.join(FEATURE_ROLES)})"
        )
    if not declared_roles:
        advisories.append(
            "no feature declares a role — legacy spec: hook/retention "
            "composition unverifiable (declare role on every P0/P1)"
        )
    else:
        # Roles are in use: a P0/P1 feature missing one is a real gap, not a
        # fully-legacy spec. The old "any role present ⇒ treat all as migrated"
        # heuristic let those silently pass; surface them as an advisory
        # (warn-default, DEGRADED under quality-max).
        missing_role = [f.id or "<unnamed>" for f in policed if not f.role]
        if missing_role:
            advisories.append(
                f"P0/P1 feature(s) {missing_role} declare no role while others do "
                f"— assign a role ({', '.join(FEATURE_ROLES)}) to every P0/P1"
            )
        if not any(f.role == "hook" for f in policed):
            problems.append(
                "no P0/P1 feature with role 'hook' — nothing gives a reason "
                "to download over the category-standard app"
            )
        if not any(f.role == "retention" for f in policed):
            problems.append(
                "no P0/P1 feature with role 'retention' — nothing gives a "
                "reason to come back"
            )

    hard_problems: list[str] = []
    if len(p0) == 1 and total_steps <= 2:
        hard_problems.append(
            f"degenerate spec: exactly 1 P0 feature with {total_steps} total "
            f"acceptance step(s) — a one-tap demo, not a plan; add features "
            f"and multi-step journeys"
        )

    if flow_accs and not any(len(a.steps) >= 2 for a in flow_accs):
        advisories.append(
            "every flow acceptance is single-step — declare at least one "
            "multi-step journey (steps >= 2, e.g. input -> confirm)"
        )

    signal = input_intent_signal(_raw_idea(project_root))
    if signal is not None and not any(
        str(s.get("action") or "") == "text_input"
        for a in flow_accs for s in a.steps
    ):
        advisories.append(
            f"idea implies text entry ('{signal}') but no flow acceptance "
            f"uses a text_input step — the core interaction is never typed "
            f"at Gate 5->6"
        )

    # Persistence pairing is only proven when BOTH sides live in an enforced
    # (P0/P1 flow) acceptance — a value_persisted pair parked on a P2 or a
    # logic-only acceptance is never driven at Gate 5->6, so it does not count.
    flow_kinds = {a.postcondition.kind for a in flow_accs}
    if (
        "setting_stored" in flow_kinds
        and "value_persisted_after_relaunch" not in flow_kinds
    ):
        advisories.append(
            "setting_stored acceptance(s) without a "
            "value_persisted_after_relaunch pair in a P0/P1 flow — persistence "
            "across relaunch is unproven"
        )

    # allow_preexisting waives navigated_to's novelty proof (legit for tab-bar
    # roots, but it lets a static stub pass). Count its use on P0 flows so the
    # bypass is auditable: warn-default, DEGRADED under quality-max.
    preexisting_p0 = sum(
        1
        for f in p0
        for a in f.acceptance
        if a.kind == "flow"
        and a.postcondition.kind == "navigated_to"
        and a.postcondition.params.get("allow_preexisting")
    )
    if preexisting_p0:
        advisories.append(
            f"{preexisting_p0} P0 flow navigated_to acceptance(s) use "
            f"allow_preexisting — the novelty proof is waived; confirm the "
            f"anchor is a genuine tab-bar root, not a static stub"
        )

    if len(p2_ids) > len(policed):
        advisories.append(
            f"P2 features ({len(p2_ids)}) outnumber P0+P1 ({len(policed)}) — "
            f"downgrade pressure: hard features may be evaporating into "
            f"unpoliced P2"
        )

    return {
        "hard_problems": hard_problems,
        "problems": problems,
        "advisories": advisories,
        "p2_features": p2_ids,
        "metrics": {
            "p0_p1": len(policed),
            "p0": len(p0),
            "p2": len(p2_ids),
            "screens": len(screens),
            "postcondition_kinds": len(kinds),
            "total_steps": total_steps,
        },
    }


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
