#!/usr/bin/env python3
"""Per-agent context pack — a small focused blob the orchestrator embeds at
the top of a sub-agent prompt instead of the full mvp.md / orchestrator skill.

Sections (always emitted in this order — no drop logic, the budget is a
warning not a hard truncation):

    PHASE             — spec slice for the phase (id, name, gate, gateChecks)
    OUTPUT CONTRACT   — fileOwnership.agents.<agent>.writes
    REQUIRED INPUTS   — owned-file paths from upstream phases
    HIGH-IMPACT LEARNINGS — top-N active learnings by effect_score
    REFERENCE INDEX   — per-agent reference file paths
    PROMPT TAIL       — orchestrator-supplied free text

If the rendered pack exceeds the soft budget the function still returns it —
the orchestrator decides whether to use it or split the dispatch. Hiding
sections "to fit" creates worse silent failures than an oversize prompt.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_BUDGET_BYTES = 40 * 1024
MAX_LEARNINGS = 8

REFERENCE_FILES = {
    "architect": [
        "references/axiom-distilled/design.md",
        "references/axiom-distilled/data-concurrency.md",
        "references/ios-ux-style.md",
    ],
    "ui-builder": [
        "references/axiom-distilled/swiftui.md",
        "references/axiom-distilled/design.md",
    ],
    "data-engineer": [
        "references/axiom-distilled/data-concurrency.md",
        "references/axiom-distilled/build-testing.md",
    ],
    "quality-engineer": [
        "references/axiom-distilled/build-testing.md",
        "references/axiom-distilled/data-concurrency.md",
        "references/axiom-distilled/swiftui.md",
    ],
    "ux-designer": ["references/axiom-distilled/design.md"],
    "design-system": [
        "references/axiom-distilled/design.md",
        "references/axiom-distilled/swiftui.md",
    ],
    "backend-engineer": [],
    "deployer": [],
}


def _spec_slice(spec: dict, phase: str) -> dict:
    phases = spec.get("phases") or {}
    gates = spec.get("gates") or {}
    block = phases.get(str(phase)) or {}
    gate_id = block.get("gate")
    return {
        "id": phase,
        "name": block.get("name"),
        "maxRetry": block.get("maxRetry"),
        "agents": block.get("agents") or [],
        "gate": gate_id,
        "gateChecks": [
            (c.get("label") or c.get("name"))
            for c in ((gates.get(gate_id) or {}).get("checks") or [])
        ],
        "gateSummary": (gates.get(gate_id) or {}).get("docsSummary"),
    }


def _writes_for(spec: dict, agent: str, app_name: str) -> list[str]:
    block = ((spec.get("fileOwnership") or {}).get("agents") or {}).get(agent) or {}
    return [raw.replace("{appName}", app_name) for raw in (block.get("writes") or [])]


def _transitive_upstream(phases: dict, start: str) -> list[str]:
    """All phases reachable from `start` via the `dependencies` edges
    (TRANSITIVE, not just the immediate parents).

    The pipeline is a single-edge chain (4→3→2→1→0), so the immediate
    dependency of Phase 4 is only Phase 3 (design-system / Packages/). Walking
    just the immediate parent omitted the Phase-1 `{appName}/Models/` +
    ServiceProtocols.swift type contract — the very thing every phase-4 coder's
    prompt is written against. Traversing the full closure surfaces it (and the
    Phase-2 design-spec) as read-only inputs. Inputs are path+sha+size
    references, not file contents, so a wider closure costs only a few lines.

    Returned ascending by phase id for stable, deterministic pack output.
    """
    seen: set[str] = set()
    stack = list((phases.get(start) or {}).get("dependencies") or [])
    while stack:
        pid = str(stack.pop())
        if pid in seen or pid not in phases:
            continue
        seen.add(pid)
        stack.extend(str(d) for d in ((phases.get(pid) or {}).get("dependencies") or []))
    return sorted(seen, key=lambda p: (len(p), p))


def _required_inputs(spec: dict, agent: str, app_name: str, project_root: Path) -> list[dict]:
    """Owned files from ALL transitive-upstream phases (read-only inputs)."""
    phases = spec.get("phases") or {}
    my_phase = next(
        (pid for pid, b in phases.items() if agent in (b.get("agents") or [])),
        None,
    )
    if my_phase is None:
        return []
    ownership = (spec.get("fileOwnership") or {}).get("agents") or {}

    inputs: list[dict] = []
    seen_paths: set[str] = set()

    def _add(full: Path) -> None:
        rel = str(full.relative_to(project_root))
        if rel in seen_paths:
            return
        seen_paths.add(rel)
        inputs.append({
            "path": rel,
            "sha": hashlib.sha256(full.read_bytes()).hexdigest()[:12],
            "size": full.stat().st_size,
        })

    for upstream in _transitive_upstream(phases, my_phase):
        for ag in (phases.get(upstream) or {}).get("agents") or []:
            for raw in (ownership.get(ag, {}).get("writes") or []):
                path_str = raw.replace("{appName}", app_name)
                full = project_root / path_str
                if path_str.endswith("/") and full.is_dir():
                    for f in sorted(full.rglob("*.swift")):
                        _add(f)
                elif full.is_file():
                    _add(full)
    return inputs


def _learnings(project_root: Path, limit: int = MAX_LEARNINGS) -> list[dict]:
    try:
        from learning_impact import active
    except ImportError:
        return []
    items = [i for i in (active(project_root).get("items") or []) if isinstance(i, dict)]
    items.sort(key=lambda i: int(i.get("effect_score", 0)), reverse=True)
    return items[:limit]


def build(
    project_root: Path,
    spec: dict,
    state: dict,
    *,
    phase: str,
    agent: str,
    prompt_tail: str = "",
    budget: int = DEFAULT_BUDGET_BYTES,
) -> dict:
    app_name = state.get("appName") or ""
    phase_info = _spec_slice(spec, phase)
    writes = _writes_for(spec, agent, app_name)
    inputs = _required_inputs(spec, agent, app_name, project_root)
    learnings = _learnings(project_root)
    references = REFERENCE_FILES.get(agent, [])

    lines: list[str] = []
    lines.append(f"# Context pack — phase={phase} agent={agent} budget={budget}")
    lines.append("")
    lines.append("PHASE")
    for k, v in phase_info.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("OUTPUT CONTRACT")
    for w in writes:
        lines.append(f"  - {w}")
    if not writes:
        lines.append("  (none — agent has no declared writes)")
    lines.append("")
    lines.append("REQUIRED INPUTS")
    if inputs:
        for entry in inputs:
            lines.append(f"  - {entry['path']:<60} [sha={entry['sha']} {entry['size']:>6}B]")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("HIGH-IMPACT LEARNINGS")
    if learnings:
        for item in learnings:
            score = item.get("effect_score", 0)
            preview = (item.get("rule_preview") or "").strip()[:140]
            lines.append(f"  - [{'+' if score >= 0 else ''}{score}] {preview}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("REFERENCE INDEX")
    for ref in references:
        lines.append(f"  - {ref}")
    if not references:
        lines.append("  (none)")
    if prompt_tail:
        lines.append("")
        lines.append("PROMPT TAIL")
        lines.append(prompt_tail)

    text = "\n".join(lines)
    size = len(text.encode("utf-8"))
    return {
        "text": text,
        "bytes": size,
        "budget": budget,
        "over_budget": size > budget,
    }


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--phase", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    parser.add_argument("--prompt-tail", default="")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    from spec_loader import load_spec
    from state_store import load_state, state_file_from_args

    spec = load_spec()
    state_args = argparse.Namespace(project_dir=args.project_dir, state_file=None)
    state = load_state(state_file_from_args(state_args))

    result = build(
        Path(args.project_dir).resolve(),
        spec, state,
        phase=args.phase, agent=args.agent,
        prompt_tail=args.prompt_tail, budget=args.budget,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["text"])
    if result["over_budget"]:
        print(f"\n# WARN: pack {result['bytes']}B exceeds budget {result['budget']}B", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
