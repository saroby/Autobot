#!/usr/bin/env python3
"""Pre-write sandbox guard — enforce `spec/pipeline.json.fileOwnership` BEFORE
a structured file-edit tool call (Write / Edit / NotebookEdit) mutates a
forbidden path.

The existing `sandbox_runner.py` (`agent-sandbox.sh before/after`) flow is
*post-hoc*: it diffs the filesystem and records violations only after damage is
done. This guard wires the SAME decision function (`sandbox_runner.
evaluate_violations`) into a PreToolUse hook so attempted writes are caught
before they reach disk. Reusing one decision function — rather than a second
re-implementation — is deliberate: it is the only way the pre-write guard and
the post-hoc enforcer cannot drift apart.

Scope (be honest about what this does and does NOT cover):
    - Covers Write / Edit / NotebookEdit. It does NOT see `Bash` writes
      (`mv`, `cp`, `sed -i`, redirection, build scripts) — the PreToolUse hook
      matcher only fires for the structured editors. Bash-path mutations are
      caught post-hoc by `sandbox_runner.py` at Gate 4→5. (Earlier this
      docstring claimed it guarded Bash; it never did.)
    - The "forbidden floor" — `forbiddenAlways` ({appName}/Models/) and
      `forbiddenInfra` (.autobot control files) — is enforced for EVERY agent,
      INCLUDING broadAccess agents, unless that agent is in the matching
      *Exempt list. So even quality-engineer (broadAccess, Phase 5) can no
      longer clobber Models/ or the pipeline control files through Write/Edit.
    - Per-agent OVERLAP among the three Phase-4 coders (which run in parallel
      and share one marker, so the hook cannot attribute an individual write to
      one of them) is enforced post-hoc at Gate 4→5, not here. See SKILL.md.

Activation marker: `.autobot/.guard-active`
    Single-line JSON: {"agent": "ui-builder", "phase": "4"}
    The orchestrator writes this before dispatching an agent and removes it
    when the agent returns. When the marker is missing the guard treats the
    caller as `quality-engineer` (broadAccess) so orchestrator self-steps keep
    working — but the forbidden floor above still applies even then.
    NOTE: the hook (`hooks/sandbox-pre-write.sh`) is itself a no-op when no
    marker is present, so in production the guard only runs for a marked agent.

CLI:
    sandbox_guard.py check --target <path> [--agent <name>] [--project-dir .]
        exit 0 → allow
        exit 2 → block (prints a single-line `BLOCKED: ...` reason)

Hook integration: see `hooks/sandbox-pre-write.sh` which reads the tool call
payload from stdin, extracts the file path, and invokes `check`.
"""

from __future__ import annotations

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
# Reuse the post-hoc enforcer's decision function so the two layers can never
# diverge. evaluate_violations applies the full precedence:
#   forbiddenAlways → forbiddenInfra → forbiddenPerAgent → broadAccess → writes
from sandbox_runner import evaluate_violations  # noqa: E402


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
    # Default when no marker is set: quality-engineer (broadAccess) so the
    # orchestrator's own self-step edits keep working. The forbidden floor in
    # evaluate_violations still blocks Models/ and infra control files even for
    # this broadAccess default — broadAccess is no longer a blanket bypass.
    return "quality-engineer"


def _relpath(project_root: Path, target: Path) -> str:
    """Project-relative POSIX string, matching how `sandbox_runner.hash_tree`
    records touched paths (so `evaluate_violations`' prefix/exact `matches()`
    applies identically in both layers).

    Both sides are resolved first so a /var → /private/var symlink (macOS
    tmpdirs) or a `..` segment cannot defeat the relative_to. A target outside
    the project root has no project-relative form; we hand back its absolute
    POSIX path, which matches no relative allow/forbidden rule — so a non-broad
    agent is denied (OWNERSHIP) and a broadAccess agent is permitted, mirroring
    the post-hoc semantics for paths the snapshot never walks.
    """
    try:
        proot = project_root.resolve()
    except OSError:
        proot = project_root
    try:
        tr = target.resolve()
    except OSError:
        tr = target
    try:
        return tr.relative_to(proot).as_posix()
    except ValueError:
        return tr.as_posix()


def check(project_root: Path, target: Path, agent: str | None = None) -> tuple[bool, str]:
    """Return (allowed, reason).

    Delegates the verdict to `sandbox_runner.evaluate_violations` — the single
    source of truth shared with the post-hoc enforcer — so the forbidden floor
    (Models/ + .autobot control files) is enforced for every agent including
    broadAccess, and the two layers cannot drift.
    """
    spec = _load_spec()
    agents = (spec.get("fileOwnership") or {}).get("agents") or {}

    active = _active_agent(project_root, agent)
    if active not in agents:
        # Unknown agent → deny by default. The operator must pass a real
        # --agent (e.g. quality-engineer for broadAccess) or set the marker.
        return False, f"unknown agent '{active}' — no ownership block in spec"

    state = try_load_state(state_file_for(project_root)) or {}
    app_name = state.get("appName") or os.environ.get("AUTOBOT_APP_NAME") or ""

    rel = _relpath(project_root, target)
    violations = evaluate_violations(spec, active, app_name, [rel])
    if not violations:
        return True, f"allowed for agent '{active}': {rel}"

    v = violations[0]
    return False, f"agent '{active}' may not write '{rel}' [{v['kind']}]: {v['message']}"


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
