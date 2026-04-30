#!/usr/bin/env python3
"""Render a compact, prompt-friendly learnings summary for Autobot.

Reads `.autobot/learnings.json` from the project directory and writes
`.autobot/active-learnings.md`, a distilled summary designed to be read by the
orchestrator and agents at build time.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


PHASE_CONFIG: dict[str, dict[str, Any]] = {
    "architecture": {
        "title": "Architecture",
        "keywords": [
            "architecture",
            "model",
            "swiftdata",
            "@model",
            "serviceprotocol",
            "service protocol",
            "backend",
            "api contract",
            "navigation",
            "import",
        ],
        "include_patterns": True,
        "include_deploy_tips": False,
    },
    "parallel_coding": {
        "title": "Parallel Coding",
        "keywords": [
            "viewmodel",
            "viewmodels",
            "view",
            "views",
            "swiftui",
            "repository",
            "repositories",
            "sample data",
            "service",
            "import",
            "modelcontext",
            "parallel",
        ],
        "include_patterns": True,
        "include_deploy_tips": False,
    },
    "quality": {
        "title": "Quality",
        "keywords": [
            "build",
            "compilation",
            "compile",
            "warning",
            "test",
            "wiring",
            "integration",
            "import",
            "modelcontext",
            "swiftdata",
        ],
        "include_patterns": False,
        "include_deploy_tips": False,
    },
    "deploy": {
        "title": "Deploy",
        "keywords": [
            "deploy",
            "archive",
            "upload",
            "testflight",
            "signing",
            "provisioning",
            "asc",
            "app store",
            "bundle identifier",
            "team",
        ],
        "include_patterns": False,
        "include_deploy_tips": True,
    },
}

PHASE_FILE_ALIASES: dict[str, list[str]] = {
    "architecture": ["architecture.md", "phase-1-architecture.md"],
    "parallel_coding": ["parallel_coding.md", "phase-4-parallel-coding.md"],
    "quality": ["quality.md", "phase-5-quality.md"],
    "deploy": ["deploy.md", "phase-6-deploy.md"],
}


def percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return " ".join(text.split())


def top_common_errors(patterns: dict[str, Any]) -> list[dict[str, Any]]:
    errors = patterns.get("common_build_errors", [])
    if not isinstance(errors, list):
        return []
    sorted_errors = sorted(
        (item for item in errors if isinstance(item, dict)),
        key=lambda item: int(item.get("frequency", 0) or 0),
        reverse=True,
    )
    return sorted_errors[:5]


def top_architectures(patterns: dict[str, Any]) -> list[dict[str, Any]]:
    architectures = patterns.get("effective_architectures", [])
    if not isinstance(architectures, list):
        return []
    sorted_architectures = sorted(
        (item for item in architectures if isinstance(item, dict)),
        key=lambda item: (
            float(item.get("successRate", 0) or 0),
            len(clean_text(item.get("pattern"))),
        ),
        reverse=True,
    )
    return sorted_architectures[:3]


def top_strings(values: Any, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    items = [clean_text(value) for value in values]
    return [item for item in items if item][:limit]


def top_improvements(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    priority_order = {"high": 0, "medium": 1, "low": 2}

    pending = [
        item for item in items
        if isinstance(item, dict) and not bool(item.get("implemented"))
    ]
    pending.sort(
        key=lambda item: (
            priority_order.get(clean_text(item.get("priority")).lower(), 3),
            clean_text(item.get("description")),
        )
    )
    return pending[:3]


def matches_keywords(text: str, keywords: list[str]) -> bool:
    haystack = clean_text(text).lower()
    return any(keyword in haystack for keyword in keywords)


def filter_error_rules(patterns: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    return [
        item
        for item in top_common_errors(patterns)
        if matches_keywords(
            " ".join(
                [
                    clean_text(item.get("pattern")),
                    clean_text(item.get("fix")),
                    clean_text(item.get("prevention")),
                ]
            ),
            keywords,
        )
    ]


def filter_improvements(items: Any, keywords: list[str]) -> list[dict[str, Any]]:
    return [
        item
        for item in top_improvements(items)
        if matches_keywords(
            " ".join(
                [
                    clean_text(item.get("description")),
                    clean_text(item.get("reason")),
                    clean_text(item.get("priority")),
                ]
            ),
            keywords,
        )
    ]


def filter_failures(builds: Any, keywords: list[str], phase_name: str) -> list[str]:
    matched: list[str] = []
    for entry in recent_failures(builds):
        if f"/ {phase_name}:" in entry.lower() or matches_keywords(entry, keywords):
            matched.append(entry)
    return matched[:3]


def recent_failures(builds: Any) -> list[str]:
    if not isinstance(builds, list):
        return []

    summaries: list[str] = []
    for build in reversed(builds):
        if not isinstance(build, dict):
            continue
        errors = build.get("errors", [])
        if not isinstance(errors, list) or not errors:
            continue

        app_name = clean_text(build.get("appName")) or clean_text(build.get("id")) or "unknown build"
        for error in errors:
            if not isinstance(error, dict):
                continue
            phase = clean_text(error.get("phase")) or "unknown phase"
            message = clean_text(error.get("message")) or clean_text(error.get("type")) or "unknown error"
            fix = clean_text(error.get("fix"))
            line = f"{app_name} / {phase}: {message}"
            if fix:
                line += f" -> {fix}"
            summaries.append(line)
            if len(summaries) >= 3:
                return summaries

    return summaries


def render_markdown(data: dict[str, Any]) -> str:
    patterns = data.get("patterns", {})
    if not isinstance(patterns, dict):
        patterns = {}

    lines: list[str] = []
    lines.append("# Active Learnings")
    lines.append("")
    lines.append("Use this file as the distilled memory for the next Autobot build. Apply matching rules directly; do not re-read the full learnings history unless you need more detail.")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Total builds: {data.get('totalBuilds', 0)}")
    lines.append(f"- Success rate: {percent(data.get('successRate'))}")
    last_updated = clean_text(data.get("lastUpdated")) or "unknown"
    lines.append(f"- Last updated: {last_updated}")

    architectures = top_architectures(patterns)
    if architectures:
        lines.append("")
        lines.append("## Proven Patterns")
        for item in architectures:
            app_type = clean_text(item.get("appType")) or "general"
            pattern = clean_text(item.get("pattern")) or "No pattern recorded"
            success_rate = percent(item.get("successRate"))
            notes = clean_text(item.get("notes"))
            line = f"- {app_type}: {pattern} (success {success_rate})"
            if notes:
                line += f" -- {notes}"
            lines.append(line)

    errors = top_common_errors(patterns)
    if errors:
        lines.append("")
        lines.append("## Prevention Rules")
        for item in errors:
            pattern = clean_text(item.get("pattern")) or "Unknown error"
            frequency = int(item.get("frequency", 0) or 0)
            prevention = clean_text(item.get("prevention")) or clean_text(item.get("fix")) or "No prevention recorded"
            lines.append(f"- {pattern} ({frequency}x): {prevention}")

    deployment_tips = top_strings(patterns.get("deployment_tips"), 3)
    if deployment_tips:
        lines.append("")
        lines.append("## Deployment Tips")
        for tip in deployment_tips:
            lines.append(f"- {tip}")

    agent_strategies = top_strings(patterns.get("agent_strategies"), 3)
    if agent_strategies:
        lines.append("")
        lines.append("## Agent Strategy")
        for strategy in agent_strategies:
            lines.append(f"- {strategy}")

    improvements = top_improvements(data.get("improvement_queue"))
    if improvements:
        lines.append("")
        lines.append("## Pending Improvements")
        for item in improvements:
            priority = clean_text(item.get("priority")).upper() or "UNKNOWN"
            description = clean_text(item.get("description")) or "No description"
            reason = clean_text(item.get("reason"))
            line = f"- [{priority}] {description}"
            if reason:
                line += f" -- {reason}"
            lines.append(line)

    failures = recent_failures(data.get("builds"))
    if failures:
        lines.append("")
        lines.append("## Recent Failure Memory")
        for failure in failures:
            lines.append(f"- {failure}")

    lines.append("")
    return "\n".join(lines)


def render_phase_markdown(data: dict[str, Any], phase_name: str, config: dict[str, Any]) -> str:
    patterns = data.get("patterns", {})
    if not isinstance(patterns, dict):
        patterns = {}

    keywords = config["keywords"]
    lines: list[str] = []
    lines.append(f"# {config['title']} Learnings")
    lines.append("")
    lines.append(
        "Read this file first for the current phase. It contains only the learnings most likely to change decisions in this phase."
    )
    lines.append("")
    lines.append("## Phase Focus")
    lines.append(f"- Phase: {phase_name}")
    lines.append(f"- Total builds considered: {data.get('totalBuilds', 0)}")
    lines.append(f"- Success rate baseline: {percent(data.get('successRate'))}")

    if config.get("include_patterns"):
        architectures = top_architectures(patterns)
        if architectures:
            lines.append("")
            lines.append("## Relevant Proven Patterns")
            for item in architectures:
                app_type = clean_text(item.get("appType")) or "general"
                pattern = clean_text(item.get("pattern")) or "No pattern recorded"
                notes = clean_text(item.get("notes"))
                line = f"- {app_type}: {pattern}"
                if notes:
                    line += f" -- {notes}"
                lines.append(line)

    rules = filter_error_rules(patterns, keywords)
    if rules:
        lines.append("")
        lines.append("## Relevant Prevention Rules")
        for item in rules:
            pattern = clean_text(item.get("pattern")) or "Unknown error"
            frequency = int(item.get("frequency", 0) or 0)
            prevention = clean_text(item.get("prevention")) or clean_text(item.get("fix")) or "No prevention recorded"
            lines.append(f"- {pattern} ({frequency}x): {prevention}")

    if config.get("include_deploy_tips"):
        deployment_tips = top_strings(patterns.get("deployment_tips"), 5)
        if deployment_tips:
            lines.append("")
            lines.append("## Relevant Deployment Tips")
            for tip in deployment_tips:
                lines.append(f"- {tip}")

    improvements = filter_improvements(data.get("improvement_queue"), keywords)
    if improvements:
        lines.append("")
        lines.append("## Relevant Pending Improvements")
        for item in improvements:
            priority = clean_text(item.get("priority")).upper() or "UNKNOWN"
            description = clean_text(item.get("description")) or "No description"
            reason = clean_text(item.get("reason"))
            line = f"- [{priority}] {description}"
            if reason:
                line += f" -- {reason}"
            lines.append(line)

    failures = filter_failures(data.get("builds"), keywords, phase_name)
    if failures:
        lines.append("")
        lines.append("## Relevant Failure Memory")
        for failure in failures:
            lines.append(f"- {failure}")

    if len(lines) == 6:
        lines.append("")
        lines.append("## Relevant Prevention Rules")
        lines.append("- No phase-specific learnings yet. Fall back to `.autobot/active-learnings.md`.")

    lines.append("")
    return "\n".join(lines)


def summarize(data: dict[str, Any]) -> str:
    patterns = data.get("patterns", {})
    if not isinstance(patterns, dict):
        patterns = {}

    return (
        f"builds={data.get('totalBuilds', 0)}, "
        f"success_rate={percent(data.get('successRate'))}, "
        f"prevention_rules={len(top_common_errors(patterns))}, "
        f"proven_patterns={len(top_architectures(patterns))}, "
        f"pending_improvements={len(top_improvements(data.get('improvement_queue')))}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    autobot_dir = project_dir / ".autobot"
    learnings_file = autobot_dir / "learnings.json"
    output_file = autobot_dir / "active-learnings.md"
    phase_dir = autobot_dir / "phase-learnings"

    if not learnings_file.exists():
        if output_file.exists():
            output_file.unlink()
        if phase_dir.exists():
            shutil.rmtree(phase_dir)
        print("available=false")
        return 0

    try:
        data = json.loads(learnings_file.read_text())
    except json.JSONDecodeError:
        output_file.write_text(
            "# Active Learnings\n\n"
            "learnings.json exists but could not be parsed. Ignore cached learnings and repair the file before the next build.\n"
        )
        print("available=invalid")
        return 0

    autobot_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_text(render_markdown(data))
    phase_dir.mkdir(parents=True, exist_ok=True)
    for phase_name, config in PHASE_CONFIG.items():
        rendered = render_phase_markdown(data, phase_name, config)
        for filename in PHASE_FILE_ALIASES.get(phase_name, [f"{phase_name}.md"]):
            (phase_dir / filename).write_text(rendered)
    print(f"available=true {summarize(data)} path={output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
