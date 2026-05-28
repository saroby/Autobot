#!/usr/bin/env python3
"""Pre-write sandbox guard — enforce `spec/pipeline.json.fileOwnership` BEFORE
an agent's Write/Edit/Bash tool call mutates a forbidden path.

The existing `agent-sandbox.sh before/after` flow is *post-hoc*: it diffs the
filesystem and records violations only after damage is done. This guard wires
the same ownership matrix into a PreToolUse hook so attempted writes outside
the owner's allow-list never reach disk.

Activation marker: `.autobot/.guard-active`
    Single-line JSON: {"agent": "ui-builder", "phase": "4"}
    Skill agents write this on dispatch and remove it when they return. When
    the marker is missing the guard treats the caller as `quality-engineer`
    (broadAccess) so direct orchestrator edits keep working.

Allow-list resolution:
    spec.fileOwnership.agents.<agent>.writes      → allow patterns
    spec.fileOwnership.agents.<agent>.broadAccess → True bypasses the check
    spec.fileOwnership.shared.writes              → always allowed
    {appName} placeholders are expanded from build-state.json
    Targets matching glob patterns (Path.match) are allowed.

CLI:
    sandbox_guard.py check --target <path> [--agent <name>] [--project-dir .]
        exit 0 → allow
        exit 2 → block (prints a single-line `BLOCKED: ...` reason)

Hook integration: see `hooks/sandbox-pre-write.sh` which reads the tool call
payload from stdin, extracts the file path, and invokes `check`.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
SPEC_PATH = PLUGIN_DIR / "spec" / "pipeline.json"
GUARD_MARKER = ".autobot/.guard-active"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_store import state_file_for, try_load_state  # noqa: E402


def _load_spec() -> dict:
    with SPEC_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _active_agent(project_root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    env_agent = os.environ.get("AUTOBOT_ACTIVE_AGENT")
    if env_agent:
        return env_agent
    marker = project_root / GUARD_MARKER
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            agent = data.get("agent")
            if isinstance(agent, str) and agent:
                return agent
        except (json.JSONDecodeError, OSError):
            pass
    return "quality-engineer"  # default: broad access (matches current pipeline behavior)


def _expand_placeholders(pattern: str, app_name: str) -> str:
    return pattern.replace("{appName}", app_name)


def _path_under(target: Path, allow: str, project_root: Path) -> bool:
    """Check whether `target` matches the allow pattern.

    Three shapes:
      - "dir/" → target is inside that directory tree
      - exact file path → equality
      - glob pattern (contains '*', '?', '[') → fnmatch
    """
    allow_path = (project_root / allow).resolve()
    try:
        target_resolved = target.resolve()
    except OSError:
        target_resolved = target

    if allow.endswith("/"):
        try:
            target_resolved.relative_to(allow_path)
            return True
        except ValueError:
            return False
    if any(ch in allow for ch in ("*", "?", "[")):
        rel_target = str(target_resolved.relative_to(project_root)) if str(target_resolved).startswith(str(project_root.resolve())) else str(target_resolved)
        return fnmatch.fnmatchcase(rel_target, allow) or fnmatch.fnmatchcase(target_resolved.name, allow)
    return target_resolved == allow_path


def check(project_root: Path, target: Path, agent: str | None = None) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    spec = _load_spec()
    ownership = spec.get("fileOwnership") or {}
    agents = ownership.get("agents") or {}
    shared = ownership.get("shared", {}).get("writes", []) or []

    active = _active_agent(project_root, agent)
    agent_block = agents.get(active)
    if agent_block is None:
        # Unknown agent → deny by default. Operator must explicitly pass
        # --agent quality-engineer (broadAccess) or set the marker.
        return False, f"unknown agent '{active}' — no ownership block in spec"

    if agent_block.get("broadAccess"):
        return True, f"agent '{active}' has broadAccess"

    state = try_load_state(state_file_for(project_root)) or {}
    app_name = state.get("appName") or os.environ.get("AUTOBOT_APP_NAME") or ""

    # Always-shared paths (e.g. .autobot/build-log.jsonl) are allowed for any agent.
    candidates = []
    for raw in (agent_block.get("writes") or []):
        candidates.append(_expand_placeholders(raw, app_name) if app_name else raw)
    for raw in shared:
        candidates.append(_expand_placeholders(raw, app_name) if app_name else raw)

    if not candidates:
        return False, f"agent '{active}' has no declared writes — every write is forbidden"

    for allow in candidates:
        if _path_under(target, allow, project_root):
            return True, f"matches '{allow}' for agent '{active}'"

    return False, (
        f"agent '{active}' may not write '{target}' — "
        f"allowed: {', '.join(candidates[:6])}"
        + ("..." if len(candidates) > 6 else "")
    )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_chk = sub.add_parser("check")
    p_chk.add_argument("--project-dir", default=".")
    p_chk.add_argument("--target", required=True)
    p_chk.add_argument("--agent")
    p_set = sub.add_parser("set-active")
    p_set.add_argument("--project-dir", default=".")
    p_set.add_argument("--agent", required=True)
    p_set.add_argument("--phase", default="")
    p_clr = sub.add_parser("clear-active")
    p_clr.add_argument("--project-dir", default=".")
    args = parser.parse_args()

    proj = Path(args.project_dir).resolve()
    if args.cmd == "set-active":
        marker = proj / GUARD_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"agent": args.agent, "phase": args.phase}), encoding="utf-8")
        print(f"OK: guard active for agent={args.agent} phase={args.phase}")
        return 0
    if args.cmd == "clear-active":
        marker = proj / GUARD_MARKER
        if marker.exists():
            marker.unlink()
        print("OK: guard cleared")
        return 0

    allowed, reason = check(proj, Path(args.target), agent=args.agent)
    if allowed:
        print(f"OK: {reason}")
        return 0
    print(f"BLOCKED: {reason}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
