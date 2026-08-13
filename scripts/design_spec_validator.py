#!/usr/bin/env python3
"""Promote `.autobot/design-spec.json` to the hard SSOT for visual contracts.

Until now, `design-spec.md` (prose) was the only artifact, and the visual
contract gate had to grep for `#RRGGBB` codes near a "Primary" header. That
works most of the time and silently passes when prose drifts. JSON makes
both the gate strict and the prose-only synthesis path deterministic.

Schema (the only fields the visual contract / ui-builder care about):

    {
      "version": 1,
      "appName": "...",
      "appCategory": "fitness|productivity|finance|food|...",
      "colorTokens": {
        "primary":   "#XXXXXX",
        "secondary": "#XXXXXX",
        "accent":    "#XXXXXX",
        "surface":   "#XXXXXX"
      },
      "typography": {
        "design": "rounded|default|serif",
        "headingWeight": "semibold|bold|heavy"
      },
      "spacing": {"base": 4, "card": 16, "section": 24},
      "primaryScreen": {
        "title": "...",
        "anchorAccessibilityIdentifier": "autobot.primaryTitle"
      },
      "visualAnchors": ["autobot.root", "autobot.primaryTitle", "autobot.primaryCTA"],
      "darkMode": true   // consumed by visual_contract._dark_mode_required:
                         // sim_runtime captures a dark-appearance screenshot and
                         // the gate verifies it; false opts the app out.
    }

Synthesis: when `design-spec.json` is missing but Phase 1 produced
`architecture.md` (with a Design Direction section) or Phase 2 produced
`design-spec.md`, this module derives a deterministic spec from the available
text. The synthesized spec is written to `design-spec.json` so the rest of
the pipeline can rely on it being there.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_ANCHORS = ("autobot.root", "autobot.primaryTitle", "autobot.primaryCTA")
ALLOWED_TYPO_DESIGN = ("rounded", "default", "serif")
ALLOWED_TYPO_WEIGHT = ("regular", "medium", "semibold", "bold", "heavy")

# Deterministic per-category fallback palette. Used only when neither
# design-spec.md nor architecture.md surfaces a primary color hex.
CATEGORY_PALETTES = {
    "fitness":      {"primary": "#34C759", "secondary": "#FFB066", "accent": "#FF3B30", "surface": "#F4FBF6"},
    "finance":      {"primary": "#1B3A5B", "secondary": "#0E7C66", "accent": "#D4A017", "surface": "#F2F4F8"},
    "food":         {"primary": "#D2682F", "secondary": "#6F8F4F", "accent": "#E0B33A", "surface": "#FBF6EE"},
    "social":       {"primary": "#7A3DD2", "secondary": "#33C7B6", "accent": "#FF6592", "surface": "#F5F0FB"},
    "productivity": {"primary": "#3F5D75", "secondary": "#2E8B8B", "accent": "#FFA94D", "surface": "#F3F5F7"},
    "education":    {"primary": "#3C7AB4", "secondary": "#F0C419", "accent": "#E76F51", "surface": "#F1F6FB"},
    "meditation":   {"primary": "#8E76C8", "secondary": "#A6C49D", "accent": "#E2C290", "surface": "#F6F3FA"},
    "music":        {"primary": "#11151E", "secondary": "#FF3CB5", "accent": "#39E1FF", "surface": "#1B1F2B"},
    "travel":       {"primary": "#2B89C9", "secondary": "#F08A4B", "accent": "#FFC857", "surface": "#F0F7FC"},
    "default":      {"primary": "#3B5BDB", "secondary": "#15AABF", "accent": "#FAB005", "surface": "#F4F6FB"},
}
CATEGORY_KEYWORDS = {
    "fitness":      ("fitness", "workout", "운동", "헬스", "달리기", "요가", "라이딩"),
    "finance":      ("finance", "budget", "투자", "가계부", "지출", "주식"),
    "food":         ("recipe", "food", "레시피", "요리", "맛집", "음식"),
    "social":       ("social", "chat", "friend", "소셜", "친구", "메신저"),
    "productivity": ("todo", "task", "habit", "할일", "생산성", "메모", "일정"),
    "education":    ("learn", "study", "공부", "학습", "교육", "단어"),
    "meditation":   ("meditation", "mindful", "명상", "wellness", "수면"),
    "music":        ("music", "audio", "음악", "playlist"),
    "travel":       ("travel", "trip", "여행", "관광"),
}


def _palette_rotation_degrees(app_name: str) -> int:
    """Deterministic per-app hue rotation for the fallback palette.

    Two same-category apps that both fail palette extraction used to get the
    IDENTICAL fallback palette (e.g. two productivity apps both #3F5D75 — the
    template-smell finding). A bounded rotation derived from the app name
    keeps the category's color family while removing cross-app collisions.
    """
    if not app_name:
        return 0
    digest = hashlib.sha256(app_name.encode("utf-8")).hexdigest()
    # ponytail: bounded ±40° so category identity survives; widen only if
    # real builds still collide visually.
    return int(digest[:8], 16) % 81 - 40


def _rotate_hex_hue(hex_str: str, degrees: int) -> str:
    """Rotate a #RRGGBB hue by `degrees`, preserving lightness/saturation."""
    if degrees == 0:
        return hex_str
    import colorsys
    value = hex_str.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return "#{:02X}{:02X}{:02X}".format(
        round(r2 * 255), round(g2 * 255), round(b2 * 255)
    )


def _hex_ok(value: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"#?[0-9a-fA-F]{6}", value or ""))


def _normalize_hex(value: str) -> str:
    if value.startswith("#"):
        return value.upper()
    return f"#{value.upper()}"


def validate(payload: dict) -> list[str]:
    problems: list[str] = []
    if payload.get("version") != SCHEMA_VERSION:
        problems.append(f"version must be {SCHEMA_VERSION}")
    if not payload.get("appName"):
        problems.append("appName missing")
    color = payload.get("colorTokens") or {}
    if not isinstance(color, dict):
        problems.append("colorTokens must be an object")
    else:
        for token in ("primary", "secondary", "accent", "surface"):
            if not _hex_ok(color.get(token, "")):
                problems.append(f"colorTokens.{token} must be a 6-digit hex (got {color.get(token)!r})")
    typo = payload.get("typography") or {}
    if not isinstance(typo, dict):
        problems.append("typography must be an object")
    else:
        if typo.get("design") not in ALLOWED_TYPO_DESIGN:
            problems.append(f"typography.design must be one of {ALLOWED_TYPO_DESIGN}")
        if typo.get("headingWeight") not in ALLOWED_TYPO_WEIGHT:
            problems.append(f"typography.headingWeight must be one of {ALLOWED_TYPO_WEIGHT}")
    spacing = payload.get("spacing") or {}
    if not isinstance(spacing, dict):
        problems.append("spacing must be an object")
    else:
        for key in ("base", "card", "section"):
            if not isinstance(spacing.get(key), (int, float)) or spacing.get(key) <= 0:
                problems.append(f"spacing.{key} must be a positive number")
    if not isinstance(payload.get("visualAnchors"), list) or not payload["visualAnchors"]:
        problems.append("visualAnchors must be a non-empty list")
    return problems


def detect_category(text: str) -> str:
    lower = (text or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                return category
    return "default"


def _extract_primary_hex(text: str) -> str | None:
    match = re.search(r"primary[^#\n]{0,40}(#?[0-9a-fA-F]{6})", text or "", re.IGNORECASE)
    if match:
        candidate = match.group(1)
        return _normalize_hex(candidate) if _hex_ok(candidate) else None
    return None


def _extract_palette_from_text(text: str) -> dict | None:
    palette: dict[str, str] = {}
    for label in ("primary", "secondary", "accent", "surface"):
        pattern = re.compile(rf"{label}[^#\n]{{0,60}}(#?[0-9a-fA-F]{{6}})", re.IGNORECASE)
        match = pattern.search(text or "")
        if match and _hex_ok(match.group(1)):
            palette[label] = _normalize_hex(match.group(1))
    return palette or None


def synthesize(project_root: Path, *, app_name: str | None = None, idea: str | None = None) -> dict:
    """Build a JSON spec from whatever artifacts we have. Always returns a
    valid object — the deterministic fallback palette guarantees that."""
    architecture = ""
    arch_path = project_root / ".autobot" / "architecture.md"
    if arch_path.is_file():
        try:
            architecture = arch_path.read_text(encoding="utf-8")
        except OSError:
            architecture = ""

    design_md = ""
    md_path = project_root / ".autobot" / "design-spec.md"
    if md_path.is_file():
        try:
            design_md = md_path.read_text(encoding="utf-8")
        except OSError:
            design_md = ""

    combined = "\n".join((idea or "", architecture, design_md))
    category = detect_category(combined)

    palette = _extract_palette_from_text(design_md) or _extract_palette_from_text(architecture) or {}
    fallback = CATEGORY_PALETTES.get(category, CATEGORY_PALETTES["default"])
    rotation = _palette_rotation_degrees(app_name or "")
    for token in ("primary", "secondary", "accent", "surface"):
        palette.setdefault(token, _rotate_hex_hue(fallback[token], rotation))

    typo_design = "rounded" if category in {"fitness", "food", "social", "education"} else "default"
    if category == "music":
        typo_design = "default"

    primary_screen_title = ""
    match = re.search(r"##\s+Screens\s*\n.*?-\s+([^\n]+)", architecture, re.DOTALL)
    if match:
        primary_screen_title = match.group(1).strip()[:40]
    if not primary_screen_title and idea:
        primary_screen_title = idea.strip().split("\n", 1)[0][:40]
    primary_screen_title = primary_screen_title or "Home"

    spec: dict = {
        "version": SCHEMA_VERSION,
        "appName": app_name or "",
        "appCategory": category,
        "colorTokens": palette,
        "typography": {
            "design": typo_design,
            "headingWeight": "semibold",
        },
        "spacing": {"base": 4, "card": 16, "section": 24},
        "primaryScreen": {
            "title": primary_screen_title,
            "anchorAccessibilityIdentifier": "autobot.primaryTitle",
        },
        "visualAnchors": list(DEFAULT_ANCHORS),
        "darkMode": True,
        "_synthesizedFrom": {
            "architecture_md": bool(architecture),
            "design_spec_md": bool(design_md),
            "fallbackPalette": not bool(_extract_palette_from_text(design_md) or _extract_palette_from_text(architecture)),
        },
        "_inputHash": hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16],
    }
    return spec


def ensure(project_root: Path, *, app_name: str = "", idea: str = "") -> tuple[Path, dict, list[str]]:
    """Load or synthesize the spec, validate it, and write the result back.
    Returns (path, payload, problems)."""
    path = project_root / ".autobot" / "design-spec.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            problems = validate(payload)
            return path, payload, problems
        except (json.JSONDecodeError, OSError):
            pass

    payload = synthesize(project_root, app_name=app_name, idea=idea)
    problems = validate(payload)
    if not problems:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, payload, problems


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "synthesize", "ensure"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        p.add_argument("--app-name", default="")
        p.add_argument("--idea", default="")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "validate":
        path = proj / ".autobot" / "design-spec.json"
        if not path.is_file():
            print(json.dumps({"ok": False, "problems": ["file_missing"]}))
            return 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "problems": [f"parse error: {e}"]}))
            return 1
        problems = validate(payload)
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
        return 0 if not problems else 1

    if args.cmd == "synthesize":
        spec = synthesize(proj, app_name=args.app_name, idea=args.idea)
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        return 0

    path, payload, problems = ensure(proj, app_name=args.app_name, idea=args.idea)
    print(json.dumps({"path": str(path), "problems": problems, "payload": payload}, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(_main())
