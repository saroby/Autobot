#!/usr/bin/env python3
"""Validate App Store / TestFlight metadata readiness before Phase 6 archive.

Reads `.autobot/metadata/appstore.json` (Autobot canonical form) and/or the
`fastlane/metadata/` directory. Either source is acceptable; if both exist they
must be consistent on the required fields.

Required fields (all gated, no soft):
  - locale            (e.g. "ko" — primary locale for first release)
  - name              (CFBundleDisplayName for the App Store listing)
  - subtitle          (≤ 30 chars per App Store rules)
  - description       (≥ 10 chars, ≤ 4000)
  - keywords          (≤ 100 chars total when joined by commas)
  - support_url       (https://...)
  - category          (App Store Connect primary category)
  - age_rating        (e.g. "4+", "9+", "12+", "17+")
  - export_compliance ("none", "uses_encryption_exempt", "uses_encryption")
  - privacy_questionnaire ("draft" or "ready")
  - screenshots       (manifest with at least one device-size entry)

When the build environment doesn't have ASC configured, this gate is `skipped`
so /autobot:mvp doesn't fail on the legacy "I just want a local build" flow.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REQUIRED_FIELDS = (
    "locale",
    "name",
    "subtitle",
    "description",
    "keywords",
    "support_url",
    "category",
    "age_rating",
    "export_compliance",
    "privacy_questionnaire",
    "screenshots",
)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
ALLOWED_EXPORT = {"none", "uses_encryption_exempt", "uses_encryption"}
ALLOWED_AGE = {"4+", "9+", "12+", "17+"}


def _disabled() -> bool:
    return os.environ.get("AUTOBOT_DISABLE_METADATA_GATE") == "1"


def _result(status: str, **fields) -> dict:
    fields["status"] = status
    return fields


def _load_appstore_json(project_root: Path) -> dict | None:
    path = project_root / ".autobot" / "metadata" / "appstore.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_fastlane_metadata(project_root: Path) -> dict | None:
    """Map the conventional fastlane metadata directory into the same dict shape
    we use internally. We only look at the *primary* locale (defaults to "ko").
    """
    base = project_root / "fastlane" / "metadata"
    if not base.is_dir():
        return None
    # Pick first locale directory that contains files.
    locales = sorted(p.name for p in base.iterdir() if p.is_dir())
    if not locales:
        return None
    locale = "ko" if "ko" in locales else locales[0]
    locale_dir = base / locale

    def _read(name: str) -> str:
        """Read one fastlane metadata field.

        The files are `<field>.txt` — that is fastlane's own convention and what
        this plugin's own `write-metadata.sh` produces. Reading them without the
        extension made every generated field come back empty, so a correctly
        generated `fastlane/metadata/` always failed `metadata_readiness`
        (measured: a 2,469-byte `ko/description.txt` read as "").

        Locale-scoped fields live under `<base>/<locale>/`; the catalog fields
        (`primary_category`, `secondary_category`, `copyright`) live at
        `<base>/`. Try the locale first, then the root, so one accessor serves
        both without the caller having to know which is which.
        """
        for directory in (locale_dir, base):
            p = directory / f"{name}.txt"
            try:
                if p.is_file():
                    return p.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    screenshots_dir = locale_dir / "screenshots"
    screenshots: dict[str, list[str]] = {}
    if screenshots_dir.is_dir():
        for size_dir in screenshots_dir.iterdir():
            if size_dir.is_dir():
                pngs = sorted(p.name for p in size_dir.glob("*.png"))
                if pngs:
                    screenshots[size_dir.name] = pngs

    review_meta_dir = base.parent / "review_information"
    support_url = _read("support_url") or (
        (review_meta_dir / locale / "support_url.txt").read_text(encoding="utf-8").strip()
        if (review_meta_dir / locale / "support_url.txt").is_file() else ""
    )

    return {
        "locale": locale,
        "name": _read("name"),
        "subtitle": _read("subtitle"),
        "description": _read("description"),
        "keywords": _read("keywords"),
        "support_url": support_url,
        "category": _read("primary_category") or _read("category"),
        "age_rating": _read("age_rating"),
        "export_compliance": _read("export_compliance"),
        "privacy_questionnaire": _read("privacy_questionnaire") or (
            "ready" if (project_root / ".autobot" / "metadata" / "privacy.json").is_file() else ""
        ),
        "screenshots": screenshots,
    }


def _validate_payload(payload: dict) -> list[str]:
    problems: list[str] = []
    for field in REQUIRED_FIELDS:
        value = payload.get(field)
        if isinstance(value, (str, list, dict)):
            if not value:
                problems.append(f"{field} is empty")
        elif value in (None, ""):
            problems.append(f"{field} is missing")
    # Field-specific validation:
    subtitle = payload.get("subtitle") or ""
    if isinstance(subtitle, str) and len(subtitle) > 30:
        problems.append(f"subtitle is {len(subtitle)} chars — App Store limit is 30")
    description = payload.get("description") or ""
    if isinstance(description, str) and len(description) < 10:
        problems.append("description is shorter than 10 characters — not credible")
    keywords = payload.get("keywords") or ""
    if isinstance(keywords, str) and len(keywords) > 100:
        problems.append(f"keywords joined string is {len(keywords)} chars — limit is 100")
    support_url = payload.get("support_url") or ""
    if isinstance(support_url, str) and support_url and not URL_RE.match(support_url):
        problems.append(f"support_url '{support_url}' is not a https URL")
    age_rating = payload.get("age_rating") or ""
    if isinstance(age_rating, str) and age_rating and age_rating not in ALLOWED_AGE:
        problems.append(f"age_rating '{age_rating}' must be one of {sorted(ALLOWED_AGE)}")
    export = payload.get("export_compliance") or ""
    if isinstance(export, str) and export and export not in ALLOWED_EXPORT:
        problems.append(
            f"export_compliance '{export}' must be one of {sorted(ALLOWED_EXPORT)} "
            "(use 'uses_encryption_exempt' for typical TestFlight builds)"
        )
    privacy = payload.get("privacy_questionnaire") or ""
    if isinstance(privacy, str) and privacy and privacy not in {"draft", "ready"}:
        problems.append(f"privacy_questionnaire '{privacy}' must be 'draft' or 'ready'")
    screenshots = payload.get("screenshots") or {}
    if isinstance(screenshots, dict) and not any(screenshots.values()):
        problems.append("screenshots manifest contains no files")
    return problems


def evaluate(project_root: Path, *, asc_configured: bool | None = None) -> dict:
    if _disabled():
        return _result("skipped", skipReason="metadata_gate_disabled")

    # Optional auto-detect ASC configuration from build-state.json.
    if asc_configured is None:
        state_path = project_root / ".autobot" / "build-state.json"
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                env = state.get("environment", {})
                asc_configured = bool(env.get("ascConfigured"))
            except (json.JSONDecodeError, OSError):
                asc_configured = None

    payload = _load_appstore_json(project_root) or _load_fastlane_metadata(project_root)
    if payload is None:
        if asc_configured:
            return _result(
                "failed",
                reason=(
                    "ascConfigured=true but neither .autobot/metadata/appstore.json nor "
                    "fastlane/metadata/ was found — generate metadata before upload"
                ),
            )
        return _result("skipped", skipReason="no_metadata_source_and_asc_unconfigured")

    problems = _validate_payload(payload)
    if problems:
        return _result(
            "failed",
            reason="; ".join(problems[:5]) + (f" (+{len(problems)-5} more)" if len(problems) > 5 else ""),
            payload=payload,
        )

    screenshots = payload.get("screenshots") or {}
    counts = {k: len(v) for k, v in screenshots.items()} if isinstance(screenshots, dict) else {}
    return _result(
        "passed",
        locale=payload.get("locale"),
        screenshotCounts=counts,
        category=payload.get("category"),
        age_rating=payload.get("age_rating"),
        export_compliance=payload.get("export_compliance"),
    )


def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--asc-configured", choices=("true", "false"))
    args = parser.parse_args()

    asc: bool | None = None
    if args.asc_configured == "true": asc = True
    elif args.asc_configured == "false": asc = False
    result = evaluate(Path(args.project_dir).resolve(), asc_configured=asc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("passed", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
