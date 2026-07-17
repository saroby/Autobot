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
                             frequency, source: "appstore"|"app_review"}]
                           items[] entries keyed stable_id("external", rule) so the
                           existing effect_score/quarantine machinery
                           (learning_impact.py) applies for free
  - record_verdict()     .autobot/review-verdict.json (written by the app-review
                         pipeline) → REJECTED verdicts join the same store as
                         high-severity source:"app_review" themes, one per
                         parsed Guideline number
  - prompt-injection defense: a suggested_prevention_rule that is just a review
    quote verbatim is dropped — review text never becomes a rule.

Global promotion is NEVER automatic (lessons #24): record_feedback only returns
promotion *candidates*; the skill presents them and requires one explicit
operator confirmation before `learning_impact.py publish-global` runs.

Event logging: feedback_fetched / external_feedback_recorded are declared in
spec.logEvents with entry-level fields (bundle_id, review_count, themes_count)
that the shell wrapper cannot carry. In a live build this module delegates to
event_log.append_build_log so the event receives the current buildId envelope;
outside a build session it validates against the same SSOT and writes
`.autobot/feedback-log.jsonl`. Each event lands in exactly one file — logs are
audit-only, no gate reads them.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import learning_impact  # noqa: E402
from event_log import append_build_log, validate_log_event  # noqa: E402
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

    A live build delegates to event_log.append_build_log for buildId scoping.
    Without a build log, validation still reuses spec.logEvents before writing
    feedback-log.jsonl (explicit out-of-build-session fallback; never both)."""
    if spec is None:
        from spec_loader import load_spec
        spec = load_spec()
    log_dir = project_root / ".autobot"
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / BUILD_LOG
    present = {k: v for k, v in fields.items() if v is not None}
    if target.is_file():
        append_build_log(
            project_root,
            event,
            spec=spec,
            extra_fields=present,
        )
        return target

    errors = validate_log_event(spec, event, present)
    if errors:
        raise SystemExit("FATAL: invalid feedback event: " + "; ".join(errors))

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


def _theme_signal(source_app: str, clean: dict) -> str:
    """Stable id for one consumed feedback signal: source app + theme + rule +
    the review quotes it was derived from. Re-recording the SAME reviews yields
    the SAME signal (so frequency is not inflated by re-polling), while genuinely
    new reviews (different quotes) or a different app produce a new signal."""
    quotes = "|".join(sorted(_norm_text(q) for q in clean.get("sample_quotes", [])))
    basis = "\x00".join((
        _norm_text(source_app),
        _norm_text(clean.get("theme", "")),
        _norm_text(clean.get("suggested_prevention_rule") or ""),
        quotes,
    ))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def record_feedback(project_root: Path, bundle_id: str, themes: list,
                    *, app_name: str | None = None,
                    source: str = "appstore") -> dict:
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
    approval_resets = 0
    candidates: list[dict] = []

    for raw in themes if isinstance(themes, list) else []:
        clean = sanitize_theme(raw)
        if clean is None:
            continue
        if clean.pop("rule_dropped"):
            dropped_rules += 1
        key = _norm_text(clean["theme"])
        signal = _theme_signal(source_app, clean)
        entry = index.get(key)
        if entry is None:
            entry = {
                "theme": clean["theme"],
                "severity": clean["severity"],
                "source_apps": [source_app],
                "sample_quotes": clean["sample_quotes"],
                "suggested_prevention_rule": clean["suggested_prevention_rule"],
                "frequency": 1,
                "source": source,
                # Data-level operator gate: unapproved entries never leave the
                # project store — publish_project_to_global filters on this,
                # closing BOTH promotion paths (feedback + Phase 7 grade).
                "approved": False,
                # Consumed-signal ledger: review signals already counted toward
                # `frequency`. Re-polling the same reviews yields the same signal
                # so it is not double-counted (project-local; stripped on global
                # publish).
                "_consumed_signals": [signal],
            }
            entries.append(entry)
            index[key] = entry
        else:
            # Only a NEW signal (a genuinely new review, or a different app)
            # increments frequency. A re-poll of already-consumed reviews maps to
            # the same signal and must not inflate the count.
            consumed = entry.setdefault("_consumed_signals", [])
            if signal not in consumed:
                consumed.append(signal)
                entry["frequency"] = int(entry.get("frequency", 0) or 0) + 1
            if _SEVERITY_RANK[clean["severity"]] < _SEVERITY_RANK.get(
                    normalize_severity(entry.get("severity")), 2):
                entry["severity"] = clean["severity"]
            apps = entry.setdefault("source_apps", [])
            if source_app not in apps:
                apps.append(source_app)
            if clean["sample_quotes"]:
                entry["sample_quotes"] = clean["sample_quotes"]
            new_rule = clean["suggested_prevention_rule"]
            if new_rule and _norm_text(new_rule) != _norm_text(
                    entry.get("suggested_prevention_rule") or ""):
                entry["suggested_prevention_rule"] = new_rule
                # Approval covers a specific rule text. A replaced rule the
                # operator never saw must NOT inherit approved:True — that
                # would auto-promote it to the global store on the next
                # publish (the lessons #24 bypass).
                if entry.get("approved"):
                    entry["approved"] = False
                    approval_resets += 1
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
        # >0 means a previously approved theme got a NEW rule text and needs
        # re-approval — the skill must surface this to the operator.
        "approval_resets": approval_resets,
        "promotion_candidates": candidates,
        "promotion_requires_operator_confirmation": True,
    }


# ── App Review verdict → learnings (source: "app_review") ──

VERDICT_FILE = ".autobot/review-verdict.json"
# ASC states that mean Apple rejected the submission. DEVELOPER_REJECTED is a
# self-withdrawal, not a verdict — nothing to learn from it.
_REJECTED_STATES = ("REJECTED", "METADATA_REJECTED", "INVALID_BINARY")


def verdict_is_rejected(verdict: dict) -> bool:
    state = clean_text(verdict.get("appVersionState"), 60).upper().replace(" ", "_")
    sub_state = clean_text(verdict.get("reviewSubmissionState"), 60).upper().replace(" ", "_")
    return state in _REJECTED_STATES or sub_state == "UNRESOLVED_ISSUES"


def themes_from_verdict(verdict: dict) -> list[dict]:
    """REJECTED verdict → one high-severity theme per Guideline number.

    Guideline numbers are the machine-parseable part of a rejection; the
    written Resolution Center reasoning is not fully exposed via the public
    ASC API, so the prevention rule is left empty for the operator to fill in
    (semi-automatic, same approval gate as review themes). `notes` is kept as
    a sample_quote for that judgement — quotes never render into prompts."""
    if not isinstance(verdict, dict) or not verdict_is_rejected(verdict):
        return []
    notes = clean_text(verdict.get("notes"), MAX_QUOTE_LEN)
    raw_numbers = verdict.get("guidelineNumbers")
    numbers = []
    if isinstance(raw_numbers, list):
        numbers = [g for g in (clean_text(v, 20) for v in raw_numbers) if g]
    themes = []
    for number in numbers or [""]:
        theme = (f"App Review rejection — Guideline {number}" if number
                 else "App Review rejection (no guideline parsed)")
        themes.append({
            "theme": theme,
            "severity": "high",
            "sample_quotes": [notes] if notes else [],
            "suggested_prevention_rule": "",
        })
    return themes


def record_verdict(project_root: Path, bundle_id: str,
                   *, verdict_path: Path | None = None,
                   app_name: str | None = None) -> dict:
    """Ingest .autobot/review-verdict.json (written by the app-review
    pipeline) into the learnings store. Non-rejected verdicts record nothing."""
    path = verdict_path or (project_root / VERDICT_FILE)
    if not path.is_file():
        raise SystemExit(f"ERROR: no verdict file at {path}")
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"ERROR: unreadable verdict file {path}: {exc}")
    if not isinstance(verdict, dict):
        # A JSON scalar/array is a malformed verdict, not a crash: return an
        # explicit, non-fatal error (the old `(verdict or {}).get(...)` blew up
        # on a non-empty list).
        return {"recorded_themes": 0, "rejected": False,
                "error": "verdict file is not a JSON object",
                "appVersionState": None}
    themes = themes_from_verdict(verdict)
    if not themes:
        return {"recorded_themes": 0, "rejected": False,
                "appVersionState": (verdict or {}).get("appVersionState")}
    summary = record_feedback(project_root, bundle_id, themes,
                              app_name=app_name, source="app_review")
    summary["rejected"] = True
    summary["guideline_themes"] = [t["theme"] for t in themes]
    return summary


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

    p_ver = sub.add_parser("record-verdict",
                           help="ingest .autobot/review-verdict.json as source:app_review themes")
    p_ver.add_argument("--project-dir", default=".")
    p_ver.add_argument("--bundle-id", required=True)
    p_ver.add_argument("--verdict-json", default=None,
                       help=f"verdict file (default: {VERDICT_FILE})")
    p_ver.add_argument("--app-name", default=None)

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

    if args.cmd == "record-verdict":
        summary = record_verdict(
            proj, args.bundle_id,
            verdict_path=Path(args.verdict_json) if args.verdict_json else None,
            app_name=args.app_name)
        if summary.get("rejected"):
            append_feedback_event(proj, "external_feedback_recorded", {
                "themes_count": summary["recorded_themes"],
                "bundle_id": args.bundle_id,
                "promoted_candidates": len(summary["promotion_candidates"]),
                "detail": {"source": "app_review",
                           "new_items": summary["new_items"]},
            })
        print(json.dumps(summary, ensure_ascii=False, indent=2))
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
