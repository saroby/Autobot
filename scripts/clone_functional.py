#!/usr/bin/env python3
"""clone_functional.py — does the reproduction actually work?

    clone_functional.py <clone-root> <simulator-udid> [--bundle-id ID]

Polishing one screen to the pixel before knowing whether the app navigates is
the expensive order: a reproduction that looks right and goes nowhere is not a
reproduction. This walks the observed flow inside the running clone — from the
initial state, tap the label, read which screen came up — and reports every edge
as wired or broken, and every mapped state as reachable or not.

Pixel work belongs after this passes (`clone_run.sh polish`).

The app must already be installed on the simulator; `device_render.sh` does
that, and `clone_run.sh functional` calls it first.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


flow_codegen = _load("clone_flow_codegen")
view_codegen = _load("clone_view_codegen")

BUNDLE_ID = "autobot.clone.preview"
ROOT_VIEW = "ObservedFlowRootView"


def _labels(tree) -> list[str]:
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key in ("AXLabel", "label", "title", "AXValue"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    found.append(value.strip())
                    break
            for child in node.get("children") or []:
                walk(child)

    for root in (tree if isinstance(tree, list) else [tree]):
        walk(root)
    return found


def current_state(udid: str, attempts: int = 12) -> str | None:
    """The state key the running clone says it is showing, or None."""
    for attempt in range(attempts):
        result = subprocess.run(["axe", "describe-ui", "--udid", udid],
                                capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                tree = json.loads(result.stdout)
            except json.JSONDecodeError:
                tree = None
            if tree is not None:
                for label in _labels(tree):
                    if label.startswith(view_codegen.STATE_MARKER):
                        return label[len(view_codegen.STATE_MARKER):]
        if attempt + 1 < attempts:
            time.sleep(0.25)
    return None


def relaunch(udid: str, bundle_id: str) -> None:
    subprocess.run(["xcrun", "simctl", "terminate", udid, bundle_id],
                   capture_output=True, text=True)
    subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process",
                    udid, bundle_id], capture_output=True, text=True,
                   env={**os.environ, "SIMCTL_CHILD_CLONE_ROOT_VIEW": ROOT_VIEW})


ACTION_ID = "clone-action:"
SYNTH_ID = "clone-action-synth:"


def tap(udid: str, label: str) -> str | None:
    """Tap by identifier, not by label.

    A measured screen repeats the same label down its container chain — five
    elements labelled "게시 옵션" at one frame in the Threads feed — and AXe
    refuses an ambiguous label outright. The generated views put the action on
    exactly one element and give it this identifier.
    """
    for kind, selector in (("measured", ["--id", ACTION_ID + label]),
                           ("synthesised", ["--id", SYNTH_ID + label]),
                           ("measured", ["--label", label])):
        result = subprocess.run(
            ["axe", "tap", *selector, "--udid", udid,
             "--post-delay", "0.25", "--wait-timeout", "2"],
            capture_output=True, text=True)
        if result.returncode == 0:
            return kind
    return None


def shortest_paths(transitions: list[tuple[str, str, str]],
                   initial: str) -> dict[str, list[tuple[str, str]]]:
    """state -> the (label, destination) hops that reach it from `initial`.

    Back actions are left out. A pop lands wherever you came from, so it cannot
    be used to route TO a named screen — and following one as if it could would
    make the walk expect a screen it has no reason to be on.
    """
    outgoing: dict[str, list[tuple[str, str]]] = {}
    for source, action, destination in transitions:
        if destination == flow_codegen.POP:
            continue
        outgoing.setdefault(source, []).append((action, destination))
    paths = {initial: []}
    queue = [initial]
    while queue:
        state = queue.pop(0)
        for action, destination in outgoing.get(state, []):
            if destination in paths:
                continue
            paths[destination] = paths[state] + [(action, destination)]
            queue.append(destination)
    return paths


def replay(udid: str, bundle_id: str, path: list[tuple[str, str]]) -> str | None:
    relaunch(udid, bundle_id)
    state = current_state(udid)
    for action, expected in path:
        if not tap(udid, action):
            return None
        state = current_state(udid)
        if state != expected:
            return None
    return state


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root")
    parser.add_argument("udid")
    parser.add_argument("--bundle-id", default=BUNDLE_ID)
    args = parser.parse_args(argv[1:])
    # The walk is minutes long and its whole value is watching it progress; a
    # block-buffered pipe turns it into a black box that looks like a hang.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    root = Path(args.root)
    events = flow_codegen.load_flow(root / "flow.jsonl")
    captured = set(flow_codegen.captured_states(events))
    transitions = flow_codegen.observed_transitions(events, captured)
    views = json.loads((root / "views.json").read_text(encoding="utf-8"))
    initial = views.get("initial_state")
    mapped = set(views.get("views", {}))
    if not initial:
        print("ERROR: views.json has no initial_state", file=sys.stderr)
        return 1

    paths = shortest_paths(transitions, initial)
    unreachable = sorted(mapped - set(paths))
    edges = [edge for edge in transitions if edge[0] in paths]
    skipped = [edge for edge in transitions if edge[0] not in paths]

    # Walk from wherever the app already is. The router has no back gesture, so
    # getting somewhere else costs a relaunch and a replay of the whole path —
    # testing every edge that way was 56 relaunches and over six minutes. Taking
    # the edges that leave the CURRENT screen first turns most of those into a
    # single tap.
    pending = list(edges)
    wired, synthesised, broken, relaunches = 0, 0, [], 0
    # Mirrors the router's own history. The walk takes whatever edge leaves the
    # screen it is already on, so it does NOT always arrive by the shortest
    # path — computing a pop's expected landing from `paths` guessed the wrong
    # predecessor. What a pop returns to is what this walk actually came from.
    walked: list[str] = []

    def rewind(path: list[tuple[str, str]]) -> None:
        walked.clear()
        walked.append(initial)
        walked.extend(destination for _action, destination in path[:-1])

    state = replay(args.udid, args.bundle_id, [])
    rewind([])
    relaunches += 1
    while pending:
        here = [edge for edge in pending if edge[0] == state]
        if not here:
            reachable = [edge for edge in pending if edge[0] in paths]
            if not reachable:
                break
            target = min(reachable, key=lambda edge: len(paths[edge[0]]))[0]
            state = replay(args.udid, args.bundle_id, paths[target])
            rewind(paths[target])
            relaunches += 1
            if state != target:
                for edge in [edge for edge in pending if edge[0] == target]:
                    pending.remove(edge)
                    broken.append((*edge, f"could not get to {target} (stopped at {state})"))
                continue
            here = [edge for edge in pending if edge[0] == state]
        source, action, destination = here[0]
        pending.remove(here[0])
        kind = tap(args.udid, action)
        if kind is None:
            broken.append((source, action, destination, "no element with that label"))
            state = replay(args.udid, args.bundle_id, paths[source])
            relaunches += 1
            continue
        landed = current_state(args.udid)
        popping = destination == flow_codegen.POP
        if popping:
            # A pop has no fixed destination; it lands on wherever this walk
            # arrived from. That is exactly the thing a state->action->state
            # table cannot say, so it is the thing worth checking.
            destination = walked[-1] if walked else initial
        if landed == destination:
            wired += 1
            synthesised += kind == "synthesised"
            if popping:
                if walked:
                    walked.pop()
            else:
                walked.append(source)
            note = " (synthesised target)" if kind == "synthesised" else ""
            print(f"INFO: ok {source} --{action}--> {destination}"
                  f"{' (back)' if popping else ''}{note}")
        else:
            broken.append((source, action, destination, f"landed on {landed}"))
            print(f"INFO: BROKEN {source} --{action}--> {destination} (landed on {landed})")
            # The history no longer describes where the app is; the next jump
            # replays a path and rewinds it anyway.
            walked.clear()
        state = landed
    for edge in pending:
        broken.append((*edge, "never exercised — the walk could not reach its screen"))
    print(f"INFO: {relaunches} relaunch(es) for {len(edges)} transition(s)")

    for source, action, destination, why in broken:
        print(f"ERROR: {source} --{action}--> {destination}: {why}", file=sys.stderr)
    if unreachable:
        # Not the reproduction's fault and not its to fix: the OBSERVED flow has
        # no edge into these at all, so no clone of it could navigate there.
        # Blaming the reproduction here would send someone to edit SwiftUI for a
        # hole that only another `observe` run can close.
        print(f"WARN: {len(unreachable)} mapped screen(s) have no observed path from "
              f"{initial} — the exploration recorded the screen but never a way in. "
              f"Run 'clone_run.sh observe' again to close it: {', '.join(unreachable)}",
              file=sys.stderr)
    if skipped:
        # Not a pass: these edges start somewhere the walk never gets to, so
        # nothing here says whether they work.
        print(f"WARN: {len(skipped)} observed transition(s) start from an "
              "unreachable screen and were not exercised", file=sys.stderr)
    print(f"INFO: {wired}/{len(edges)} reachable transition(s) wired"
          + (f" ({synthesised} of them on a target synthesised at a recorded tap "
             "point, because the label is not in the capture that screen is "
             "reproduced from)" if synthesised else "")
          + f", "
          f"{len(mapped) - len(unreachable)}/{len(mapped)} mapped screen(s) reachable"
          + (f" ({len(unreachable)} unreachable in the observed flow itself)"
             if unreachable else ""))
    if broken:
        return 1
    print("OK: the reproduction navigates exactly like the observed flow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
