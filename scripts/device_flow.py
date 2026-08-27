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
import xml.etree.ElementTree as ET
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


def _edges(events: list[dict]) -> list[tuple[str, str, str, float, float]]:
    """Transitions, each carrying the point that was actually tapped.

    The coordinate is what lets the map draw the edge from the spot on the
    screenshot instead of from the bottom of the card: "tapping HERE goes there"
    is the thing a flow map is for, and a line leaving the card's edge does not
    say it.
    """
    seen, out = set(), []
    for t in taps(events):
        edge = (action_source(t) or "?", action_destination(t), t.get("label", "?"))
        if edge not in seen and changed(t):
            seen.add(edge)
            try:
                x, y = float(t.get("x", -1)), float(t.get("y", -1))
            except (TypeError, ValueError):
                x = y = -1.0
            out.append((*edge, x, y))
    return out


def _depths(nodes: list[str], edges: list[tuple]) -> dict[str, int]:
    """Distance from an entry screen — the map's rows.

    Seeded from every screen nothing leads INTO, not just the first capture.
    Seeding only the first put all 25 screens on one row: exploration began on
    an unscrolled home feed which was never returned to, so the seed had no
    outgoing edge and the relaxation never started.
    """
    if not nodes:
        return {}
    incoming = {n: 0 for n in nodes}
    for src, dst, *_rest in edges:
        if dst in incoming and dst != src:
            incoming[dst] += 1
    roots = [n for n in nodes if not incoming.get(n)] or [nodes[0]]
    depth = {n: 0 for n in roots}
    changed = True
    while changed:
        changed = False
        for src, dst, *_rest in edges:
            if src in depth and (dst not in depth or depth[dst] > depth[src] + 1) and dst != src:
                depth[dst] = depth[src] + 1
                changed = True
    for n in nodes:                       # captured but never reached by a tap
        depth.setdefault(n, 0)
    return depth


# Card geometry. The card is sized FROM the capture's own frame so the phone
# image fills it exactly — no letterbox, no crop, and a tap at (x, y) lands at
# (x/fw, y/fh) of the card with no correction term to get wrong. The first
# attempt fixed the card at 200x232 and relied on `object-fit: contain`; the
# render cropped the screenshots and every marker was placed against letterbox
# offsets that were not there.
SHOT_H, META_H = 300, 34
FALLBACK_W = 160          # a capture whose frame we cannot read
GAP_X, ROW_GAP, PAD = 34, 96, 40


def _frame_of(tree: str) -> tuple[float, float]:
    """The app's point-space frame — what tap coordinates are relative to."""
    try:
        for node in ET.parse(tree).getroot().iter():
            if (node.get("type") or node.tag).endswith("Application"):
                w, h = float(node.get("width") or 0), float(node.get("height") or 0)
                return (w, h) if w > 0 and h > 0 else (0.0, 0.0)
    except (OSError, ET.ParseError, ValueError):
        pass
    return (0.0, 0.0)


def map_key(event: dict) -> str:
    """A screen's identity ON THE MAP: its labels AND its interaction state.

    Neither half is enough. `statekey` alone merged the home feed, the creator
    tab, the ranking tab and the contest tab onto one card, because it hashes
    the tree's SHAPE and a custom-rendered app has none — measured on zeta,
    every screen reported the coarse node `da39a3ee5e6b`, which is sha1(""), so
    taps made on one screen were drawn on a screenshot of another. `sig` alone
    loses the states that share a label set, which is what separates a sheet
    that is open from the same screen with it closed. Together they split on
    either difference.
    """
    return f'{_first_value(event, "sig")}:{screen_identity(event)}'


def map_screens(events: list[dict]) -> "OrderedDict[str, dict]":
    """Screens for the MAP, identified by their label set rather than structure.

    `nodekey`/`statekey` hash the tree's SHAPE, and a custom-rendered app has no
    shape to hash: measured on zeta, every screen reported the same coarse node
    `da39a3ee5e6b`, which is sha1(""). The home feed, the creator tab, the
    ranking tab and the contest tab all collapsed onto one card, so taps made on
    one screen were drawn on a screenshot of another. `sig` hashes the labels,
    which is exactly what differs between those screens.

    The cost is the opposite error: a feed re-sigs as it scrolls, so one screen
    can become several cards. For a map that is the safe direction — a duplicate
    card is visibly a duplicate, while a merged card silently lies about where a
    tap was.
    """
    out: "OrderedDict[str, dict]" = OrderedDict()
    for e in events:
        if e.get("type") != "screen":
            continue
        key = map_key(e)
        if key and key not in out:
            out[key] = e
    return out


def map_edges(events: list[dict]) -> list[tuple[str, str, str, float, float]]:
    """Transitions between MAP screens, resolved chronologically.

    A tap records statekeys, which are the identities that collapse. The log is
    ordered, though, so the screen a tap left is the last one captured before it
    and the screen it reached is the next one captured after — that ordering is
    real information the statekey abstraction throws away.
    """
    out, seen = [], set()
    for index, event in enumerate(events):
        if event.get("type") != "tap" or not changed(event):
            continue
        before = next((map_key(e) for e in reversed(events[:index])
                       if e.get("type") == "screen"), "")
        after = next((map_key(e) for e in events[index + 1:]
                      if e.get("type") == "screen"), "")
        if not before or not after or before == after:
            continue
        label = event.get("label", "?")
        try:
            x, y = float(event.get("x", -1)), float(event.get("y", -1))
        except (TypeError, ValueError):
            x = y = -1.0
        key = (before, after, label)
        if key in seen:
            continue
        seen.add(key)
        out.append((before, after, label, x, y))
    return out


def _layout(cards: "OrderedDict[str, dict]", todo: dict, edges: list, depth: dict,
            out_dir: Path) -> tuple[list, list, list]:
    """One row per exploration depth, each card sized to its own screenshot."""
    at: dict[int, list] = {}
    for key in cards:
        at.setdefault(depth.get(key, 0), []).append(key)

    boxes: dict[str, dict] = {}
    lanes, y = [], PAD
    for level in sorted(at):
        lanes.append((level, y))
        x, row_h = PAD, 0
        for key in at[level]:
            event = cards[key]
            fw, fh = _frame_of(event.get("tree", ""))
            w = round(SHOT_H * fw / fh) if fw and fh else FALLBACK_W
            png = event.get("png", "")
            boxes[key] = {
                "kind": "screen", "node": key, "x": x, "y": y,
                "w": w, "h": SHOT_H + META_H, "shot_w": w, "shot_h": SHOT_H,
                "frame": (fw, fh), "label": event.get("name", key),
                "png": (os.path.relpath(Path(png).resolve(), out_dir)
                        if png and Path(png).exists() else ""),
                "todo": todo.get(key, {}).get("points", []),
                "todo_count": todo.get(key, {}).get("left", 0),
                "total": todo.get(key, {}).get("total", 0),
            }
            x += w + GAP_X
            row_h = max(row_h, SHOT_H + META_H)
        y += row_h + ROW_GAP

    def spot(key: str, px: float, py: float):
        box = boxes.get(key)
        if not box or px < 0 or py < 0:
            return None
        fw, fh = box["frame"]
        if not fw or not fh:
            return None
        return (box["x"] + px / fw * box["shot_w"], box["y"] + py / fh * box["shot_h"])

    links = [(boxes[a], boxes[b], lab, spot(a, x, y))
             for a, b, lab, x, y in edges if a in boxes and b in boxes]
    return list(boxes.values()), links, lanes


def _svg_edges(links: list, boxes: list) -> tuple[str, str]:
    """What goes behind the cards, and what goes on top of them.

    Two layers, because one does not work: a card is opaque and painted after
    the SVG, so a marker drawn at the tap coordinate in a single layer is buried
    under the screenshot — geometrically perfect and completely invisible.
    Connector curves belong behind (in front they scribble across every
    screenshot they cross); the tap marker and the short leader tying it to the
    card's edge belong on top, the only place "you tapped HERE" can be read.
    """
    below, above = [], []
    for src, dst, label, origin in links:
        bottom = src["y"] + src["h"]
        x1 = origin[0] if origin else src["x"] + src["w"] / 2
        x2, y2 = dst["x"] + dst["w"] / 2, dst["y"]
        mid = (bottom + y2) / 2
        below.append(f'<path class="edge" d="M{x1},{bottom} C{x1},{mid} {x2},{mid} {x2},{y2}"/>')
        if y2 <= bottom:                       # a back edge, pointing upwards
            below.append(f'<circle class="back" cx="{x2}" cy="{y2}" r="3.5"/>')
        if origin:
            tx, ty = origin
            above.append(f'<path class="leader" d="M{tx},{ty} L{x1},{bottom}"/>')
            above.append(f'<circle class="tap" cx="{tx}" cy="{ty}" r="5"/>')
            above.append(f'<circle class="tapdot" cx="{tx}" cy="{ty}" r="1.6"/>')
        lx, ly = (x1 + x2) / 2, mid
        below.append(f'<text class="elabel" x="{lx}" y="{ly}" text-anchor="middle">'
                     f'{html.escape(label)}</text>')

    # Unexplored candidates are dots on the screenshot, not cards of their own.
    # Drawn as 196 separate nodes they buried the map in dashed lines and said
    # only how many there were; on the screenshot they say WHERE.
    for box in boxes:
        fw, fh = box["frame"]
        if not fw or not fh:
            continue
        for px, py, label in box["todo"]:
            if px < 0 or py < 0:
                continue
            cx = box["x"] + px / fw * box["shot_w"]
            cy = box["y"] + py / fh * box["shot_h"]
            above.append(f'<circle class="gap" cx="{cx}" cy="{cy}" r="4">'
                         f'<title>{html.escape(label)}</title></circle>')
    return "".join(below), "".join(above)


def cmd_map(path: str, out: str) -> int:
    events = load(path)
    rows = {r["key"]: r for r in frontier(events)}
    cards_by_sig = map_screens(events)
    edges = map_edges(events)
    depth = _depths(list(cards_by_sig), edges)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # The frontier is keyed by statekey, which is exactly the identity the map
    # refuses to trust; re-attach it through each card's own capture.
    todo = {}
    for sig, event in cards_by_sig.items():
        tree = event.get("tree", "")
        state = screen_identity(event)
        # From THIS capture's own candidates. The statekey row unions candidates
        # across every capture of that state, so a scrolled feed would show dots
        # for controls that are not on the screenshot under them.
        records = candidate_records_of(tree) if tree else []
        points = [(r["x"], r["y"], r["label"])
                  for r in unexplored(records, events, state)]
        # `unexplored` skips withheld records, so counting them in the
        # denominator made a screen with 0 taps read as partly explored — the
        # withheld ones silently landed on the "done" side. They are not
        # explored, they are refused; the banner reports them on their own.
        todo[sig] = {"points": points, "left": len(points),
                     "total": sum(1 for r in records if not r["withheld"]),
                     "withheld": sum(1 for r in records if r["withheld"])}

    boxes, links, lanes = _layout(cards_by_sig, todo, edges, depth,
                                  out_path.resolve().parent)
    edges_below, edges_above = _svg_edges(links, boxes)
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
        style = (f'left:{b["x"]}px; top:{b["y"]}px; width:{b["w"]}px; height:{b["h"]}px')
        shot = (f'<img src="{esc(b["png"])}" alt="" width="{b["shot_w"]}"'
                f' height="{b["shot_h"]}">' if b["png"]
                else f'<div class="noshot" style="height:{b["shot_h"]}px">캡처 없음</div>')
        badge = (f'<span class="badge">미탐 {b["todo_count"]}</span>'
                 if b["todo_count"] else '<span class="badge done">전수</span>')
        cards.append(
            f'<div class="node screen" style="{style}"><div class="shot">{shot}</div>'
            f'<div class="meta"><strong>{esc(b["label"])}</strong>{badge}</div></div>')

    # Every number here is counted off the cards the map actually drew. Mixing
    # a statekey-derived denominator with a card-derived numerator printed
    # "행동 클래스 -47/219" — the two identities do not share a scale.
    total = sum(v["total"] for v in todo.values())
    left = sum(len(v["points"]) for v in todo.values())
    withheld = sum(v["withheld"] for v in todo.values())
    banner = (f'화면 {len(cards_by_sig)}개 · 탭 지점 {total - left}/{total} 탐험'
              + (f' · <strong>미탐 {left}</strong> (화면 위 빈 점)'
                 if left else ' · 전수 탐험')
              + (f' · 상태 변경 보류 {withheld}' if withheld else '')
              + ' · 같은 화면이라도 스크롤 위치가 다르면 별도 카드')

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
  /* Two layers. A card is opaque and paints after the SVG, so a marker drawn at
     the tap coordinate in a single layer is buried under the screenshot. */
  svg {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
  svg.above {{ z-index:3; }}
  .leader {{ fill:none; stroke:var(--accent); stroke-width:1; opacity:.55; }}
  .edge {{ fill:none; stroke:var(--accent); stroke-width:1; opacity:.45; }}
  .back {{ fill:var(--accent); }}
  /* The tap marker sits ON the screenshot, at the point the log recorded. */
  /* Solid ring = tapped. Hollow dot = a candidate nobody tapped. */
  .tap {{ fill:none; stroke:var(--accent); stroke-width:1.5; }}
  .tapdot {{ fill:var(--accent); }}
  .gap {{ fill:none; stroke:#f0f0f4; stroke-width:1; opacity:.5; }}
  .elabel {{ fill:var(--muted); font-size:10px; paint-order:stroke;
             stroke:var(--bg); stroke-width:3px; opacity:.8; }}
  .node {{ position:absolute; border-radius:12px; background:var(--card);
           border:1px solid var(--border); overflow:hidden; }}
  .node.screen {{ display:flex; flex-direction:column; }}
  /* The card is sized to the capture, so the image fills it 1:1 — no contain,
     no crop, and a tap fraction maps straight onto the card. */
  .shot {{ height:{SHOT_H}px; background:#000; }}
  .shot img {{ width:100%; height:100%; display:block; }}
  .noshot {{ color:var(--muted); font-size:12px; }}
  .meta {{ height:{META_H}px; padding:0 8px; display:flex; align-items:center;
           justify-content:space-between; gap:6px; border-top:1px solid var(--border); }}
  .meta strong {{ font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .badge {{ font-size:11px; color:var(--warn); white-space:nowrap; }}
  .badge.done {{ color:var(--muted); }}
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
    <svg class="below" viewBox="0 0 {width} {height}">{edges_below}</svg>
    {"".join(cards)}
    <svg class="above" viewBox="0 0 {width} {height}">{edges_above}</svg>
  </div></div>
  <p class="legend">
    <span><i></i>탐험한 전이 — 선은 <strong>실제로 탭한 지점</strong>에서 출발한다</span>
    <span>◦ 화면 위 빈 점 = 아직 탭하지 않은 후보</span>
    <span>● 도착점이 위쪽이면 되돌아가는 전이</span>
    <span>세로축 = <strong>탐험 시작 화면으로부터의 거리</strong>이지 앱의 계층이 아니다</span>
  </p>
</body></html>
""", encoding="utf-8")
    gaps = sum(len(b["todo"]) for b in boxes)
    print(f"OK: wrote {out_path} ({len(cards_by_sig)} screens, {len(edges)} transitions, "
          f"{gaps} unexplored)")
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
