#!/usr/bin/env python3
"""Render markdown blocks derived from plugins/autobot/spec/pipeline.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
REPO_ROOT = PLUGIN_DIR.parent.parent
SPEC_PATH = PLUGIN_DIR / "spec" / "pipeline.json"


def load_spec() -> dict:
    with SPEC_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def sorted_phases(spec: dict) -> list[tuple[str, dict]]:
    return sorted(spec.get("phases", {}).items(), key=lambda item: int(item[0]))


def gate_label(gate_id: str | None) -> str:
    if not gate_id:
        return "—"
    return gate_id.replace("->", "→")


def render_readme_phase_table(spec: dict) -> str:
    lines = [
        "| Phase | 이름 | 에이전트 | 산출물 |",
        "|-------|------|---------|--------|",
    ]
    for phase_id, phase in sorted_phases(spec):
        docs = phase.get("docs", {})
        outputs = ", ".join(docs.get("outputs", []))
        lines.append(
            f"| {phase_id} | {docs.get('displayName', phase.get('name', phase_id))} | "
            f"{docs.get('readmeAgent', docs.get('skillAgent', '(unspecified)'))} | {outputs} |"
        )
    return "\n".join(lines)


def render_readme_gate_summary(spec: dict) -> str:
    lines = []
    for gate_id, gate in sorted(spec.get("gates", {}).items(), key=lambda item: int(item[1]["fromPhase"])):
        label = gate_label(gate_id)
        summary = gate.get("docsSummary", gate.get("summary", "")).strip()
        suffix = " (soft gate)" if gate.get("soft") else ""
        lines.append(f"- **Gate {label}**: {summary}{suffix}")
    return "\n".join(lines)


def render_skill_phase_summary(spec: dict) -> str:
    lines = [
        "| Phase | Name | Agent | Parallel | Gate | Max Retry |",
        "|-------|------|-------|----------|------|-----------|",
    ]
    for phase_id, phase in sorted_phases(spec):
        docs = phase.get("docs", {})
        parallel = "**Yes**" if docs.get("parallel") else "No"
        lines.append(
            f"| {phase_id} | {docs.get('displayName', phase.get('name', phase_id))} | "
            f"{docs.get('skillAgent', docs.get('readmeAgent', '(unspecified)'))} | "
            f"{parallel} | {docs.get('gateLabel', gate_label(phase.get('gate')))} | "
            f"{phase.get('maxRetry', '—') if phase.get('gate') is not None else '—'} |"
        )
    return "\n".join(lines)


def replace_block(content: str, block_name: str, replacement: str) -> str:
    start = f"<!-- {block_name}:START -->"
    end = f"<!-- {block_name}:END -->"
    new_block = f"{start}\n{replacement.rstrip()}\n{end}"
    start_idx = content.find(start)
    end_idx = content.find(end)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        raise ValueError(f"missing block markers for {block_name}")
    end_idx += len(end)
    return f"{content[:start_idx]}{new_block}{content[end_idx:]}"


def render_targets(spec: dict) -> dict[Path, dict[str, str]]:
    return {
        REPO_ROOT / "README.md": {
            "AUTOBOT_PHASE_TABLE": render_readme_phase_table(spec),
            "AUTOBOT_GATE_SUMMARY": render_readme_gate_summary(spec),
        },
        PLUGIN_DIR / "skills" / "orchestrator" / "SKILL.md": {
            "AUTOBOT_PHASE_SUMMARY": render_skill_phase_summary(spec),
        },
    }


def apply_render(spec: dict, *, write: bool) -> int:
    targets = render_targets(spec)
    dirty: list[Path] = []

    for path, blocks in targets.items():
        original = path.read_text(encoding="utf-8")
        rendered = original
        for block_name, replacement in blocks.items():
            rendered = replace_block(rendered, block_name, replacement)
        if rendered != original:
            dirty.append(path)
            if write:
                path.write_text(rendered, encoding="utf-8")

    if dirty and not write:
        for path in dirty:
            print(f"OUTDATED: {path}")
        return 1

    if write:
        if dirty:
            for path in dirty:
                print(f"UPDATED: {path}")
        else:
            print("OK: rendered docs already up to date")
    else:
        print("OK: rendered docs are up to date")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render pipeline-derived markdown blocks")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Exit non-zero if rendered blocks are stale")
    mode.add_argument("--write", action="store_true", help="Rewrite rendered blocks in place")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    spec = load_spec()
    return apply_render(spec, write=args.write)


if __name__ == "__main__":
    sys.exit(main())
