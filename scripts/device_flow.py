#!/usr/bin/env python3
"""device_flow.py — the exploration run, read back.

`device_wda.sh` appends one JSON line per screen capture and per tap to
`.autobot/clone/flow.jsonl`. That log is the whole state of an exploration, which
is what makes the three things below possible:

    device_flow.py next <flow.jsonl>              What is still unexplored.
    device_flow.py map  <flow.jsonl> <out.html>    The flow map, for a human.
    device_flow.py stats <flow.jsonl>              Coverage, one line.

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

import html
import json
import os
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path: str) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def screens(events: list[dict]) -> "OrderedDict[str, dict]":
    """node key → the first capture of that screen (name, tree, png)."""
    out: OrderedDict[str, dict] = OrderedDict()
    for e in events:
        if e.get("type") == "screen" and e.get("node") and e["node"] not in out:
            out[e["node"]] = e
    return out


def taps(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tap"]


def changed(tap: dict) -> bool:
    """Accept the JSON strings emitted by the shell driver and bool fixtures."""
    return str(tap.get("changed", "")).lower() == "true"


def capture_gaps(events: list[dict], rows: list[dict] | None = None) -> dict[str, list]:
    """Return missing artifacts that must keep coverage from becoming complete.

    A tap records a transition, not a durable destination screenshot/tree. The
    latter is needed by measurement and reproduction, so a changed tap whose
    destination was never captured is an explicit gap instead of a silent
    success. Missing source trees are handled here too: without them the
    candidate list cannot be reconstructed for resume.
    """
    missing_destinations = []
    unresolved_destinations = []
    for index, tap in enumerate(events):
        if tap.get("type") != "tap":
            continue
        if not changed(tap):
            continue
        destination = tap.get("to", "?")
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
            and (unresolved or e.get("node") == destination)
            for e in events[index + 1:])
        if not destination_captured:
            (unresolved_destinations if unresolved else missing_destinations).append(tap)
    missing_trees = [r for r in (rows or frontier(events)) if r.get("tree_missing")]
    return {
        "missing_trees": missing_trees,
        "missing_destinations": missing_destinations,
        "unresolved_destinations": unresolved_destinations,
    }


def candidates_of(tree: str) -> list[tuple[int, int, str]]:
    """(x, y, label) a screen offers — the same list the tap guard enforces."""
    if not Path(tree).exists():
        return []
    proc = subprocess.run([sys.executable, str(HERE / "device_a11y.py"), "candidates", tree],
                          capture_output=True, text=True)
    found = []
    for line in proc.stdout.splitlines():
        if line.startswith("INFO: tap "):
            parts = line[len("INFO: tap "):].split(" | ")
            xy = parts[0].split()
            found.append((int(xy[0]), int(xy[1]), parts[-1]))
    return found


def frontier(events: list[dict]) -> list[dict]:
    """Per screen: which of its targets were never tapped."""
    tapped: dict[str, list] = {}
    for t in taps(events):
        tapped.setdefault(t.get("from", ""), []).append(
            (t.get("label", "?"), int(t["x"]), int(t["y"])))
    out = []
    for key, screen in screens(events).items():
        done = tapped.get(key, [])
        tree = screen.get("tree", "")
        if not tree or not Path(tree).is_file():
            out.append({"node": key, "name": screen.get("name", key),
                        "tree": tree, "png": screen.get("png", ""),
                        "total": 0, "todo": [], "tree_missing": True})
            continue
        # Matched with tolerance, not equality: the same screen captured twice
        # reports the back button at (38,72) and (38,71). On exact coordinates
        # that target stays "unexplored" forever — coverage under-reports and
        # `next` keeps proposing work already done. Same 12pt bucket the tap
        # candidate list already uses to collapse duplicates.
        def is_done(c, done=done):
            return any((lab == c[2] or "?" in (lab, c[2]))
                       and abs(x - c[0]) <= 12 and abs(y - c[1]) <= 12
                       for lab, x, y in done)
        candidates = candidates_of(tree)
        todo = [c for c in candidates if not is_done(c)]
        out.append({"node": key, "name": screen.get("name", key),
                    "tree": tree, "png": screen.get("png", ""),
                    "total": len(candidates), "todo": todo, "tree_missing": False})
    return out


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
        print("OK: frontier empty — every candidate of every captured screen was tapped")
        return 0
    # Shallowest first, by the same depths the map draws: breadth-first keeps the
    # upper levels complete when the run is cut short, which it usually is.
    depth = _depths([r["node"] for r in rows], _edges(events))
    pending.sort(key=lambda r: depth.get(r["node"], 0))
    for r in pending:
        print(f"INFO: screen {r['name']} ({r['node']}) — {len(r['todo'])}/{r['total']} unexplored")
        for x, y, label in r["todo"]:
            print(f"INFO:   tap {x} {y} | {label}")
        print(f"INFO:   tree {r['tree']}")
    total_todo = sum(len(r["todo"]) for r in pending)
    _print_capture_gaps(gaps)
    print(f"OK: {total_todo} unexplored targets across {len(pending)} screens — "
          "re-foreground the app, re-capture that screen, then tap from ITS fresh candidates")
    return 0


def _print_capture_gaps(gaps: dict[str, list]) -> None:
    if gaps["missing_trees"]:
        print(f"WARN: {len(gaps['missing_trees'])} captured screen(s) have no accessibility tree — "
              "re-run device_wda.sh screen before claiming coverage")
    if gaps["missing_destinations"]:
        nodes = sorted({t.get("to", "?") for t in gaps["missing_destinations"]})
        print(f"WARN: {len(gaps['missing_destinations'])} changed transition(s) have no destination capture "
              f"({', '.join(nodes)}) — run device_wda.sh screen after each changed tap, "
              "or re-visit those screens now and capture them")
    if gaps["unresolved_destinations"]:
        print(f"WARN: {len(gaps['unresolved_destinations'])} changed transition(s) have no resolvable destination "
              "— re-capture the destination screen and inspect the WDA session")


def cmd_stats(path: str) -> int:
    events = load(path)
    rows = frontier(events)
    total = sum(r["total"] for r in rows)
    todo = sum(len(r["todo"]) for r in rows)
    dead = [t for t in taps(events) if not changed(t)]
    gaps = capture_gaps(events, rows)
    print(f"INFO: screens {len(rows)}")
    print(f"INFO: targets {total - todo}/{total} explored, {todo} left")
    if dead:
        print(f"INFO: no-op taps {len(dead)} (target changed nothing)")
    _print_capture_gaps(gaps)
    incomplete = any(gaps.values())
    if todo:
        status = f"partial ({todo} unexplored)"
        if incomplete:
            status += "; evidence incomplete"
    elif incomplete:
        status = "incomplete (screen evidence missing)"
    else:
        status = "complete"
    print("OK: coverage " + status)
    return 0


def _edges(events: list[dict]) -> list[tuple[str, str, str]]:
    seen, out = set(), []
    for t in taps(events):
        edge = (t.get("from", "?"), t.get("to", "?"), t.get("label", "?"))
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
            box["total"] = rows.get(key, {}).get("total", 0)

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
    rows = {r["node"]: r for r in frontier(events)}
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

    total = sum(r["total"] for r in rows.values())
    left = sum(len(r["todo"]) for r in rows.values())
    banner = (f'화면 {len(scr)}개 · 탭 후보 {total - left}/{total} 탐험'
              + (f' · <strong>미탐험 {left}</strong> (점선 노드)' if left else ' · 전수 완료'))

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


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    try:
        if mode in ("next", "stats") and len(argv) == 3:
            return (cmd_next if mode == "next" else cmd_stats)(argv[2])
        if mode == "map" and len(argv) == 4:
            return cmd_map(argv[2], argv[3])
    except FileNotFoundError:
        print(f"ERROR: no exploration log at {argv[2]} — capture a screen first "
              "(`device_wda.sh screen` writes it)", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: corrupt exploration log {argv[2]}: {exc}", file=sys.stderr)
        return 1
    print("ERROR: usage: device_flow.py next|stats <flow.jsonl> | map <flow.jsonl> <out.html>",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
