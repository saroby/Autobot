#!/usr/bin/env python3
"""External signal loop v1 — App Store reviews → learnings.

Deterministic half of `/autobot:feedback`. The skill (LLM) fetches reviews via
mcp-appstore and extracts themes; THIS module owns everything that must be
testable without a network or an LLM:

  - parse_reviews()      normalize a fetch_reviews payload (count + fields)
  - sanitization         review text is UNTRUSTED external input: control/format
                         chars stripped, whitespace collapsed, hard length caps
  - record_feedback()    themes → .autobot/learnings.json
                           patterns.external_feedback [{theme, severity,
                             source_apps, sample_quotes, suggested_prevention_rule,
                             frequency}]
                           items[] entries keyed stable_id("external", rule) so the
                           existing effect_score/quarantine machinery
                           (learning_impact.py) applies for free
  - prompt-injection defense: a suggested_prevention_rule that is just a review
    quote verbatim is dropped — review text never becomes a rule.

Global promotion is NEVER automatic (lessons #24): record_feedback only returns
promotion *candidates*; the skill presents them and requires one explicit
operator confirmation before `learning_impact.py publish-global` runs.

Event logging: feedback_fetched / external_feedback_recorded are declared in
spec.logEvents with entry-level fields (bundle_id, review_count, themes_count)
that the phase/agent/detail-only build-log.sh wrapper cannot carry, so this
module validates through the same runtime validator (event_log.validate_log_event
— spec stays the SSOT) and appends the entry itself. Target file: the project's
existing `.autobot/build-log.jsonl` when present; otherwise (feedback runs
outside any build session, post-release) `.autobot/feedback-log.jsonl`. Each
event lands in exactly one file — logs are audit-only, no gate reads them.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import learning_impact  # noqa: E402
from event_log import validate_log_event  # noqa: E402
from learning_impact import _norm_text, stable_id  # noqa: E402
from state_store import utc_now  # noqa: E402

MAX_THEME_LEN = 120
MAX_RULE_LEN = 300
MAX_QUOTE_LEN = 200
MAX_QUOTES = 3
# A quote this short is too generic to prove the rule was copied from it.
MIN_QUOTE_MATCH_LEN = 12

_SEVERITIES = ("high", "medium", "low")
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

FEEDBACK_LOG = "feedback-log.jsonl"
BUILD_LOG = "build-log.jsonl"


# ── sanitization (trust boundary — review text is untrusted) ──


def clean_text(value: object, max_len: int) -> str:
    """Strip control (Cc) and format (Cf: zero-width, bidi override) characters,
    collapse all whitespace to single spaces, and cap the length."""
    text = str(value or "")
    text = "".join(
        " " if unicodedata.category(ch) in ("Cc", "Cf") else ch for ch in text
    )
    text = " ".join(text.split())
    return text[:max_len].strip()


def normalize_severity(value: object) -> str:
    sev = str(value or "").strip().lower()
    return sev if sev in _SEVERITIES else "low"


def rule_is_quoted_review(rule: str, quotes: list[str]) -> bool:
    """True when the suggested rule is (or contains) a review quote verbatim —
    the prompt-injection path where user review text gets promoted into an
    instruction for future builds. Deterministic text check, no LLM."""
    rule_n = _norm_text(rule)
    if not rule_n:
        return False
    for quote in quotes:
        quote_n = _norm_text(quote)
        if len(quote_n) >= MIN_QUOTE_MATCH_LEN and quote_n in rule_n:
            return True
    return False


# ── fetch_reviews payload parsing ──


def parse_reviews(payload: object) -> list[dict]:
    """Normalize an mcp-appstore fetch_reviews payload to
    [{"title", "text", "score"}]. Accepts {"reviews": [...]} or a bare list."""
    if isinstance(payload, dict):
        reviews = payload.get("reviews")
    else:
        reviews = payload
    if not isinstance(reviews, list):
        return []
    normalized: list[dict] = []
    for raw in reviews:
        if not isinstance(raw, dict):
            continue
        text = raw.get("text") or raw.get("review") or raw.get("content") or raw.get("body") or ""
        score = raw.get("score", raw.get("rating"))
        normalized.append({
            "title": clean_text(raw.get("title"), MAX_QUOTE_LEN),
            "text": clean_text(text, 2000),
            "score": score if isinstance(score, (int, float)) else None,
        })
    return normalized


# ── event logging (audit-only) ──


def append_feedback_event(project_root: Path, event: str, fields: dict,
                          *, spec: dict | None = None) -> Path:
    """Spec-validated append for the entry-level-field feedback events.

    Validation reuses event_log.validate_log_event against spec.logEvents (the
    SSOT). Writes to build-log.jsonl when the project has one, else to
    feedback-log.jsonl (explicit out-of-build-session fallback; see module
    docstring — never both)."""
    if spec is None:
        from spec_loader import load_spec
        spec = load_spec()
    present = {k: v for k, v in fields.items() if v is not None}
    errors = validate_log_event(spec, event, present)
    if errors:
        raise SystemExit("FATAL: invalid feedback event: " + "; ".join(errors))

    log_dir = project_root / ".autobot"
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / BUILD_LOG
    if not target.is_file():
        target = log_dir / FEEDBACK_LOG
    entry = {"ts": utc_now(), "event": event, **present}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
        handle.write("\n")
    return target


# ── themes → learnings ──


def sanitize_theme(raw: dict) -> dict | None:
    """One raw LLM-extracted theme → sanitized fields, or None when unusable.
    Drops the rule (not the theme) when it fails the injection check."""
    if not isinstance(raw, dict):
        return None
    theme = clean_text(raw.get("theme"), MAX_THEME_LEN)
    if not theme:
        return None
    quotes_raw = raw.get("sample_quotes")
    quotes = []
    if isinstance(quotes_raw, list):
        quotes = [q for q in (clean_text(v, MAX_QUOTE_LEN) for v in quotes_raw[:MAX_QUOTES]) if q]
    rule = clean_text(raw.get("suggested_prevention_rule"), MAX_RULE_LEN)
    rule_dropped = False
    if rule and rule_is_quoted_review(rule, quotes):
        rule = ""
        rule_dropped = True
    return {
        "theme": theme,
        "severity": normalize_severity(raw.get("severity")),
        "sample_quotes": quotes,
        "suggested_prevention_rule": rule,
        "rule_dropped": rule_dropped,
    }


def record_feedback(project_root: Path, bundle_id: str, themes: list,
                    *, app_name: str | None = None) -> dict:
    """Record sanitized themes into the PROJECT-LOCAL learnings store
    (automatic) and return global promotion candidates (operator-gated)."""
    source_app = app_name or bundle_id
    data = learning_impact._load(project_root)
    patterns = data.setdefault("patterns", {})
    entries = patterns.get("external_feedback")
    if not isinstance(entries, list):
        entries = []
        patterns["external_feedback"] = entries
    index = {_norm_text(e.get("theme", "")): e for e in entries if isinstance(e, dict)}
    items = data.setdefault("items", [])
    item_ids = {i.get("id") for i in items if isinstance(i, dict)}

    recorded = 0
    new_items = 0
    dropped_rules = 0
    candidates: list[dict] = []

    for raw in themes if isinstance(themes, list) else []:
        clean = sanitize_theme(raw)
        if clean is None:
            continue
        if clean.pop("rule_dropped"):
            dropped_rules += 1
        key = _norm_text(clean["theme"])
        entry = index.get(key)
        if entry is None:
            entry = {
                "theme": clean["theme"],
                "severity": clean["severity"],
                "source_apps": [source_app],
                "sample_quotes": clean["sample_quotes"],
                "suggested_prevention_rule": clean["suggested_prevention_rule"],
                "frequency": 1,
                # Data-level operator gate: unapproved entries never leave the
                # project store — publish_project_to_global filters on this,
                # closing BOTH promotion paths (feedback + Phase 7 grade).
                "approved": False,
            }
            entries.append(entry)
            index[key] = entry
        else:
            entry["frequency"] = int(entry.get("frequency", 0) or 0) + 1
            if _SEVERITY_RANK[clean["severity"]] < _SEVERITY_RANK.get(
                    normalize_severity(entry.get("severity")), 2):
                entry["severity"] = clean["severity"]
            apps = entry.setdefault("source_apps", [])
            if source_app not in apps:
                apps.append(source_app)
            if clean["sample_quotes"]:
                entry["sample_quotes"] = clean["sample_quotes"]
            if clean["suggested_prevention_rule"]:
                entry["suggested_prevention_rule"] = clean["suggested_prevention_rule"]
        recorded += 1

        rule = entry.get("suggested_prevention_rule") or ""
        if not rule:
            continue
        if not any(_norm_text(c["theme"]) == key for c in candidates):
            candidates.append({
                "theme": entry["theme"],
                "severity": entry.get("severity", "low"),
                "rule": rule,
            })
        item_id = stable_id("external", rule)
        if item_id not in item_ids:
            items.append({
                "id": item_id,
                "phase": "external",
                "effect_score": 0,
                "last_outcome": "untried",
                "applied_runs": [],
                "rule_preview": rule[:200],
                "source": "external_feedback",
                "theme": entry["theme"],
            })
            item_ids.add(item_id)
            new_items += 1

    learning_impact._save(project_root, data)
    candidates.sort(key=lambda c: _SEVERITY_RANK.get(c["severity"], 3))
    return {
        "recorded_themes": recorded,
        "new_items": new_items,
        "dropped_rules": dropped_rules,
        "promotion_candidates": candidates,
        "promotion_requires_operator_confirmation": True,
    }


def approve_themes(project_root: Path, themes: list[str]) -> dict:
    """Operator gate, as data: mark external_feedback entries approved so
    publish_project_to_global lets them (and their tracking items) through.
    Unknown themes are reported, not silently skipped."""
    data = learning_impact._load(project_root)
    entries = data.get("patterns", {}).get("external_feedback")
    entries = entries if isinstance(entries, list) else []
    index = {_norm_text(e.get("theme", "")): e for e in entries if isinstance(e, dict)}
    approved, unknown = [], []
    for theme in themes:
        entry = index.get(_norm_text(theme))
        if entry is None:
            unknown.append(theme)
            continue
        entry["approved"] = True
        approved.append(entry.get("theme"))
    if approved:
        learning_impact._save(project_root, data)
    return {"approved": approved, "unknown": unknown}


def resolve_bundle_id(project_root: Path) -> str | None:
    """bundleId from .autobot/architecture.json, falling back to build-state.json."""
    for name in ("architecture.json", "build-state.json"):
        path = project_root / ".autobot" / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8")).get("bundleId")
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ── CLI ──


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="External feedback → learnings")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_res = sub.add_parser("resolve-bundle-id")
    p_res.add_argument("--project-dir", default=".")

    p_fetch = sub.add_parser("log-fetched")
    p_fetch.add_argument("--project-dir", default=".")
    p_fetch.add_argument("--bundle-id", required=True)
    p_fetch.add_argument("--review-count", type=int, default=None)
    p_fetch.add_argument("--reviews-json", default=None,
                         help="fetch_reviews payload file; used to derive --review-count")
    p_fetch.add_argument("--app-id", default=None)
    p_fetch.add_argument("--source", default="appstore")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--project-dir", default=".")
    p_rec.add_argument("--bundle-id", required=True)
    p_rec.add_argument("--themes-json", required=True,
                       help='file with {"themes": [{theme, severity, sample_quotes, suggested_prevention_rule}]}')
    p_rec.add_argument("--app-name", default=None)

    p_app = sub.add_parser("approve",
                           help="operator gate: mark themes eligible for global publish")
    p_app.add_argument("--project-dir", default=".")
    p_app.add_argument("--theme", action="append", required=True,
                       help="theme text to approve (repeatable)")

    args = parser.parse_args()
    proj = Path(args.project_dir).resolve()

    if args.cmd == "approve":
        result = approve_themes(proj, args.theme)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["unknown"] else 0

    if args.cmd == "resolve-bundle-id":
        bundle = resolve_bundle_id(proj)
        if not bundle:
            print("ERROR: no bundleId in .autobot/architecture.json or .autobot/build-state.json",
                  file=sys.stderr)
            return 1
        print(bundle)
        return 0

    if args.cmd == "log-fetched":
        count = args.review_count
        if count is None and args.reviews_json:
            payload = json.loads(Path(args.reviews_json).read_text(encoding="utf-8"))
            count = len(parse_reviews(payload))
        if count is None:
            print("ERROR: pass --review-count or --reviews-json", file=sys.stderr)
            return 1
        target = append_feedback_event(proj, "feedback_fetched", {
            "bundle_id": args.bundle_id,
            "review_count": count,
            "app_id": args.app_id,
            "source": args.source,
        })
        print(f"OK: feedback_fetched logged ({count} reviews) -> {target}")
        return 0

    # record
    payload = json.loads(Path(args.themes_json).read_text(encoding="utf-8"))
    themes = payload.get("themes") if isinstance(payload, dict) else payload
    summary = record_feedback(proj, args.bundle_id, themes or [], app_name=args.app_name)
    target = append_feedback_event(proj, "external_feedback_recorded", {
        "themes_count": summary["recorded_themes"],
        "bundle_id": args.bundle_id,
        "promoted_candidates": len(summary["promotion_candidates"]),
        "detail": {"new_items": summary["new_items"],
                   "dropped_rules": summary["dropped_rules"]},
    })
    summary["log_path"] = str(target)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
