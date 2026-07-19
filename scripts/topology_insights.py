#!/usr/bin/env python3
"""Cross-build pipeline hotspot analyzer (A1).

Mines the ALREADY-accumulated host-wide learnings store
(`~/.config/autobot/learnings.json`, via learning_impact.load_global) to answer
one question the per-build retrospective never asks:

    Across every build this host has ever run, WHERE is the pipeline
    systemically weak, and which learnings are dead weight?

Why this and not "topology search": Autobot's phase topology is static
(`spec/pipeline.json` is the same every build), so there is no topology
*variance* in history to correlate outcomes against — an offline miner can
only surface where corrective pressure concentrates, not which unseen ordering
is better. It emits operator-facing *candidates*; nothing here mutates
pipeline.json or auto-promotes anything (promotion stays on the existing
`learning_impact publish-global` operator-approved path).

Read-only. Pure `rollup(global_learnings)` core so it is testable without a
network, an LLM, or the real global store.

CLI:
    topology_insights.py                 # print insights JSON to stdout
    topology_insights.py --out-dir DIR   # also write topology-insights.{json,md}
    topology_insights.py --format md     # print the markdown report instead
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from learning_impact import QUARANTINE_THRESHOLD, load_global  # noqa: E402

# Report-only labels. Falls back to "Phase N" for anything unmapped, so a new
# phase never breaks the analyzer — it just shows up unnamed.
PHASE_NAMES = {
    "0": "Setup",
    "1": "Architecture",
    "2": "UX Design",
    "3": "Scaffold",
    "4": "Parallel Coding",
    "5": "Quality / Integration",
    "6": "Deploy",
    "7": "Retrospective",
}

# A phase holding at least this share of ALL accumulated learnings is a
# systemic weak point worth an operator's attention.
HOTSPOT_SHARE = 0.30
# This many never-helped (effect_score <= 0) learnings in one phase is Phase-0
# noise worth pruning.
DEAD_WEIGHT_MIN = 5


def _phase_label(phase: str) -> str:
    return f"Phase {phase} · {PHASE_NAMES[phase]}" if phase in PHASE_NAMES else f"Phase {phase}"


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _phase_rollup(items: list) -> list[dict]:
    """Group learnings by phase, ranked by corrective pressure (item count)."""
    by_phase: dict[str, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        by_phase.setdefault(str(item.get("phase", "?")), []).append(item)

    total = sum(len(v) for v in by_phase.values()) or 1
    rows: list[dict] = []
    for phase, group in by_phase.items():
        scores = [_int(i.get("effect_score")) for i in group]
        outcomes = Counter(str(i.get("last_outcome", "untried")) for i in group)
        builds: set[str] = set()
        for i in group:
            runs = i.get("applied_runs")
            if isinstance(runs, list):
                builds.update(str(r) for r in runs)
        rows.append(
            {
                "phase": phase,
                "label": _phase_label(phase),
                "item_count": len(group),
                "share": round(len(group) / total, 3),
                "effect_sum": sum(scores),
                "effect_mean": round(sum(scores) / len(group), 2) if group else 0.0,
                "quarantined": sum(1 for s in scores if s <= QUARANTINE_THRESHOLD),
                "dead_or_negative": sum(1 for s in scores if s <= 0),
                "outcomes": dict(outcomes),
                "build_coverage": len(builds),
            }
        )
    rows.sort(key=lambda r: (r["item_count"], -r["effect_sum"]), reverse=True)
    return rows


def _pattern_rollup(patterns: dict, key: str) -> list[dict]:
    """Best-effort frequency view of a `patterns.<key>` list. Elements may be
    plain strings or dicts; a numeric count/frequency field is honoured when
    present, else each distinct entry counts once."""
    entries = patterns.get(key) if isinstance(patterns, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[dict] = []
    for e in entries:
        if isinstance(e, dict):
            label = str(
                e.get("signature")
                or e.get("error")
                or e.get("theme")
                or e.get("rule")
                or e.get("name")
                or e
            )
            count = _int(e.get("count") or e.get("frequency") or e.get("occurrences"), 1)
            extra = {k: e[k] for k in ("severity", "source_apps") if k in e}
        else:
            label, count, extra = str(e), 1, {}
        out.append({"label": label, "count": count, **extra})
    out.sort(key=lambda r: r["count"], reverse=True)
    return out


def _candidates(phase_rows: list[dict], build_errors: list[dict], ext_themes: list[dict]) -> list[dict]:
    """Deterministic, operator-facing improvement candidates. Evidence-first;
    never prescriptive beyond 'look here'."""
    cands: list[dict] = []
    for row in phase_rows:
        if row["share"] >= HOTSPOT_SHARE:
            cands.append(
                {
                    "phase": row["phase"],
                    "severity": "high",
                    "evidence": (
                        f"{row['label']} holds {int(row['share'] * 100)}% "
                        f"({row['item_count']}) of all accumulated learnings — "
                        f"the dominant sink of corrective pressure."
                    ),
                    "suggested_change": (
                        "Strengthen the contract handoff into/out of this phase "
                        "(tighter upstream spec, earlier validation) so fewer "
                        "corrections are needed here. Operator decision — not auto-applied."
                    ),
                }
            )
        if row["dead_or_negative"] >= DEAD_WEIGHT_MIN:
            cands.append(
                {
                    "phase": row["phase"],
                    "severity": "medium",
                    "evidence": (
                        f"{row['label']} carries {row['dead_or_negative']} learnings "
                        f"with effect_score<=0 (never demonstrably helped)."
                    ),
                    "suggested_change": (
                        "Review these for quarantine to cut Phase-0 injection noise; "
                        f"{row['quarantined']} already auto-quarantined."
                    ),
                }
            )
    for err in build_errors:
        if err["count"] >= 3:
            cands.append(
                {
                    "phase": None,
                    "severity": "medium",
                    "evidence": f"Build-error pattern recurs ({err['count']}x): {err['label'][:120]}",
                    "suggested_change": "Encode a pre-build guard/prevention rule for this recurring class.",
                }
            )
    for theme in ext_themes:
        if theme["count"] >= 2:
            cands.append(
                {
                    "phase": None,
                    "severity": theme.get("severity", "medium"),
                    "evidence": f"Cross-app user complaint theme ({theme['count']} apps): {theme['label'][:120]}",
                    "suggested_change": "Promote a prevention rule via `learning_impact publish-global` (operator-approved).",
                }
            )
    return cands


def rollup(global_learnings: dict) -> dict:
    """Pure core: global learnings store dict -> insights dict."""
    items = global_learnings.get("items") if isinstance(global_learnings, dict) else None
    items = items if isinstance(items, list) else []
    patterns = global_learnings.get("patterns") if isinstance(global_learnings, dict) else None
    patterns = patterns if isinstance(patterns, dict) else {}

    phase_rows = _phase_rollup(items)
    build_errors = _pattern_rollup(patterns, "common_build_errors")
    ext_themes = _pattern_rollup(patterns, "external_feedback")
    return {
        "total_items": len(items),
        "phase_hotspots": phase_rows,
        "recurring_build_errors": build_errors,
        "external_feedback_themes": ext_themes,
        "candidates": _candidates(phase_rows, build_errors, ext_themes),
    }


def render_markdown(insights: dict) -> str:
    lines = ["# Cross-Build Pipeline Insights", ""]
    lines.append(f"누적 학습 {insights['total_items']}건 기준. 토폴로지가 정적이라 '더 나은 순서'가 아니라 '어디가 약한가'를 마이닝한 결과다. 아래는 **후보**이며 자동 적용되지 않는다.")
    lines.append("")
    lines.append("## Phase 핫스팟 (교정 압력 순)")
    lines.append("")
    lines.append("| Phase | 학습수 | 비중 | effect합 | 죽은(≤0) | 격리 | 빌드커버리지 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in insights["phase_hotspots"]:
        lines.append(
            f"| {r['label']} | {r['item_count']} | {int(r['share'] * 100)}% | "
            f"{r['effect_sum']} | {r['dead_or_negative']} | {r['quarantined']} | {r['build_coverage']} |"
        )
    lines.append("")
    if insights["recurring_build_errors"]:
        lines.append("## 반복 빌드 에러 패턴")
        lines.append("")
        for e in insights["recurring_build_errors"][:10]:
            lines.append(f"- ({e['count']}x) {e['label'][:160]}")
        lines.append("")
    if insights["external_feedback_themes"]:
        lines.append("## 교차-앱 사용자 피드백 테마")
        lines.append("")
        for t in insights["external_feedback_themes"][:10]:
            lines.append(f"- ({t['count']}) {t['label'][:160]}")
        lines.append("")
    lines.append("## 개선 후보 (운영자 검토용)")
    lines.append("")
    if not insights["candidates"]:
        lines.append("_임계치를 넘는 후보 없음._")
    for c in insights["candidates"]:
        tag = c["phase"] and f"[Phase {c['phase']}] " or ""
        lines.append(f"- **{c['severity'].upper()}** {tag}{c['evidence']}")
        lines.append(f"  - → {c['suggested_change']}")
    lines.append("")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-build pipeline hotspot analyzer")
    parser.add_argument("--out-dir", help="write topology-insights.{json,md} into this dir")
    parser.add_argument("--format", choices=["json", "md"], default="json", help="stdout format")
    args = parser.parse_args(argv)

    insights = rollup(load_global())

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "topology-insights.json").write_text(
            json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out / "topology-insights.md").write_text(render_markdown(insights), encoding="utf-8")

    if args.format == "md":
        print(render_markdown(insights))
    else:
        print(json.dumps(insights, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
