#!/usr/bin/env python3
"""Agent file-ownership sandbox: snapshot → diff → enforce against spec.

Ownership rules live in spec/pipeline.json under fileOwnership. Violations
are recorded into the build state (phases.<phase>.sandbox.violations) and
emitted as 'sandbox_violation' / 'sandbox_clean' events through the runtime,
so Gate 4→5's sandbox_clean check can read them.

Subcommands:
    snapshot --agent <name> --app-name <App> [--project-dir DIR]
    verify   --agent <name> --app-name <App> --phase <N> [--project-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SPEC_PATH = SCRIPT_DIR.parent / "spec" / "pipeline.json"

# Import the focused runtime modules directly. We deliberately bypass
# runtime.py (which is a re-export facade) so loading this script does not
# pull in cli.py and the entire argparse tree.
sys.path.insert(0, str(SCRIPT_DIR))
from event_log import append_build_log  # noqa: E402  (import after sys.path mutation)
from spec_loader import load_spec, resolve_app_template  # noqa: E402
from state_store import (  # noqa: E402
    load_state,
    mutate_state_with_validation,
    state_file_from_args,
    utc_now,
)


def _snapshot_roots_from_spec(spec: dict[str, Any], app_name: str) -> list[str]:
    """Derive snapshot root directories from spec.fileOwnership.

    Roots = the top-level segment of every agent's writes path. Plus the
    pipeline's own infra root (.autobot) so changes there are also detected.
    The result is the minimal set of directories the sandbox must walk to see
    every file any agent could legitimately touch.
    """
    ownership = spec.get("fileOwnership", {})
    roots: set[str] = {".autobot"}
    for cfg in ownership.get("agents", {}).values():
        for raw in cfg.get("writes", []):
            resolved = raw.replace("{appName}", app_name).rstrip("/")
            if not resolved:
                continue
            top = resolved.split("/", 1)[0]
            if top:
                roots.add(top)
    # Sorted for deterministic snapshot output (helps diffing).
    return sorted(roots)


# Files that change every command (state, log, lock) must never enter the
# sandbox diff — agents legitimately don't write them, but they mutate
# between snapshot/verify and would surface as false-positive violations.
_DIFF_IGNORE_PATHS = frozenset({
    ".autobot/build-state.json",
    ".autobot/build-log.jsonl",
    ".autobot/build.lock",
})
_DIFF_IGNORE_PREFIXES = (".autobot/sandbox/",)


def hash_tree(project_dir: Path, app_name: str, spec: dict[str, Any] | None = None) -> dict[str, str]:
    if spec is None:
        spec = load_spec()
    snapshot: dict[str, str] = {}
    for rel in _snapshot_roots_from_spec(spec, app_name):
        root = project_dir / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(project_dir).as_posix()
            if rel_path in _DIFF_IGNORE_PATHS:
                continue
            if any(rel_path.startswith(p) for p in _DIFF_IGNORE_PREFIXES):
                continue
            with path.open("rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            snapshot[rel_path] = digest
    return snapshot


def write_snapshot(target: Path, project_dir: Path, app_name: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    snap = hash_tree(project_dir, app_name)
    # Atomic write via tmp + rename so a partial snapshot can never be observed.
    tmp = target.with_name(f".{target.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(snap, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(target)


def _ensure_known_agent(spec: dict[str, Any], agent: str) -> None:
    agents_cfg = spec.get("fileOwnership", {}).get("agents", {})
    if agent not in agents_cfg:
        known = ", ".join(sorted(agents_cfg))
        raise SystemExit(
            f"FATAL: agent '{agent}' is not declared in spec.fileOwnership.agents. "
            f"Known agents: {known}. "
            "Add the agent to spec/pipeline.json before running sandbox."
        )


resolve = resolve_app_template


def matches(rule: str, path: str) -> bool:
    """Directory rules end with '/' and match prefixes; file rules match exact."""
    if rule.endswith("/"):
        return path.startswith(rule)
    return path == rule


def evaluate_violations(
    spec: dict[str, Any], agent: str, app_name: str, touched: list[str],
) -> list[dict[str, str]]:
    ownership = spec.get("fileOwnership", {})
    agents_cfg = ownership.get("agents", {})
    agent_cfg = agents_cfg.get(agent, {})

    forbidden_always = [resolve(r, app_name) for r in ownership.get("forbiddenAlways", [])]
    forbidden_always_exempt = set(ownership.get("forbiddenAlwaysExempt", []))
    forbidden_infra = [resolve(r, app_name) for r in ownership.get("forbiddenInfra", [])]
    forbidden_infra_exempt = set(ownership.get("forbiddenInfraExempt", []))
    forbidden_per_agent = [
        resolve(r, app_name) for r in ownership.get("forbiddenPerAgent", {}).get(agent, [])
    ]
    allowed = [resolve(r, app_name) for r in agent_cfg.get("writes", [])]
    broad_access = bool(agent_cfg.get("broadAccess", False))

    violations: list[dict[str, str]] = []

    for path in touched:
        if agent not in forbidden_always_exempt:
            if any(matches(rule, path) for rule in forbidden_always):
                violations.append({"agent": agent, "kind": "FORBIDDEN", "path": path,
                                   "message": "wrote into Models/ (architect-only contract)"})
                continue

        if agent not in forbidden_infra_exempt:
            if any(matches(rule, path) for rule in forbidden_infra):
                violations.append({"agent": agent, "kind": "INFRA", "path": path,
                                   "message": "wrote into pipeline control file"})
                continue

        if any(matches(rule, path) for rule in forbidden_per_agent):
            violations.append({"agent": agent, "kind": "OVERLAP", "path": path,
                               "message": "wrote into another agent's directory"})
            continue

        if broad_access:
            continue
        # An agent without broadAccess and without any 'writes' rules is not
        # allowed to write anywhere; treat every touched path as OWNERSHIP
        # violation. (Earlier behavior was silent-pass on empty allowed.)
        if not any(matches(rule, path) for rule in allowed):
            violations.append({"agent": agent, "kind": "OWNERSHIP", "path": path,
                               "message": "wrote outside allowed directories"})
    return violations


def cmd_snapshot(args: argparse.Namespace) -> int:
    spec = load_spec()
    _ensure_known_agent(spec, args.agent)
    project_dir = Path(args.project_dir).resolve()
    sandbox_dir = project_dir / ".autobot" / "sandbox"
    target = sandbox_dir / f"{args.agent}.before.json"
    write_snapshot(target, project_dir, args.app_name)
    print(f"snapshot_saved: {target}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    spec = load_spec()
    _ensure_known_agent(spec, args.agent)
    project_dir = Path(args.project_dir).resolve()
    sandbox_dir = project_dir / ".autobot" / "sandbox"
    before_path = sandbox_dir / f"{args.agent}.before.json"
    after_path = sandbox_dir / f"{args.agent}.after.json"

    if not before_path.is_file():
        print(f"ERROR: missing 'before' snapshot for agent '{args.agent}': {before_path}", file=sys.stderr)
        return 2

    write_snapshot(after_path, project_dir, args.app_name)

    with before_path.open(encoding="utf-8") as handle:
        before = json.load(handle)
    with after_path.open(encoding="utf-8") as handle:
        after = json.load(handle)

    created  = sorted(p for p in after  if p not in before)
    deleted  = sorted(p for p in before if p not in after)
    modified = sorted(p for p in after  if p in before and after[p] != before[p])
    touched  = created + modified + deleted

    violations = evaluate_violations(spec, args.agent, args.app_name, touched)

    state_path = state_file_from_args(args)
    timestamp = args.at or utc_now()
    phase_id = str(args.phase)

    def mutate(next_state: dict[str, Any]) -> None:
        phases = next_state.setdefault("phases", {})
        phase_state = phases.setdefault(phase_id, {"status": "pending"})
        sandbox = phase_state.setdefault("sandbox", {"agentsVerified": [], "violations": []})
        agents_seen = sandbox.setdefault("agentsVerified", [])
        if args.agent not in agents_seen:
            agents_seen.append(args.agent)
            agents_seen.sort()
        existing = sandbox.setdefault("violations", [])
        # Drop prior entries for this agent before re-recording, so that a clean
        # re-run can clear earlier violations.
        existing[:] = [v for v in existing if v.get("agent") != args.agent]
        existing.extend(violations)

    mutate_state_with_validation(state_path, spec, mutate)

    summary = (
        f"{args.agent} — {len(created)} created, {len(modified)} modified, "
        f"{len(deleted)} deleted, {len(violations)} violations"
    )

    # Order: state mutation (above) → log append → snapshot cleanup. If the
    # log append fails the violation is already in state and the before/after
    # snapshots remain on disk for forensic inspection.
    if violations:
        for v in violations:
            print(f"VIOLATION: {v['kind']}: {v['agent']} {v['message']} → {v['path']}")
        append_build_log(
            project_dir, "sandbox_violation",
            phase=phase_id, agent=args.agent,
            detail={"summary": summary, "violations": violations, "touched": len(touched)},
            timestamp=timestamp, spec=spec,
        )
        before_path.unlink(missing_ok=True)
        after_path.unlink(missing_ok=True)
        print(f"SUMMARY: {summary}")
        return 1

    append_build_log(
        project_dir, "sandbox_clean",
        phase=phase_id, agent=args.agent,
        detail={"summary": summary, "touched": len(touched)},
        timestamp=timestamp, spec=spec,
    )
    before_path.unlink(missing_ok=True)
    after_path.unlink(missing_ok=True)
    print(f"OK: {summary}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent sandbox enforcer")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="Record pre-agent file hashes")
    snap.add_argument("--agent", required=True)
    snap.add_argument("--app-name", required=True)
    snap.add_argument("--project-dir", default=".")
    snap.set_defaults(func=cmd_snapshot)

    verify = sub.add_parser("verify", help="Compare to snapshot, enforce ownership, persist result")
    verify.add_argument("--agent", required=True)
    verify.add_argument("--app-name", required=True)
    verify.add_argument("--phase", required=True)
    verify.add_argument("--project-dir", default=".")
    verify.add_argument("--state-file")
    verify.add_argument("--at")
    verify.set_defaults(func=cmd_verify)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
