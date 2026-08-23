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
import struct
import subprocess
import sys
import tempfile
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

_TAP_SCALE: dict[str, float] = {}


def tap_scale(udid: str) -> float:
    """How far AXe's tap coordinates drift from the app's, per point.

    iPhone 12/13 mini render at 375x812 @3x (1125x2436) and the simulator
    downsamples that to the 1080x2340 panel. AXe maps points to the PANEL, the
    app hit-tests in the render buffer, so a tap requested at y lands at
    y*2436/2340 — 4% low, ~30pt by the tab bar. Measured 2026-08-23 with a
    four-target probe: every bottom-of-screen target missed and the tap fell
    through onto the tab bar beneath it. A finger on the real device has no
    such drift; only this driver does, so only this driver corrects for it.
    """
    if udid in _TAP_SCALE:
        return _TAP_SCALE[udid]
    scale = 1.0
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            shot = handle.name
        subprocess.run(["xcrun", "simctl", "io", udid, "screenshot", shot],
                       capture_output=True, check=True)
        with open(shot, "rb") as handle:
            head = handle.read(24)
        panel_w, panel_h = struct.unpack(">II", head[16:24])
        tree = subprocess.run(["axe", "describe-ui", "--udid", udid],
                              capture_output=True, text=True, check=True).stdout
        root = json.loads(tree)
        root = root[0] if isinstance(root, list) else root
        frame = root.get("frame") or {}
        logical_h = float(frame.get("height") or 0)
        if logical_h > 0:
            render_scale = round(panel_h / logical_h)          # 3 for a 12 mini
            scale = panel_h / (logical_h * render_scale)       # 2340 / 2436
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError,
            struct.error, KeyError, TypeError):
        scale = 1.0
    finally:
        try:
            os.unlink(shot)
        except (OSError, NameError):
            pass
    _TAP_SCALE[udid] = scale
    return scale


def _find_target(tree, label: str) -> tuple[str, dict] | None:
    wanted = {ACTION_ID + label: "measured", SYNTH_ID + label: "synthesised"}
    by_label = None

    def walk(node):
        nonlocal by_label
        if not isinstance(node, dict):
            return None
        uid = node.get("AXUniqueId") or ""
        if uid in wanted and node.get("frame"):
            return wanted[uid], node["frame"]
        if by_label is None and (node.get("AXLabel") or "") == label and node.get("frame"):
            by_label = node["frame"]
        for child in node.get("children") or []:
            found = walk(child)
            if found:
                return found
        return None

    for root in (tree if isinstance(tree, list) else [tree]):
        found = walk(root)
        if found:
            return found
    return ("measured", by_label) if by_label else None


def tap(udid: str, label: str) -> str | None:
    """Tap the target's centre by corrected coordinates.

    Resolved by identifier, not label: a measured screen repeats the same label
    down its container chain — five elements labelled "게시 옵션" at one frame
    in the Threads feed. The generated views put the action on exactly one
    element and give it this identifier. The centre is then corrected for the
    driver's coordinate drift (see tap_scale) before tapping.
    """
    result = subprocess.run(["axe", "describe-ui", "--udid", udid],
                            capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        tree = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    found = _find_target(tree, label)
    if not found:
        return None
    kind, frame = found
    try:
        cx = float(frame["x"]) + float(frame["width"]) / 2
        cy = float(frame["y"]) + float(frame["height"]) / 2
    except (KeyError, TypeError, ValueError):
        return None
    factor = tap_scale(udid)
    result = subprocess.run(
        ["axe", "tap", "-x", f"{cx * factor:.1f}", "-y", f"{cy * factor:.1f}",
         "--udid", udid, "--post-delay", "0.25"],
        capture_output=True, text=True)
    return kind if result.returncode == 0 else None


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
    views = json.loads((root / "views.json").read_text(encoding="utf-8"))
    initial = views.get("initial_state")
    mapped = set(views.get("views", {}))
    # The router is generated from views.json, so that is the state set the
    # walk may expect. Using every captured state instead reported edges into
    # screens the router had never heard of as BROKEN — after an interrupted
    # observe appended new captures the router was not regenerated for.
    observed, inferred = flow_codegen.all_transitions(events, mapped, root / "screens")
    transitions = observed + inferred
    inferred_keys = {(s_, a_) for s_, a_, _d in inferred}
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
    inferred_wired = 0
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
            inferred_wired += (source, action) in inferred_keys
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

    # An edge the clone has no target for (an ambiguous synthesised target was
    # dropped, say) takes every screen behind it with it. Those downstream
    # edges are not wired wrong — they were never reached. Re-derive
    # reachability without the missing targets and report them as such, so the
    # one real gap is counted once and the fix (re-observe, or a capture that
    # has the label) is named once.
    missing = {(s_, a_) for s_, a_, _d, why in broken if why == "no element with that label"}
    if missing:
        remaining = [edge for edge in transitions if (edge[0], edge[1]) not in missing]
        still = shortest_paths(remaining, initial)
        downstream = [entry for entry in broken
                      if entry[3].startswith("could not get to") and entry[0] not in still]
        for entry in downstream:
            broken.remove(entry)
        if downstream:
            lost = sorted({entry[0] for entry in downstream})
            print(f"WARN: {len(downstream)} transition(s) start from screen(s) the clone "
                  f"cannot reach without a missing target ({', '.join(lost)}) — "
                  "fix the missing target and these follow", file=sys.stderr)
    print(f"INFO: {relaunches} relaunch(es) for {len(edges)} transition(s)")

    for source, action, destination, why in broken:
        print(f"ERROR: {source} --{action}--> {destination}: {why}", file=sys.stderr)
    if unreachable:
        # This is an observation gap rather than a clone-wiring defect, but the
        # functional gate still cannot certify navigation it never exercised.
        print(f"ERROR: {len(unreachable)} mapped screen(s) have no observed path from "
              f"{initial} — the exploration recorded the screen but never a way in. "
              f"Run 'clone_run.sh observe' again to close it: {', '.join(unreachable)}",
              file=sys.stderr)
    if skipped:
        print(f"ERROR: {len(skipped)} observed transition(s) start from an "
              "unreachable screen and were not exercised", file=sys.stderr)
    if inferred:
        # Inferred edges were never seen on the device; passing here proves the
        # clone's wiring matches the INFERENCE, not the app. Say how many.
        print(f"INFO: {len(inferred)} transition(s) are inferred from persistent controls "
              f"observed on other screens (tab bar and the like) — {inferred_wired} of them wired")
    print(f"INFO: {wired}/{len(edges)} reachable transition(s) wired"
          + (f" ({synthesised} of them on a target synthesised at a recorded tap "
             "point, because the label is not in the capture that screen is "
             "reproduced from)" if synthesised else "")
          + f", "
          f"{len(mapped) - len(unreachable)}/{len(mapped)} mapped screen(s) reachable"
          + (f" ({len(unreachable)} unreachable in the observed flow itself)"
             if unreachable else ""))
    failures = []
    if broken:
        failures.append(f"{len(broken)} broken transition(s)")
    if unreachable:
        failures.append(f"{len(unreachable)} unreachable mapped screen(s)")
    if skipped:
        failures.append(f"{len(skipped)} skipped transition(s)")
    if failures:
        print(f"ERROR: functional gate failed: {'; '.join(failures)}", file=sys.stderr)
        return 1
    print("OK: the reproduction navigates exactly like the observed flow")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
