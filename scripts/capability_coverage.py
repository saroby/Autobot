#!/usr/bin/env python3
"""Capability Coverage — make the feature's limits LOUD instead of silent.

The /autobot:mvp evaluation found the worst user-harm is not bugs but SILENCE:
ambitious ideas are quietly narrowed to a medium-CRUD app, whole iOS categories
(StoreKit / WidgetKit / Push / Background / App Clips) are dropped without a
word, a backend_required app ships pointed at a non-existent localhost, the
"build locally" artifact is a simulator-only Debug build, and the VERIFIED
badge proves less than its name implies. None of that is a bug to "fix" by
building six new subsystems — the honest fix is to TELL the user, on the
completion screen, exactly what was and was not covered.

This module derives a structured coverage report from the build artifacts and
renders a `## Capability Coverage` section for run-summary. It reads only files
that already exist; everything degrades to "unknown"/empty when absent so it
never breaks summary generation.

    assess(project_root) -> dict      # structured coverage
    render(coverage)     -> str       # markdown section (no trailing newline)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


# ── iOS capabilities the pipeline never generates. If the idea / architecture
#    asks for one, the user should be told it was NOT built — not discover it
#    missing later. (Confirmed: no agent emits any of these.) ──
_UNSUPPORTED_CATEGORIES = [
    {
        "category": "In-app purchases / subscriptions (StoreKit)",
        "patterns": [r"storekit", r"in-?app purchase", r"\bIAP\b", r"subscription",
                     r"구독", r"인앱 ?결제", r"결제"],
    },
    {
        "category": "Home-screen widgets (WidgetKit)",
        "patterns": [r"widgetkit", r"\bwidget\b", r"위젯"],
    },
    {
        "category": "Push notifications (APNs / remote)",
        "patterns": [r"\bapns\b", r"push notification", r"remote notification", r"푸시"],
    },
    {
        "category": "Background tasks (BGTaskScheduler)",
        "patterns": [r"bgtaskscheduler", r"background task", r"background refresh", r"백그라운드"],
    },
    {
        "category": "App Clips",
        "patterns": [r"app ?clip", r"앱 ?클립"],
    },
    {
        "category": "Real-time / collaboration (WebSocket)",
        "patterns": [r"websocket", r"real-?time", r"실시간", r"collaborat", r"협업",
                     r"multiplayer", r"멀티플레이"],
    },
    {
        "category": "Cross-device sync (CloudKit)",
        "patterns": [r"cloudkit", r"icloud sync", r"sync across", r"기기 ?간", r"동기화",
                     r"across devices"],
    },
    {
        "category": "watchOS companion app",
        "patterns": [r"watchos", r"apple watch", r"애플 ?워치", r"워치 ?앱"],
    },
]

# Liquid-Glass / iOS-26-specific markers. If NONE appear in the generated Views,
# the "enterprise-grade iOS 26+" claim is unbacked and we say so (advisory).
_MODERN_API_MARKERS = [
    "glassEffect", "GlassEffectContainer", "glassBackgroundEffect",
    "backgroundExtensionEffect", "scrollEdgeEffect", ".tabRole",
]

# Hardcoded-color signals in Views (advisory — prefer design-system tokens).
_HARDCODED_COLOR_RE = re.compile(
    r"Color\(\s*red\s*:|UIColor\(|Color\(\.sRGB|Color\(hex", re.IGNORECASE
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _detect_unsupported(haystack: str) -> list[dict]:
    low = haystack.lower()
    hits: list[dict] = []
    for entry in _UNSUPPORTED_CATEGORIES:
        for pat in entry["patterns"]:
            m = re.search(pat, low)
            if m:
                hits.append({"category": entry["category"], "matched": m.group(0)})
                break
    return hits


def _out_of_scope_text(arch_md: str) -> str:
    """Lowercased body of the architecture's ``## Out of Scope`` section (or '')."""
    m = re.search(r"(?im)^#+\s*out of scope\s*$(.*?)(?=^#+\s|\Z)", arch_md, re.DOTALL)
    return m.group(1).lower() if m else ""


def _mark_acknowledged(hits: list[dict], arch_md: str) -> None:
    """Flag each unsupported hit the architect explicitly excluded.

    When the architect writes a ``## Out of Scope`` section naming an unsupported
    category, that's a deliberate exclusion (not a silent gap) — capability
    coverage reports it differently so the user sees "excluded by design" vs
    "requested but missing". Mutates *hits* in place, adding ``acknowledged``.
    """
    oos = _out_of_scope_text(arch_md)
    by_cat = {e["category"]: e["patterns"] for e in _UNSUPPORTED_CATEGORIES}
    for h in hits:
        pats = by_cat.get(h["category"], [])
        h["acknowledged"] = bool(oos) and any(re.search(p, oos) for p in pats)


def _verification_prereqs(env: dict) -> list[dict]:
    """Tool availability + actionable install hint for each verification prereq."""
    environment = (env or {}).get("environment") or {}
    sim = (env or {}).get("simulator")
    axe_present = bool(environment.get("axe"))
    return [
        {
            "tool": "AXe (UI automation)",
            "present": axe_present,
            "installHint": "brew install cameroncooke/axe/axe",
            "why": "drives functional flows; without it gate 5→6 degrades to UNVERIFIED",
        },
        {
            "tool": "iOS simulator",
            "present": sim is not None,
            "installHint": "open Xcode → Settings → Components → install an iOS 26 simulator runtime",
            "why": "boots/launches the app for runtime smoke + flows",
        },
    ]


def assess(project_root: Path) -> dict:
    root = Path(project_root)
    autobot = root / ".autobot"
    state = _load_json(autobot / "build-state.json")
    arch_md = _read_text(autobot / "architecture.md")
    env = _load_json(autobot / "env_snapshot.json")
    idea = str(state.get("idea") or "")
    app_name = str(state.get("appName") or "")

    # ── scope: downgraded (P2) features + requested-but-unbuilt categories ──
    downgraded: list[dict] = []
    try:
        from intent_spec import load_feature_spec
        for f in (load_feature_spec(root) or []):
            if f.priority == "P2":
                downgraded.append({"id": f.id, "title": f.title})
    except Exception:
        pass

    unsupported = _detect_unsupported(f"{idea}\n{arch_md}")
    _mark_acknowledged(unsupported, arch_md)

    backend_required = bool(state.get("backend_required"))
    backend = None
    if backend_required:
        backend = {
            "required": True,
            "deployed": False,
            "note": ("Backend code is generated under backend/ but NOT deployed. The app "
                     "points at a localhost URL until you deploy the server and update "
                     "Release.xcconfig — auth / AI calls will fail before then."),
        }

    # ── verification: badge + prereqs + honest depth caveats ──
    gate56 = (state.get("gates", {}).get("5->6") or {}).get("status")
    badge = "VERIFIED" if gate56 == "passed" else ("DEGRADED" if gate56 == "degraded" else "UNVERIFIED")
    prereqs = _verification_prereqs(env)
    depth_caveats = [
        "Flows are driven by tapping anchors only — text entry, scrolling and "
        "swipes are not exercised, so multi-input workflows are unproven.",
        "Only P0 flows block the build; P1 flow failures are recorded as warnings "
        "under a passing badge.",
        "navigated_to / artifact_generated / setting_stored assert an anchor is "
        "present after the tap, not that its underlying value changed.",
        "Each flow is checked once on a fresh launch on a single simulator.",
    ]

    # ── quality (advisory scan of generated Views) ──
    quality = _scan_views(root, app_name)

    return {
        "verification": {
            "badge": badge,
            "gate56Status": gate56,
            "prereqs": prereqs,
            "depthCaveats": depth_caveats,
        },
        "scope": {
            "downgradedFeatures": downgraded,
            "unsupportedRequested": unsupported,
            "backend": backend,
            "deviceDeployment": (
                "This is a Debug / simulator build. To run it on your own iPhone, open "
                "the project in Xcode and set a signing team (Signing & Capabilities); "
                "/autobot:testflight handles signed distribution."
            ),
        },
        "quality": quality,
        "iteration": (
            "There is no in-place edit command yet: to change the app, either edit the "
            "Swift directly in Xcode, or refine your idea and re-run /autobot:mvp (the "
            "build is regenerated from the one-line idea, not patched)."
        ),
    }


def _scan_views(root: Path, app_name: str) -> dict:
    """Advisory: do the generated Views use design tokens & any modern API?"""
    views_dir = root / app_name / "Views" if app_name else None
    if not views_dir or not views_dir.is_dir():
        return {"scanned": False}
    hardcoded = 0
    modern_used: set[str] = set()
    swift_files = list(views_dir.rglob("*.swift"))
    for f in swift_files:
        text = _read_text(f)
        hardcoded += len(_HARDCODED_COLOR_RE.findall(text))
        for marker in _MODERN_API_MARKERS:
            if marker in text:
                modern_used.add(marker)
    return {
        "scanned": True,
        "viewFiles": len(swift_files),
        "hardcodedColorHits": hardcoded,
        "modernApiMarkers": sorted(modern_used),
        "modernApiUsed": bool(modern_used),
    }


def _bullet(lines: list[str], text: str) -> None:
    lines.append(f"- {text}")


def render(coverage: dict) -> str:
    lines: list[str] = ["## Capability Coverage", ""]
    cov = coverage or {}

    # Verification prerequisites the user may be missing.
    ver = cov.get("verification") or {}
    missing = [p for p in (ver.get("prereqs") or []) if not p.get("present")]
    if missing:
        lines.append("**⚠️ Verification prerequisites missing — that is why the badge is not VERIFIED:**")
        for p in missing:
            lines.append(f"- `{p['tool']}` not found — install: `{p['installHint']}` ({p['why']})")
        lines.append("")

    # What "verified" does and does not prove.
    caveats = ver.get("depthCaveats") or []
    if caveats:
        lines.append("**What a VERIFIED badge does NOT prove:**")
        for c in caveats:
            _bullet(lines, c)
        lines.append("")

    scope = cov.get("scope") or {}
    downgraded = scope.get("downgradedFeatures") or []
    if downgraded:
        lines.append("**Features built as aspirational stubs (P2 — NOT runtime-verified):**")
        for f in downgraded:
            _bullet(lines, f"{f.get('title') or f.get('id')} (`{f.get('id')}`)")
        lines.append("")

    unsupported = scope.get("unsupportedRequested") or []
    unacknowledged = [u for u in unsupported if not u.get("acknowledged")]
    acknowledged = [u for u in unsupported if u.get("acknowledged")]
    if unacknowledged:
        lines.append("**Requested capabilities this build does NOT include "
                     "(not declared out of scope — silent gap):**")
        for u in unacknowledged:
            _bullet(lines, f"{u['category']} — detected in your idea/architecture (\"{u['matched']}\") but not generated")
        lines.append("")
    if acknowledged:
        lines.append("**Intentionally out of scope (architect declared in `## Out of Scope`):**")
        for u in acknowledged:
            _bullet(lines, f"{u['category']} — excluded by design")
        lines.append("")

    backend = scope.get("backend")
    if backend:
        lines.append(f"**Backend:** {backend['note']}")
        lines.append("")

    if scope.get("deviceDeployment"):
        lines.append(f"**On-device:** {scope['deviceDeployment']}")
        lines.append("")

    quality = cov.get("quality") or {}
    if quality.get("scanned"):
        if quality.get("hardcodedColorHits"):
            _bullet(lines, f"**Design tokens:** {quality['hardcodedColorHits']} hardcoded color literal(s) in "
                           f"Views — prefer the design-system tokens for a coherent palette.")
        if not quality.get("modernApiUsed"):
            _bullet(lines, "**iOS 26 look:** no Liquid-Glass / iOS-26-specific API detected in Views — "
                           "the app may look like a generic SwiftUI default.")
        lines.append("")

    if cov.get("iteration"):
        lines.append(f"**Changing the app:** {cov['iteration']}")
        lines.append("")

    if len(lines) <= 2:
        lines.append("_No coverage gaps detected._")
    return "\n".join(lines).rstrip()


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    proj = Path(args.project_dir).resolve()
    cov = assess(proj)
    print(json.dumps(cov, ensure_ascii=False, indent=2) if args.format == "json" else render(cov))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
