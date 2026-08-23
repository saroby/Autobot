#!/usr/bin/env python3
"""device_flow.py — the exploration run, read back.

`device_wda.sh` appends one JSON line per screen capture, tap, and swipe to
`.autobot/clone/flow.jsonl`. That log is the whole state of an exploration, which
is what makes the three things below possible:

    device_flow.py next <flow.jsonl>              What is still unexplored.
    device_flow.py todo <flow.jsonl> <tree.xml>    Unexplored safe candidates of THIS capture.
    device_flow.py next-tap <flow.jsonl> <tree.xml>  The ONE tap to make next.
    device_flow.py map  <flow.jsonl> <out.html>    The flow map, for a human.
    device_flow.py stats <flow.jsonl>              Coverage, one line.

`todo` is the machine half of `next`: same behavior-class frontier, but scoped
to one live capture so the coordinates it prints are valid for the tap guard
(which only accepts candidates of the tree currently on the device). It is what
lets `device_wda.sh explore` drain a screen without a human in the loop.

`next-tap` is what lets that loop cross screens. When the current capture still
has an unexplored candidate it returns that one; when the screen is drained it
walks the transitions already in the log to the nearest screen that is not, and
returns the FIRST HOP of that route — read out of the fresh tree it was handed,
never out of the log, so the stale-coordinate tap guard passes. Routing hops are
by definition edges already tapped, which is exactly why `todo` (which excludes
them) cannot answer this and a second query is needed.

`next` is also how a run RESUMES. On a real phone the session dies, the screen
locks, a login wall appears — exploration ending early is the normal case, not
the failure case. Re-reading the log rebuilds the frontier, so the next run picks
up instead of starting over.

Coverage is always reported, never assumed: a run that visited 6 of 30 targets
must not read as "explored everything". Screens the target app gated behind data
(an empty list that never shows its populated layout) are named too — they are
the difference between "reproduced the app" and "reproduced what we could reach".
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
import sys
from collections import OrderedDict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent


class FlowContractError(ValueError):
    pass


# Flow v2 contract. 0.13.10 accidentally shipped its WDA producer with the
# three underscored aliases below even though this reader already required the
# canonical names. Read those released logs so resumability survives upgrades;
# the producer integration test prevents new logs from drifting back.
RELEASED_STATE_ALIASES = {
    "state": "statekey",
    "from_state": "from_statekey",
    "to_state": "to_statekey",
}
UNOFFICIAL_STATE_FIELDS = {
    "state_key", "fromState", "toState",
}


def _validate_event(event: object, line_number: int) -> dict:
    if not isinstance(event, dict):
        raise FlowContractError(f"line {line_number}: event must be a JSON object")
    event = dict(event)
    for alias, canonical in RELEASED_STATE_ALIASES.items():
        if alias not in event:
            continue
        if canonical in event:
            raise FlowContractError(
                f"line {line_number}: conflicting state fields {alias} and {canonical}"
            )
        event[canonical] = event.pop(alias)
    aliases = sorted(UNOFFICIAL_STATE_FIELDS.intersection(event))
    if aliases:
        raise FlowContractError(
            f"line {line_number}: unsupported state field(s) {', '.join(aliases)}; "
            "use statekey/from_statekey/to_statekey"
        )
    event_type = event.get("type")
    if event_type == "screen" and not event.get("node"):
        raise FlowContractError(
            f"line {line_number}: screen event requires coarse node, including when statekey is present"
        )
    if event_type in ("tap", "swipe"):
        has_from_state = bool(event.get("from_statekey"))
        has_to_state = bool(event.get("to_statekey"))
        if has_from_state != has_to_state:
            raise FlowContractError(
                f"line {line_number}: {event_type} event must provide both "
                "from_statekey and to_statekey"
            )
    return event


def load(path: str) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if line:
                events.append(_validate_event(json.loads(line), line_number))
    return events


def _first_value(event: dict, *keys: str) -> str:
    for key in keys:
        value = event.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def screen_identity(event: dict) -> str:
    """Official statekey first; legacy node-only logs remain readable."""
    return _first_value(event, "statekey", "node")


def action_source(event: dict) -> str:
    return _first_value(event, "from_statekey", "from")


def action_destination(event: dict) -> str:
    return _first_value(event, "to_statekey", "to") or "?"


def screens(events: list[dict]) -> "OrderedDict[str, dict]":
    """state key (or legacy node key) → first capture of that state."""
    out: OrderedDict[str, dict] = OrderedDict()
    for e in events:
        key = screen_identity(e)
        if e.get("type") == "screen" and key and key not in out:
            out[key] = e
    return out


def screen_captures(events: list[dict]) -> "OrderedDict[str, list[dict]]":
    """state key (or legacy node key) → every durable capture.

    ``nodekey`` deliberately absorbs scrolling so a feed does not become an
    unbounded graph. Candidates still need to be unioned across those captures,
    otherwise controls revealed by a swipe disappear from resume.
    """
    out: OrderedDict[str, list[dict]] = OrderedDict()
    for e in events:
        key = screen_identity(e)
        if e.get("type") == "screen" and key:
            out.setdefault(key, []).append(e)
    return out


def taps(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tap"]


def changed(tap: dict) -> bool:
    """Accept the JSON strings emitted by the shell driver and bool fixtures."""
    return str(tap.get("changed", "")).lower() == "true"


def capture_gaps(events: list[dict], rows: list[dict] | None = None) -> dict[str, list]:
    """Return missing artifacts that must keep coverage from becoming complete.

    A tap or swipe records a transition, not a durable destination screenshot/tree.
    The latter is needed by measurement and reproduction, so a changed action whose
    destination was never captured is an explicit gap instead of a silent
    success. Missing source trees are handled here too: without them the
    candidate list cannot be reconstructed for resume.
    """
    missing_destinations = []
    unresolved_destinations = []
    for index, action in enumerate(events):
        if action.get("type") not in ("tap", "swipe"):
            continue
        if not changed(action):
            continue
        destination = action_destination(action)
        unresolved = destination in ("", "?")
        # The durable capture must postdate the tap — an older capture of the
        # same nodekey must never satisfy a new transition (a re-transition to
        # an already-seen screen still needs fresh evidence). It need NOT sit
        # before the next tap, though: a gap has to be repairable by
        # re-visiting the destination and capturing it then, which lands later
        # in the log. Requiring "immediately after" made a once-missed capture
        # permanently incomplete. For an unresolved destination ("?"), any
        # durable capture after the tap is the arrival evidence.
        destination_captured = any(
            e.get("type") == "screen" and e.get("tree") and Path(e["tree"]).is_file()
            and (unresolved or screen_identity(e) == destination)
            for e in events[index + 1:])
        if not destination_captured:
            (unresolved_destinations if unresolved else missing_destinations).append(action)
    missing_trees = [r for r in (rows or frontier(events)) if r.get("tree_missing")]
    return {
        "missing_trees": missing_trees,
        "missing_destinations": missing_destinations,
        "unresolved_destinations": unresolved_destinations,
    }


def candidate_records_of(tree: str) -> list[dict]:
    """Candidates plus behavior/category metadata emitted by device_a11y."""
    if not Path(tree).exists():
        return []
    proc = subprocess.run([sys.executable, str(HERE / "device_a11y.py"), "candidates", tree],
                          capture_output=True, text=True)
    found = []
    for line in proc.stdout.splitlines():
        if line.startswith("INFO: tap "):
            parts = line[len("INFO: tap "):].split(" | ", 2)
            xy = parts[0].split()
            found.append({"x": int(xy[0]), "y": int(xy[1]), "role": parts[1],
                          "label": parts[2], "withheld": False})
        elif line.startswith("WARN: withheld "):
            parts = line[len("WARN: withheld "):].split(" | ", 2)
            xy = parts[0].split()
            label = parts[2].rsplit(" — ", 1)[0]
            found.append({"x": int(xy[0]), "y": int(xy[1]), "role": parts[1],
                          "label": label, "withheld": True})
        elif line.startswith("INFO: candidate-meta "):
            parts = line[len("INFO: candidate-meta "):].split(" | ")
            xy = tuple(map(int, parts[0].split()))
            metadata = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
            record = next((item for item in reversed(found)
                           if (item["x"], item["y"]) == xy and "behavior" not in item), None)
            if record is not None:
                record.update(metadata)
                record["withheld"] = metadata.get("withheld", "false") == "true"
                record["state_changing"] = metadata.get("state_changing", "false") == "true"
    for record in found:
        if "behavior" not in record:
            source = f"{record['role']}|{record['label']}"
            record["behavior"] = hashlib.sha1(source.encode()).hexdigest()[:12]
        record.setdefault("category", "state-changing" if record["withheld"] else "navigation")
        record.setdefault("effect", "unknown" if record["withheld"] else "none")
        record.setdefault("state_changing", record["withheld"])
    return found


def candidates_of(tree: str) -> list[tuple[int, int, str]]:
    """Legacy tuple view: only safe targets that the tap guard permits."""
    return [(record["x"], record["y"], record["label"])
            for record in candidate_records_of(tree) if not record["withheld"]]


def frontier(events: list[dict]) -> list[dict]:
    """Per state: raw target and normalized behavior-class coverage."""
    tapped: dict[str, list] = {}
    for t in taps(events):
        tapped.setdefault(action_source(t), []).append(
            (t.get("label", "?"), int(t["x"]), int(t["y"]), t.get("behavior")))
    out = []
    captures_by_node = screen_captures(events)
    for key, screen in screens(events).items():
        done = tapped.get(key, [])
        captures = captures_by_node.get(key, [screen])
        valid_captures = [
            capture for capture in captures
            if capture.get("tree") and Path(capture["tree"]).is_file()
        ]
        tree_missing = any(
            not capture.get("tree") or not Path(capture["tree"]).is_file()
            for capture in captures
        )
        if not valid_captures:
            out.append({"key": key, "node": screen["node"],
                        "statekey": screen.get("statekey", ""),
                        "name": screen.get("name", key),
                        "tree": screen.get("tree", ""), "png": screen.get("png", ""),
                        "total": 0, "raw_todo": [], "behavior_total": 0,
                        "todo": [], "todo_groups": [], "withheld": 0,
                        "tree_missing": True})
            continue
        # Matched with tolerance, not equality: the same screen captured twice
        # reports the back button at (38,72) and (38,71). On exact coordinates
        # that target stays "unexplored" forever — coverage under-reports and
        # `next` keeps proposing work already done. Same 12pt bucket the tap
        # candidate list already uses to collapse duplicates.
        def is_done(candidate, done=done):
            return any((lab == candidate["label"] or "?" in (lab, candidate["label"]))
                       and abs(x - candidate["x"]) <= 12 and abs(y - candidate["y"]) <= 12
                       for lab, x, y, _behavior in done)
        # A feed/list may have the same nodekey before and after a swipe. Keep
        # the union of candidates, along with the capture that produced each
        # one, so resume can re-capture and tap the right visible variant.
        candidates_with_tree = []
        withheld_with_tree = []
        for capture in valid_captures:
            tree = capture["tree"]
            for candidate in candidate_records_of(tree):
                collection = withheld_with_tree if candidate["withheld"] else candidates_with_tree
                if not any(
                    (previous[0]["label"] == candidate["label"]
                     or "?" in (previous[0]["label"], candidate["label"]))
                    and abs(previous[0]["x"] - candidate["x"]) <= 12
                    and abs(previous[0]["y"] - candidate["y"]) <= 12
                    for previous in collection
                ):
                    collection.append((candidate, tree))
        candidates = [candidate for candidate, _tree in candidates_with_tree]
        raw_todo_records = [candidate for candidate in candidates if not is_done(candidate)]
        done_behaviors = {str(behavior) for _lab, _x, _y, behavior in done if behavior}
        legacy_done = [item for item in done if not item[3]]
        done_behaviors.update(
            candidate["behavior"] for candidate in candidates
            if any((lab == candidate["label"] or "?" in (lab, candidate["label"]))
                   and abs(x - candidate["x"]) <= 12 and abs(y - candidate["y"]) <= 12
                   for lab, x, y, _behavior in legacy_done)
        )
        behavior_representatives: OrderedDict[str, tuple[dict, str]] = OrderedDict()
        for candidate, tree in candidates_with_tree:
            behavior_representatives.setdefault(candidate["behavior"], (candidate, tree))
        todo_with_tree = [item for behavior, item in behavior_representatives.items()
                          if behavior not in done_behaviors]
        todo = [(candidate["x"], candidate["y"], candidate["label"])
                for candidate, _tree in todo_with_tree]
        todo_groups = []
        for candidate, tree in todo_with_tree:
            if not todo_groups or todo_groups[-1][0] != tree:
                todo_groups.append((tree, []))
            todo_groups[-1][1].append((candidate["x"], candidate["y"], candidate["label"]))
        out.append({"key": key, "node": screen["node"],
                    "statekey": screen.get("statekey", ""),
                    "name": screen.get("name", key),
                    "tree": screen.get("tree", ""), "png": screen.get("png", ""),
                    "total": len(candidates),
                    "raw_todo": [(candidate["x"], candidate["y"], candidate["label"])
                                 for candidate in raw_todo_records],
                    "behavior_total": len(behavior_representatives), "todo": todo,
                    "todo_groups": todo_groups, "tree_missing": tree_missing})
        out[-1]["withheld"] = len(withheld_with_tree)
    return out


def unexplored(records: list[dict], events: list[dict], state: str) -> list[dict]:
    """Safe candidates of one capture whose behavior class was never tapped here.

    ``records`` come from the live tree, so every coordinate returned is one the
    tap guard accepts. Coordinates are matched with the same 12pt tolerance the
    candidate list uses, because the same control is reported at (38,72) and
    (38,71) across two captures of one screen.
    """
    done = [(t.get("label", "?"), int(t["x"]), int(t["y"]), t.get("behavior"))
            for t in taps(events) if action_source(t) == state]
    done_behaviors = {str(behavior) for _lab, _x, _y, behavior in done if behavior}
    emitted: set[str] = set()
    out = []
    for record in records:
        if record["withheld"]:
            continue
        behavior = record["behavior"]
        if behavior in done_behaviors or behavior in emitted:
            continue
        if any((lab == record["label"] or "?" in (lab, record["label"]))
               and abs(x - record["x"]) <= 12 and abs(y - record["y"]) <= 12
               for lab, x, y, _behavior in done):
            continue
        emitted.add(behavior)
        out.append(record)
    return out


def observed_edges(events: list[dict]) -> "OrderedDict[str, list[tuple[str, str]]]":
    """from state key → [(behavior, to state key)] for transitions that changed."""
    edges: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict()
    for tap in taps(events):
        if not changed(tap):
            continue
        source, destination = action_source(tap), action_destination(tap)
        behavior = str(tap.get("behavior") or "")
        if not source or not behavior or destination in ("", "?") or source == destination:
            continue
        bucket = edges.setdefault(source, [])
        if (behavior, destination) not in bucket:
            bucket.append((behavior, destination))
    return edges


def routes(edges, start: str, targets: set[str]) -> list[tuple[str, str, int]]:
    """Shortest observed routes from ``start`` to each target: (target, first behavior, hops)."""
    found: list[tuple[str, str, int]] = []
    seen = {start}
    queue = deque()
    for behavior, destination in edges.get(start, []):
        if destination not in seen:
            seen.add(destination)
            queue.append((destination, behavior, 1))
    while queue:
        node, first_behavior, hops = queue.popleft()
        if node in targets:
            found.append((node, first_behavior, hops))
        for behavior, destination in edges.get(node, []):
            if destination not in seen:
                seen.add(destination)
                queue.append((destination, first_behavior, hops + 1))
    return found


def cmd_next_tap(path: str, tree: str) -> int:
    """The one tap to make next from the screen currently on the device.

    Prints at most one `INFO: next-tap x y | label` plus an `INFO: kind ...`
    line saying whether it drains this screen (`frontier`) or walks toward
    another one (`route`). No tap line means there is nothing to do from here —
    the reason is on the OK/WARN line, and the exit code stays 0 so the caller
    distinguishes "done" from "broken".
    """
    if not Path(tree).is_file():
        print(f"ERROR: no such tree '{tree}'", file=sys.stderr)
        return 1
    state = _statekey_of(tree)
    if not state:
        print(f"ERROR: could not derive a state key from '{tree}'", file=sys.stderr)
        return 1
    events = load(path)
    records = candidate_records_of(tree)
    todo = unexplored(records, events, state)
    if todo:
        record = todo[0]
        print(f"INFO: next-tap {record['x']} {record['y']} | {record['label']}")
        print("INFO: kind frontier")
        print(f"OK: {len(todo)} unexplored safe candidate(s) on this screen")
        return 0
    # frontier() re-reads every capture through device_a11y, so a routing hop
    # costs one full coverage pass. Bounded (CLONE_EXPLORE_MAX_ROUTE hops per
    # navigation) and small next to a tap plus settle on a real phone. If it
    # ever dominates, pass the target back in as a hint so hops after the first
    # only re-plan over the log's edges.
    rows = frontier(events)
    pending = {row["key"] for row in rows if row["todo"] and row["key"] != state}
    if not pending:
        # frontier() unions candidates across every capture of one state, so a
        # feed can hold targets that only a different scroll position shows.
        # This capture being drained is NOT the same claim as the run being
        # done, and saying "explored everything" here would be the exact
        # false completeness SKILL rule 6 forbids.
        here = next((row for row in rows if row["key"] == state and row["todo"]), None)
        if here:
            print(f"WARN: {len(here['todo'])} candidate(s) of this screen were seen in another "
                  "capture of it (a different scroll position) and are not on this one — "
                  "scroll and re-capture to reach them")
            print("OK: nothing left to tap on this capture")
            return 0
        print("OK: frontier empty — every safe behavior class was explored")
        return 0
    # Route hops are edges already tapped from here, so they are live candidates
    # of this tree; look them up by behavior to get today's coordinates.
    by_behavior = {record["behavior"]: record for record in records if not record["withheld"]}
    for target, first_behavior, hops in routes(observed_edges(events), state, pending):
        record = by_behavior.get(first_behavior)
        if record is None:
            continue
        print(f"INFO: next-tap {record['x']} {record['y']} | {record['label']}")
        print(f"INFO: kind route hops={hops} target={target}")
        print(f"OK: routing toward {target} ({len(pending)} screen(s) still unexplored)")
        return 0
    print(f"WARN: {len(pending)} screen(s) still have unexplored candidates, but no observed "
          "transition leads there from this screen — navigate manually (device_flow.py next)")
    print("OK: no reachable next tap from this screen")
    return 0


def cmd_next(path: str) -> int:
    events = load(path)
    rows = frontier(events)
    pending = [r for r in rows if r["todo"]]
    gaps = capture_gaps(events, rows)
    if not pending:
        if gaps["missing_trees"] or gaps["missing_destinations"] or gaps["unresolved_destinations"]:
            _print_capture_gaps(gaps)
            print("WARN: frontier is empty, but durable screen evidence is incomplete; "
                  "do not call the clone explored yet")
            return 1
        raw_left = sum(len(r["raw_todo"]) for r in rows)
        suffix = f"; {raw_left} repeated raw target(s) unvisited" if raw_left else ""
        print("OK: frontier empty — every safe behavior class was explored" + suffix)
        return 0
    # Shallowest first, by the same depths the map draws: breadth-first keeps the
    # upper levels complete when the run is cut short, which it usually is.
    depth = _depths([r["key"] for r in rows], _edges(events))
    pending.sort(key=lambda r: depth.get(r["key"], 0))
    for r in pending:
        print(f"INFO: screen {r['name']} ({r['key']}) — "
              f"{len(r['todo'])}/{r['behavior_total']} behavior classes unexplored; "
              f"{len(r['raw_todo'])}/{r['total']} raw targets unexplored")
        groups = r.get("todo_groups") or [(r["tree"], r["todo"])]
        for tree, candidates in groups:
            for x, y, label in candidates:
                print(f"INFO:   tap {x} {y} | {label}")
            print(f"INFO:   tree {tree}")
    total_todo = sum(len(r["todo"]) for r in pending)
    raw_todo = sum(len(r["raw_todo"]) for r in rows)
    _print_capture_gaps(gaps)
    print(f"OK: {total_todo} unexplored behavior classes ({raw_todo} raw targets) "
          f"across {len(pending)} screens — "
          "re-foreground the app, re-capture that screen, then tap from ITS fresh candidates")
    return 0


def _statekey_of(tree: str) -> str:
    proc = subprocess.run([sys.executable, str(HERE / "device_a11y.py"), "statekey", tree],
                          capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("INFO: statekey "):
            return line[len("INFO: statekey "):].strip()
    return ""


def cmd_todo(path: str, tree: str) -> int:
    """Unexplored safe candidates of one capture, one `INFO: todo x y | label` per line.

    Behavior-class filtered like `frontier` (repeated rows collapse to one
    representative), but every printed coordinate comes from the given tree, so
    a caller can pass it straight to the tap guard.
    """
    if not Path(tree).is_file():
        print(f"ERROR: no such tree '{tree}'", file=sys.stderr)
        return 1
    state = _statekey_of(tree)
    if not state:
        print(f"ERROR: could not derive a state key from '{tree}'", file=sys.stderr)
        return 1
    events = load(path)
    todo = unexplored(candidate_records_of(tree), events, state)
    for record in todo:
        print(f"INFO: todo {record['x']} {record['y']} | {record['label']}")
    print(f"OK: {len(todo)} unexplored safe candidate(s) on this capture")
    return 0


def _print_capture_gaps(gaps: dict[str, list]) -> None:
    if gaps["missing_trees"]:
        print(f"WARN: {len(gaps['missing_trees'])} captured screen(s) have no accessibility tree — "
              "re-run device_wda.sh screen before claiming coverage")
    if gaps["missing_destinations"]:
        nodes = sorted({action_destination(t) for t in gaps["missing_destinations"]})
        print(f"WARN: {len(gaps['missing_destinations'])} changed action(s) have no destination capture "
              f"({', '.join(nodes)}) — run device_wda.sh screen after each changed tap/swipe, "
              "or re-visit those screens now and capture them")
    if gaps["unresolved_destinations"]:
        print(f"WARN: {len(gaps['unresolved_destinations'])} changed transition(s) have no resolvable destination "
              "— re-capture the destination screen and inspect the WDA session")


def cmd_stats(path: str) -> int:
    events = load(path)
    rows = frontier(events)
    total = sum(r["total"] for r in rows)
    raw_todo = sum(len(r["raw_todo"]) for r in rows)
    behavior_total = sum(r["behavior_total"] for r in rows)
    behavior_todo = sum(len(r["todo"]) for r in rows)
    withheld = sum(r["withheld"] for r in rows)
    dead = [t for t in taps(events) if not changed(t)]
    gaps = capture_gaps(events, rows)
    print(f"INFO: screens {len(rows)}")
    print(f"INFO: targets {total - raw_todo}/{total} explored, {raw_todo} left")
    print(f"INFO: behavior classes {behavior_total - behavior_todo}/{behavior_total} explored, "
          f"{behavior_todo} left")
    if withheld:
        print(f"INFO: withheld state-changing {withheld} (not safe pending work)")
    if dead:
        print(f"INFO: no-op taps {len(dead)} (target changed nothing)")
    _print_capture_gaps(gaps)
    incomplete = any(gaps.values())
    if behavior_todo:
        status = f"partial ({behavior_todo} behavior classes unexplored)"
        if incomplete:
            status += "; evidence incomplete"
    elif incomplete:
        status = "incomplete (screen evidence missing)"
    else:
        status = (f"complete (behavior classes; {raw_todo} repeated raw targets unvisited)"
                  if raw_todo else "complete")
    print("OK: coverage " + status)
    return 0


def _edges(events: list[dict]) -> list[tuple[str, str, str]]:
    seen, out = set(), []
    for t in taps(events):
        edge = (action_source(t) or "?", action_destination(t), t.get("label", "?"))
        if edge not in seen and changed(t):
            seen.add(edge)
            out.append(edge)
    return out


def _depths(nodes: list[str], edges: list[tuple[str, str, str]]) -> dict[str, int]:
    """Distance from the first captured screen — the map's rows."""
    if not nodes:
        return {}
    depth = {nodes[0]: 0}
    changed = True
    while changed:
        changed = False
        for src, dst, _ in edges:
            if src in depth and (dst not in depth or depth[dst] > depth[src] + 1) and dst != src:
                depth[dst] = depth[src] + 1
                changed = True
    for n in nodes:                       # captured but never reached by a tap
        depth.setdefault(n, 0)
    return depth


# Node geometry. Fixed sizes so the SVG edges can be laid out server-side —
# there is no layout engine here and no CDN to borrow one from.
NODE_W, NODE_H = 200, 268
TODO_W, TODO_H = 148, 62
GAP_X, GAP_S, ROW_GAP, PAD = 28, 10, 64, 32
TODO_COLS = 4          # a screen with 20 untapped targets must not be 20 nodes wide


def _layout(scr: dict, rows: dict, edges: list, depth: dict, out_dir: Path) -> tuple[list, list, list]:
    """Place every node on a grid and resolve the edges into coordinates.

    Unexplored candidates become real nodes — empty ones, hanging off the screen
    that offers them. A target nobody tapped is exactly a screen nobody has seen,
    and drawing it as a blank card says that better than a count does.

    A screen's unexplored children are wrapped into a block instead of one long
    row: laid out flat, 51 of them made the canvas 9000px wide and unreadable.
    """
    placed: dict[str, dict] = {}
    screens_at: dict[int, list] = {}
    todos_at: dict[int, list] = {}

    for node in scr:
        screens_at.setdefault(depth.get(node, 0), []).append(node)
        kids = rows.get(node, {}).get("todo", [])
        if kids:
            todos_at.setdefault(depth.get(node, 0) + 1, []).append((node, kids))

    def put(key, kind, x, y, w, h, label, parent=None):
        placed[key] = {"kind": kind, "x": x, "y": y, "w": w, "h": h,
                       "label": label, "parent": parent, "node": key}

    lanes = []
    y = PAD
    for level in sorted(set(screens_at) | set(todos_at)):
        lanes.append((level, y))
        x, row_h = PAD, 0
        for node in screens_at.get(level, []):
            put(node, "screen", x, y, NODE_W, NODE_H, scr[node].get("name", node))
            x += NODE_W + GAP_X
            row_h = max(row_h, NODE_H)
        for parent, kids in todos_at.get(level, []):
            cols = min(TODO_COLS, len(kids))
            for i, (_tx, _ty, label) in enumerate(kids):
                put(f"{parent}#{i}", "todo",
                    x + (i % cols) * (TODO_W + GAP_S),
                    y + (i // cols) * (TODO_H + GAP_S),
                    TODO_W, TODO_H, label, parent)
            x += cols * (TODO_W + GAP_S) + GAP_X
            row_h = max(row_h, -(-len(kids) // cols) * (TODO_H + GAP_S))
        y += row_h + ROW_GAP

    for key, box in placed.items():
        if box["kind"] == "screen":
            png = scr[key].get("png", "")
            box["png"] = (os.path.relpath(Path(png).resolve(), out_dir)
                          if png and Path(png).exists() else "")
            box["todo_count"] = len(rows.get(key, {}).get("todo", []))
            box["total"] = rows.get(key, {}).get("behavior_total", 0)

    links = [(src, dst, label) for src, dst, label in edges if src in placed and dst in placed]
    links += [(box["parent"], key, box["label"]) for key, box in placed.items()
              if box["kind"] == "todo" and box["parent"] in placed]
    return (list(placed.values()), [(placed[a], placed[b], lab) for a, b, lab in links], lanes)


def _svg_edges(links: list) -> str:
    """One cubic curve per transition, from the parent's bottom to the child's top."""
    out = []
    for src, dst, label in links:
        x1, y1 = src["x"] + src["w"] / 2, src["y"] + src["h"]
        x2, y2 = dst["x"] + dst["w"] / 2, dst["y"]
        mid = (y1 + y2) / 2
        cls = "edge todo" if dst["kind"] == "todo" else "edge"
        out.append(f'<path class="{cls}" d="M{x1},{y1} C{x1},{mid} {x2},{mid} {x2},{y2}"/>')
        # Backwards edges (a back button) would otherwise be indistinguishable.
        if y2 <= y1:
            out.append(f'<circle class="back" cx="{x2}" cy="{y2}" r="4"/>')
        if dst["kind"] != "todo":
            lx, ly = (x1 + x2) / 2, mid
            out.append(f'<text class="elabel" x="{lx}" y="{ly}" text-anchor="middle">'
                       f'{html.escape(label)}</text>')
    return "".join(out)


def cmd_map(path: str, out: str) -> int:
    events = load(path)
    scr = screens(events)
    rows = {r["key"]: r for r in frontier(events)}
    edges = _edges(events)
    depth = _depths(list(scr), edges)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    boxes, links, lanes = _layout(scr, rows, edges, depth, out_path.resolve().parent)
    width = max((b["x"] + b["w"] for b in boxes), default=400) + PAD
    height = max((b["y"] + b["h"] for b in boxes), default=200) + PAD

    def esc(s: object) -> str:
        return html.escape(str(s))

    # The vertical axis is how far a screen sits from where THIS run started —
    # not the app's own hierarchy. Exploration began mid-app here (an empty list
    # reached from the home screen), so an unlabelled top-to-bottom layout would
    # assert a structure the log never measured, and contradict the reverse brief.
    cards = [f'<div class="lane" style="top:{y}px">탐험 거리 {lvl}</div>'
             for lvl, y in lanes]
    for b in boxes:
        style = f'left:{b["x"]}px; top:{b["y"]}px; width:{b["w"]}px; height:{b["h"]}px'
        if b["kind"] == "todo":
            cards.append(f'<div class="node todo" style="{style}" title="미탐험">'
                         f'<span>{esc(b["label"])}</span></div>')
            continue
        shot = (f'<img src="{esc(b["png"])}" alt="">' if b["png"]
                else '<div class="noshot">캡처 없음</div>')
        badge = (f'<span class="badge">미탐험 {b["todo_count"]}/{b["total"]}</span>'
                 if b["todo_count"] else '<span class="badge done">전수</span>')
        cards.append(
            f'<div class="node screen" style="{style}"><div class="shot">{shot}</div>'
            f'<div class="meta"><strong>{esc(b["label"])}</strong>{badge}</div></div>')

    raw_total = sum(r["total"] for r in rows.values())
    raw_left = sum(len(r["raw_todo"]) for r in rows.values())
    behavior_total = sum(r["behavior_total"] for r in rows.values())
    behavior_left = sum(len(r["todo"]) for r in rows.values())
    withheld = sum(r["withheld"] for r in rows.values())
    banner = (f'화면 {len(scr)}개 · 탭 후보 {raw_total - raw_left}/{raw_total} 탐험'
              f' · 행동 클래스 {behavior_total - behavior_left}/{behavior_total} 탐험'
              + (f' · <strong>미탐험 {behavior_left}</strong> (점선 노드)'
                 if behavior_left else ' · 행동 클래스 완료')
              + (f' · 상태 변경 보류 {withheld}' if withheld else ''))

    out_path.write_text(f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clone flow map</title>
<style>
  :root {{ --bg:#0b0b0c; --card:#151517; --border:#2a2a2e; --text:#ececf0; --muted:#8e8e96;
          --accent:#6d7cfe; --warn:#e5484d; }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg:#f7f7f8; --card:#fff; --border:#d9d9de; --text:#18181b; --muted:#6b6b73; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px; background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .banner {{ color:var(--muted); margin:0 0 20px; font-size:14px; }}
  .banner strong {{ color:var(--warn); }}
  .canvas {{ position:relative; overflow:auto; border:1px solid var(--border);
             border-radius:14px; background:var(--bg); }}
  .stage {{ position:relative; width:{width}px; height:{height}px; }}
  svg {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
  .edge {{ fill:none; stroke:var(--accent); stroke-width:2; }}
  .edge.todo {{ stroke:var(--muted); stroke-dasharray:4 4; stroke-width:1.5; }}
  .back {{ fill:var(--accent); }}
  .elabel {{ fill:var(--muted); font-size:11px; paint-order:stroke;
             stroke:var(--bg); stroke-width:4px; }}
  .node {{ position:absolute; border-radius:12px; background:var(--card);
           border:1px solid var(--border); overflow:hidden; }}
  .node.screen {{ display:flex; flex-direction:column; }}
  .shot {{ flex:1; min-height:0; display:grid; place-items:center; background:#000; }}
  .shot img {{ width:100%; height:100%; object-fit:contain; display:block; }}
  .noshot {{ color:var(--muted); font-size:12px; }}
  .meta {{ padding:8px 10px; display:flex; align-items:center; justify-content:space-between;
           gap:8px; border-top:1px solid var(--border); }}
  .meta strong {{ font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .badge {{ font-size:11px; color:var(--warn); white-space:nowrap; }}
  .badge.done {{ color:var(--muted); }}
  .node.todo {{ border-style:dashed; background:transparent; display:grid; place-items:center;
                padding:6px 8px; text-align:center; }}
  .node.todo span {{ font-size:12px; color:var(--muted); overflow:hidden;
                     display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; }}
  .legend {{ margin-top:12px; font-size:13px; color:var(--muted); display:flex; gap:20px;
             flex-wrap:wrap; }}
  .legend i {{ display:inline-block; width:22px; height:0; border-top:2px solid var(--accent);
               vertical-align:middle; margin-right:6px; }}
  .legend i.dash {{ border-top:1.5px dashed var(--muted); }}
  .lane {{ position:absolute; left:0; width:{PAD}px; font-size:10px; color:var(--muted);
           writing-mode:vertical-rl; text-orientation:mixed; letter-spacing:.04em; }}
</style></head>
<body>
  <h1>Clone flow map</h1>
  <p class="banner">{banner}</p>
  <div class="canvas"><div class="stage">
    <svg viewBox="0 0 {width} {height}">{_svg_edges(links)}</svg>
    {"".join(cards)}
  </div></div>
  <p class="legend">
    <span><i></i>탐험한 전이 (라벨 = 탭한 요소)</span>
    <span><i class="dash"></i>미탐험 — 이 요소를 탭하면 나올 화면</span>
    <span>● 도착점이 위쪽이면 되돌아가는 전이</span>
    <span>세로축 = <strong>탐험 시작 화면으로부터의 거리</strong>이지 앱의 계층이 아니다</span>
  </p>
</body></html>
""", encoding="utf-8")
    todo_nodes = sum(1 for b in boxes if b["kind"] == "todo")
    print(f"OK: wrote {out_path} ({len(scr)} screens, {len(edges)} transitions, "
          f"{todo_nodes} unexplored)")
    return 0


def cmd_audit(path: str) -> int:
    """Did this run tap anything the guard should have withheld?

    The guard lives in `device_a11y`, and a hole in it is invisible at the time —
    the tap just succeeds. Measured 2026-08-22: exploration liked and shared
    another person's posts on the user's real Threads account for two runs
    before a hand-written log audit caught it, because every pattern was anchored
    at the end of the label and real labels are `좋아요. 226명이 …`.

    So re-judge what was actually tapped, with today's classifier. This turns a
    one-off investigation into a check every run makes about itself, and it flags
    logs recorded before a guard fix as well as a future regression.
    """
    import device_a11y

    def effect_of(label: str) -> str | None:
        if device_a11y.DESTRUCTIVE.search(label):
            return "destructive"
        clauses = device_a11y._label_clauses(label)
        for effect, pattern in device_a11y.STATE_CHANGING:
            if any(pattern.search(clause) for clause in clauses):
                return effect
        return None

    events = load(path)
    offenders = []
    for action in events:
        if action.get("type") not in ("tap", "swipe"):
            continue
        label = str(action.get("label") or "").strip()
        if not label or label == "?":
            continue
        effect = effect_of(label)
        if effect:
            offenders.append((effect, label, action.get("at", "?")))
    total = sum(1 for a in events if a.get("type") in ("tap", "swipe"))
    if not offenders:
        print(f"OK: none of the {total} recorded action(s) would be withheld today")
        return 0
    for effect, label, at in offenders:
        print(f"ERROR: tapped a {effect} target at {at} | {label}", file=sys.stderr)
    print(f"ERROR: {len(offenders)} of {total} recorded action(s) mutate state — the guard "
          "let them through. Fix device_a11y before exploring again, and tell the user what "
          "was changed on their account.", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        if mode in ("next", "stats", "audit") and len(argv) == 3:
            return {"next": cmd_next, "stats": cmd_stats, "audit": cmd_audit}[mode](argv[2])
        if mode == "map" and len(argv) == 4:
            return cmd_map(argv[2], argv[3])
        if mode == "todo" and len(argv) == 4:
            return cmd_todo(argv[2], argv[3])
        if mode == "next-tap" and len(argv) == 4:
            return cmd_next_tap(argv[2], argv[3])
    except FileNotFoundError:
        print(f"ERROR: no exploration log at {argv[2]} — capture a screen first "
              "(`device_wda.sh screen` writes it)", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: corrupt exploration log {argv[2]}: {exc}", file=sys.stderr)
        return 1
    except FlowContractError as exc:
        print(f"ERROR: invalid exploration log {argv[2]}: {exc}", file=sys.stderr)
        return 1
    print("ERROR: usage: device_flow.py next|stats|audit <flow.jsonl> "
          "| map <flow.jsonl> <out.html> | todo|next-tap <flow.jsonl> <tree.xml>",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
