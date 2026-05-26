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
