#!/usr/bin/env python3
"""Static plan-preview HTML builder.

Reads the structured artifacts the pipeline already emits and assembles a single
self-contained HTML page — a *numbered screen-flow storyboard* for review before
code generation:
  - Concept summary (Overview + Features + Screens) — addresses the "기획" review
  - Screen-flow storyboard: screens ordered (entry → tab groups) and numbered
    ①②③, rendered as a flow diagram; raw Navigation Structure kept in <details>
  - Mobile-frame screen gallery (one iPhone frame per screen, ordered + numbered).
    Each card carries id="screen-N" so injected critique can deep-link to it.
  - States & interaction (Empty/Loading/Error + Interaction Feel from design-spec)
  - Design tokens swatch (color + typography)
  - App icon preview
  - <!-- CRITIQUE_PLACEHOLDER --> marker for the skill to inject HIG critique

Inputs (graceful fallback when any is absent):
  .autobot/architecture.md   — Overview/Features/Screens/Navigation (prose)
  .autobot/architecture.json — rootScreens / featureModules (storyboard ordering)
  .autobot/design-spec.md    — Screen Designs map, color/typography, states
  .autobot/designs/*.png     — screen mockups
  .autobot/app-icon-1024.png — icon
  .autobot/build-state.json  — appName / displayName

No external dependencies. Output is offline-viewable.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6,8}\b")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
ARROW = '<span class="flow-arrow">→</span>'


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _norm_name(s: str) -> str:
    """Normalize a screen name for matching: lowercase, drop spaces and a
    trailing/embedded 'view' suffix so 'HomeView' == 'Home' == 'home view'.
    """
    return re.sub(r"\s+", "", (s or "").strip().lower()).replace("view", "")


def _slice_section(md: str, heading: str) -> str:
    """Return the content under a heading (any level) until the next heading of
    same-or-higher level. heading is the visible text, e.g. "Overview".
    """
    pattern = re.compile(
        rf"^(#{{1,6}})\s+{re.escape(heading)}\b.*?\n(.*?)(?=^#{{1,6}}\s+\S|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(md)
    return (m.group(2) if m else "").strip()


def _parse_overview(arch_md: str) -> str:
    body = _slice_section(arch_md, "Overview")
    body = re.sub(r"\n{2,}", "\n\n", body).strip()
    if not body:
        return ""
    # Take first paragraph only — keep concept summary tight
    para = body.split("\n\n", 1)[0]
    return para.strip()


def _parse_table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and any(cells):
            rows.append(cells)
    # First row is the header
    return rows[1:] if len(rows) > 1 else []


def _parse_features(arch_md: str) -> list[dict]:
    section = _slice_section(arch_md, "Features")
    rows = _parse_table_rows(section)
    out: list[dict] = []
    for r in rows:
        # template: # | Feature | Priority | Description
        if len(r) >= 4:
            out.append({"id": r[0], "name": r[1], "priority": r[2], "desc": r[3]})
        elif len(r) >= 3:
            out.append({"id": "", "name": r[0], "priority": r[1], "desc": r[2]})
    return out


def _parse_screens(arch_md: str) -> list[dict]:
    section = _slice_section(arch_md, "Screens")
    rows = _parse_table_rows(section)
    out: list[dict] = []
    for r in rows:
        # template: Screen | Purpose | Tab | Key UI Elements
        if len(r) >= 4:
            out.append({"name": r[0], "purpose": r[1], "tab": r[2], "ui": r[3]})
        elif len(r) >= 2:
            out.append({"name": r[0], "purpose": r[1], "tab": "", "ui": ""})
    return out


def _parse_navigation(arch_md: str) -> str:
    section = _slice_section(arch_md, "Navigation Structure")
    # Take the first fenced block (``` ... ```), or the section as-is if no fence
    fence = re.search(r"```[a-zA-Z]*\n(.*?)```", section, re.DOTALL)
    if fence:
        return fence.group(1).rstrip()
    # Strip leading blank lines and return up to ~30 lines
    lines = [ln for ln in section.splitlines() if ln.strip()]
    return "\n".join(lines[:30])


def _parse_screen_design_map(spec_md: str) -> dict[str, str]:
    """Authoritative screen→PNG mapping from design-spec.md's `## Screen Designs`
    table (`Screen | Design File | Screen ID | Description` — legacy builds with
    generated mockups). Returns {normalized_screen_name: png_basename}. Empty if
    the table is absent, which is the normal case for spec-only builds.
    """
    section = _slice_section(spec_md, "Screen Designs")
    rows = _parse_table_rows(section) if section else []
    out: dict[str, str] = {}
    for r in rows:
        if len(r) >= 2:
            name = r[0].strip()
            m = re.search(r"([^\s/|]+\.png)", r[1])
            if name and m:
                out[_norm_name(name)] = m.group(1)
    return out


def _parse_states(spec_md: str) -> list[dict]:
    """Empty/Loading/Error states from design-spec.md."""
    section = _slice_section(spec_md, "Empty, Loading, Error States")
    rows = _parse_table_rows(section) if section else []
    out: list[dict] = []
    for r in rows:
        if len(r) >= 2:
            out.append({
                "state": r[0],
                "visual": r[1] if len(r) > 1 else "",
                "tone": r[2] if len(r) > 2 else "",
                "action": r[3] if len(r) > 3 else "",
            })
    return out


def _parse_interaction(spec_md: str) -> str:
    """Interaction Feel prose (first ~2 paragraphs)."""
    body = _slice_section(spec_md, "Interaction Feel")
    body = re.sub(r"\n{2,}", "\n\n", body).strip()
    if not body:
        return ""
    return "\n\n".join(body.split("\n\n")[:2]).strip()


def _collect_colors(spec_md: str, arch_md: str) -> list[dict]:
    """Find color tokens. Prefer design-spec.md; fall back to architecture.md
    Color Palette table.
    """
    out: list[dict] = []

    spec_colors = _slice_section(spec_md, "Color Tokens") or _slice_section(spec_md, "Colors")
    rows = _parse_table_rows(spec_colors) if spec_colors else []
    for r in rows:
        # design-spec table shape varies; just find a hex in each row
        hexes = [m for cell in r for m in HEX_RE.findall(cell)]
        if hexes:
            label = r[0]
            out.append({"label": label, "hex": hexes[0]})

    if not out:
        arch_colors = _slice_section(arch_md, "Color Palette")
        rows = _parse_table_rows(arch_colors) if arch_colors else []
        for r in rows:
            # template: Role | Name | Light | Dark | Usage
            hexes = [m for cell in r for m in HEX_RE.findall(cell)]
            if hexes and len(r) >= 2:
                label = f"{r[0]} ({r[1]})" if r[1] else r[0]
                out.append({"label": label, "hex": hexes[0]})

    # Last-ditch fallback: scan any hex codes in either doc
    if not out:
        for src in (spec_md, arch_md):
            for h in HEX_RE.findall(src)[:6]:
                out.append({"label": h, "hex": h})
            if out:
                break

    return out[:10]


def _collect_typography(spec_md: str, arch_md: str) -> list[dict]:
    out: list[dict] = []
    section = _slice_section(spec_md, "Typography") or _slice_section(arch_md, "Typography Style")
    rows = _parse_table_rows(section) if section else []
    for r in rows:
        if len(r) >= 2:
            out.append({"role": r[0], "spec": " · ".join(r[1:])})
    return out[:8]


def _load_arch_json(project_dir: Path) -> dict:
    try:
        return json.loads((project_dir / ".autobot" / "architecture.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _order_screens(screens: list[dict], arch_json: dict) -> list[dict]:
    """Order screens into a storyboard sequence: entry (rootScreens) first, then
    by tab group. Tab groups are ordered by their position in featureModules
    when names match, else by first appearance. Stable within each group.
    Falls back to the original order when architecture.json is absent.
    """
    if not screens:
        return []

    root = [r.strip() for r in (arch_json.get("rootScreens") or []) if isinstance(r, str)]
    modules = [m.strip() for m in (arch_json.get("featureModules") or []) if isinstance(m, str)]
    root_norm = {_norm_name(r): i for i, r in enumerate(root)}

    tab_first_seen: dict[str, int] = {}
    for i, s in enumerate(screens):
        tab = (s.get("tab") or "").strip()
        if tab and tab not in tab_first_seen:
            tab_first_seen[tab] = i

    def module_index(tab: str):
        for mi, m in enumerate(modules):
            if _norm_name(m) == _norm_name(tab):
                return mi
        return None

    def sort_key(item):
        i, s = item
        rn = _norm_name(s.get("name", ""))
        if rn in root_norm:
            return (0, 0, root_norm[rn], i)
        tab = (s.get("tab") or "").strip()
        if not tab:
            return (2, 0, 0, i)
        mi = module_index(tab)
        if mi is not None:
            return (1, 0, mi, i)
        return (1, 1, tab_first_seen.get(tab, 0), i)

    indexed = sorted(enumerate(screens), key=sort_key)
    return [s for _, s in indexed]


def _png_data_uri(path: Path) -> str:
    try:
        b = path.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")


def _load_state(project_dir: Path) -> dict:
    state_path = project_dir / ".autobot" / "build-state.json"
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _build_cards(designs_dir: Path, ordered_screens: list[dict], design_map: dict[str, str]) -> list[dict]:
    """Resolve a PNG for each ordered screen and assign storyboard numbers.

    Resolution order per screen: design-spec.md `## Screen Designs` mapping
    (authoritative) → stem heuristic. Screens with no PNG get a placeholder card
    (keeps numbering aligned with the screen list + surfaces ungenerated screens).
    PNGs not referenced by any screen are appended with continuing numbers.
    """
    pngs = sorted(p for p in designs_dir.glob("*.png") if p.is_file()) if designs_dir.is_dir() else []
    by_stem = {p.stem.lower(): p for p in pngs}

    def resolve(screen: dict):
        name = screen.get("name", "").strip()
        key = _norm_name(name)
        fn = design_map.get(key)
        if fn:
            p = designs_dir / fn
            if p.is_file():
                return p
        return (
            by_stem.get(name.lower())
            or by_stem.get(key)
            or by_stem.get(name.lower().replace(" ", ""))
        )

    cards: list[dict] = []
    used: set[Path] = set()
    n = 0
    for s in ordered_screens:
        n += 1
        png = resolve(s)
        if png in used:
            png = None
        if png:
            used.add(png)
        cards.append({"n": n, "screen": s, "png": png})

    for p in pngs:
        if p not in used:
            n += 1
            cards.append({
                "n": n,
                "screen": {"name": p.stem, "purpose": "", "tab": "", "ui": ""},
                "png": p,
                "extra": True,
            })
    return cards


def _priority_class(prio: str) -> str:
    p = prio.lower()
    if "p0" in p:
        return "p0"
    if "p1" in p:
        return "p1"
    if "p2" in p:
        return "p2"
    return "px"


def _features_html(features: list[dict]) -> str:
    if not features:
        return '<p class="muted">기능 정보가 없습니다.</p>'
    items: list[str] = []
    for f in features:
        prio = _esc(f.get("priority", ""))
        items.append(
            f'<li><span class="prio prio-{_priority_class(prio)}">{prio}</span> '
            f'<strong>{_esc(f.get("name", ""))}</strong> '
            f'<span class="muted">— {_esc(f.get("desc", ""))}</span></li>'
        )
    return "<ul class=\"features-list\">\n" + "\n".join(items) + "\n</ul>"


def _screens_html(ordered_screens: list[dict]) -> str:
    if not ordered_screens:
        return '<p class="muted">화면 목록이 없습니다.</p>'
    items: list[str] = []
    for i, s in enumerate(ordered_screens, 1):
        tab = (" · " + _esc(s.get("tab", ""))) if s.get("tab") else ""
        items.append(
            f'<li><span class="ord">{i}</span> <strong>{_esc(s.get("name", ""))}</strong> '
            f'<span class="muted">— {_esc(s.get("purpose", ""))}</span>{tab}</li>'
        )
    return "<ul class=\"screens-list\">\n" + "\n".join(items) + "\n</ul>"


def _flow_html(ordered_screens: list[dict], arch_json: dict, navigation: str) -> str:
    nav_details = ""
    if navigation and navigation.strip():
        nav_details = (
            f'<details><summary>원본 네비게이션 정의</summary><pre>{_esc(navigation)}</pre></details>'
        )

    if not ordered_screens:
        return f'<div class="flow"><p class="muted">화면 흐름 정보가 없습니다.</p>{nav_details}</div>'

    root_norm = {_norm_name(r) for r in (arch_json.get("rootScreens") or []) if isinstance(r, str)}

    def lane(s: dict) -> str:
        if _norm_name(s.get("name", "")) in root_norm:
            return "진입"
        tab = (s.get("tab") or "").strip()
        return tab if tab else "기타"

    groups: list[tuple[str, list[tuple[int, str]]]] = []
    for n, s in enumerate(ordered_screens, 1):
        ln = lane(s)
        node = (n, s.get("name", ""))
        if groups and groups[-1][0] == ln:
            groups[-1][1].append(node)
        else:
            groups.append((ln, [node]))

    rows: list[str] = []
    for ln, items in groups:
        nodes = [f'<a class="flow-node" href="#screen-{n}">{n}. {_esc(nm)}</a>' for n, nm in items]
        rows.append(
            f'<div class="flow-row"><span class="flow-lane">{_esc(ln)}</span>{ARROW.join(nodes)}</div>'
        )
    return f'<div class="flow">{"".join(rows)}{nav_details}</div>'


def _gallery_html(cards: list[dict]) -> str:
    if not cards:
        return ('<p class="muted">디자인 PNG 가 없습니다 — Phase 2 는 design-spec 직접 저작이 기본이므로 '
                '정상입니다 (design-spec.md 를 확인하세요).</p>')
    out: list[str] = []
    for c in cards:
        n = c["n"]
        s = c["screen"]
        png = c.get("png")
        if png:
            data = _png_data_uri(png)
            shot = (f'<img class="iphone-png" alt="{_esc(s.get("name", ""))}" src="{data}">'
                    if data else '<div class="shot-empty">PNG 읽기 실패</div>')
        else:
            shot = '<div class="shot-empty">디자인 미생성</div>'
        extra = ' <span class="muted">· 추가 PNG</span>' if c.get("extra") else ""
        ui = (f'<p class="ui-hint muted">{_esc(s.get("ui", ""))}</p>') if s.get("ui") else ""
        out.append(
            f'<div class="screen-card" id="screen-{n}">'
            f'<span class="ord ord-lg">{n}</span>'
            f'<div class="iphone"><div class="iphone-screen-area">{shot}</div></div>'
            f'<div class="screen-meta"><strong>{_esc(s.get("name", ""))}</strong>{extra}'
            f'<p class="muted">{_esc(s.get("purpose", ""))}</p>{ui}</div>'
            f'</div>'
        )
    return '<div class="gallery">' + "".join(out) + "</div>"


def _swatch_html(colors: list[dict]) -> str:
    if not colors:
        return '<p class="muted">색 토큰을 추출하지 못했습니다.</p>'
    items: list[str] = []
    for c in colors:
        items.append(
            f'<div class="swatch-item">'
            f'  <div class="swatch-color" style="background:{_esc(c["hex"])}"></div>'
            f'  <div class="swatch-label">{_esc(c["label"])}<br><code>{_esc(c["hex"])}</code></div>'
            f'</div>'
        )
    return '<div class="swatch">' + "".join(items) + "</div>"


def _typography_html(rows: list[dict]) -> str:
    if not rows:
        return '<p class="muted">타이포 정보가 없습니다.</p>'
    items: list[str] = []
    for r in rows:
        items.append(
            f'<li><strong>{_esc(r["role"])}</strong> <span class="muted">— {_esc(r["spec"])}</span></li>'
        )
    return '<ul class="typography-list">' + "".join(items) + "</ul>"


def _states_section_html(states: list[dict], interaction: str) -> str:
    """Render the states + interaction section, or "" when neither is present."""
    parts: list[str] = []
    if states:
        rows = "".join(
            f'<tr><td><strong>{_esc(s["state"])}</strong></td><td>{_esc(s["visual"])}</td>'
            f'<td class="muted">{_esc(s["tone"])}</td><td>{_esc(s["action"])}</td></tr>'
            for s in states
        )
        parts.append(
            '<h3>Empty / Loading / Error</h3>'
            '<table class="states-table"><thead><tr>'
            '<th>상태</th><th>비주얼</th><th>톤</th><th>액션</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    if interaction:
        paras = "".join(f"<p>{_esc(p)}</p>" for p in interaction.split("\n\n") if p.strip())
        parts.append(f"<h3>인터랙션 감각</h3>{paras}")
    if not parts:
        return ""
    return '<section><h2>상태 &amp; 인터랙션</h2>' + "".join(parts) + "</section>"


def _build_html(ctx: dict) -> str:
    html_template = TEMPLATE
    for key, value in ctx.items():
        html_template = html_template.replace(f"{{{{{key}}}}}", value)
    return html_template


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{APP_NAME}} — Plan Preview</title>
<style>
  :root {
    --bg: #f4f4f7;
    --surface: #ffffff;
    --text: #1c1c1e;
    --muted: #6b6b70;
    --border: #e5e5ea;
    --accent: #007aff;
    --shot-letterbox: #e9e9ee;
    --critique-bg: #fff7f0;
    --critique-border: #ff6b35;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1c1c1e;
      --surface: #2c2c2e;
      --text: #f2f2f7;
      --muted: #aeaeb2;
      --border: #3a3a3c;
      --shot-letterbox: #000000;
      --critique-bg: #3a2a1a;
      --critique-border: #ff8c5a;
    }
  }
  * { box-sizing: border-box; }
  body {
    font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    background: var(--bg); color: var(--text);
    margin: 0; padding: 24px;
  }
  .container { max-width: 1200px; margin: 0 auto; }
  header { display: flex; align-items: center; gap: 20px; margin-bottom: 32px; }
  header img.icon { width: 96px; height: 96px; border-radius: 22px; box-shadow: 0 4px 14px rgba(0,0,0,0.1); }
  header h1 { margin: 0; font-size: 34px; font-weight: 700; }
  header .subtitle { margin: 4px 0 0; color: var(--muted); }
  section {
    background: var(--surface);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    border: 1px solid var(--border);
  }
  section h2 { margin: 0 0 12px; font-size: 22px; }
  section h3 { margin: 18px 0 8px; font-size: 16px; color: var(--muted); }
  .muted { color: var(--muted); }
  ul { padding-left: 18px; }
  ul.features-list, ul.screens-list { list-style: none; padding: 0; }
  ul.features-list li, ul.screens-list li { padding: 6px 0; border-bottom: 1px solid var(--border); }
  ul.features-list li:last-child, ul.screens-list li:last-child { border-bottom: none; }
  .prio { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; margin-right: 8px; vertical-align: middle; }
  .prio-p0 { background: #ff3b30; color: white; }
  .prio-p1 { background: #ff9500; color: white; }
  .prio-p2 { background: #8e8e93; color: white; }
  .prio-px { background: var(--border); color: var(--text); }
  /* storyboard ordinal badge — same number on screen list, flow node, gallery card */
  .ord { display: inline-flex; align-items: center; justify-content: center; min-width: 20px; height: 20px; padding: 0 6px; border-radius: 10px; background: var(--accent); color: #fff; font-size: 12px; font-weight: 700; margin-right: 6px; }
  .ord-lg { position: absolute; top: 10px; left: 10px; z-index: 2; box-shadow: 0 1px 4px rgba(0,0,0,0.3); }
  pre {
    background: var(--bg); padding: 16px; border-radius: 12px;
    overflow-x: auto; font: 13px/1.5 ui-monospace, SF Mono, Menlo, monospace;
  }
  /* screen-flow storyboard */
  .flow { display: flex; flex-direction: column; gap: 12px; }
  .flow-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .flow-lane { font-size: 12px; font-weight: 700; color: var(--muted); min-width: 72px; text-transform: uppercase; letter-spacing: 0.04em; }
  .flow-node { display: inline-flex; align-items: center; gap: 6px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 6px 12px; text-decoration: none; color: var(--text); font-size: 14px; font-weight: 600; }
  .flow-node:hover { border-color: var(--accent); }
  .flow-arrow { color: var(--muted); }
  .flow details { margin-top: 14px; }
  .flow summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .gallery {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 24px;
  }
  .screen-card {
    position: relative;
    background: var(--bg);
    border-radius: 14px;
    padding: 16px;
    border: 1px solid var(--border);
    scroll-margin-top: 24px;
  }
  /* deep-link target: critique "→ 화면 N" highlights the card */
  .screen-card:target { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent); }
  /* iPhone 16 Pro frame — aspect 393/852. object-fit: contain so the FULL screen
     (incl. bottom home-indicator / tab-bar safe area that critique must judge)
     is shown un-cropped; letterbox fills any aspect mismatch. */
  .iphone {
    width: 240px;
    aspect-ratio: 393 / 852;
    margin: 0 auto 12px;
    background: #000;
    border-radius: 38px;
    padding: 6px;
    box-shadow: 0 8px 28px rgba(0,0,0,0.22);
    position: relative;
    display: flex;
    overflow: hidden;
  }
  .iphone-screen-area {
    position: relative;
    flex: 1;
    background: var(--shot-letterbox);
    border-radius: 32px;
    overflow: hidden;
  }
  .iphone-png {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    object-position: center;
    display: block;
  }
  .shot-empty {
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    color: var(--muted); font-size: 12px; text-align: center; padding: 12px;
  }
  .screen-meta strong { display: block; margin-top: 4px; }
  .screen-meta .ui-hint { margin: 4px 0 0; font-size: 13px; }
  .swatch { display: flex; gap: 14px; flex-wrap: wrap; }
  .swatch-item { width: 110px; text-align: center; }
  .swatch-color { width: 110px; height: 80px; border-radius: 12px; border: 1px solid var(--border); }
  .swatch-label { margin-top: 6px; font-size: 12px; line-height: 1.4; }
  .swatch-label code { background: var(--bg); padding: 1px 6px; border-radius: 4px; }
  ul.typography-list { list-style: none; padding: 0; }
  ul.typography-list li { padding: 4px 0; }
  .states-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .states-table th, .states-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  .states-table th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }
  .critique {
    background: var(--critique-bg);
    border-left: 4px solid var(--critique-border);
    padding: 20px 24px;
  }
  .critique h2 { color: var(--critique-border); }
  .critique-placeholder { color: var(--muted); font-style: italic; }
  /* injected critique deep-link chip (autobot-plan-preview skill) */
  .critique-screen { display: inline-block; margin-left: 8px; font-size: 12px; font-weight: 600; color: var(--accent); text-decoration: none; border: 1px solid var(--accent); border-radius: 8px; padding: 1px 8px; }
  .critique-screen:hover { background: var(--accent); color: #fff; }
  footer { text-align: center; color: var(--muted); font-size: 13px; padding: 20px 0; }
  footer code { background: var(--surface); padding: 2px 8px; border-radius: 6px; }
</style>
</head>
<body>
<div class="container">

<header>
  {{ICON_TAG}}
  <div>
    <h1>{{DISPLAY_NAME}}</h1>
    <p class="subtitle">Plan Preview · <code>{{APP_NAME}}</code></p>
  </div>
</header>

<section class="concept">
  <h2>이 빌드가 만들 앱</h2>
  <p>{{OVERVIEW}}</p>

  <h3>주요 기능</h3>
  {{FEATURES_HTML}}

  <h3>화면 목록</h3>
  {{SCREENS_HTML}}
</section>

<section>
  <h2>화면 흐름 (스토리보드)</h2>
  {{FLOW_HTML}}
</section>

<section>
  <h2>화면 디자인</h2>
  {{GALLERY_HTML}}
</section>

{{STATES_SECTION}}

<section>
  <h2>디자인 토큰</h2>
  <h3>Color</h3>
  {{SWATCH_HTML}}
  <h3>Typography</h3>
  {{TYPOGRAPHY_HTML}}
</section>

<section class="critique">
  <h2>🔍 Critique (LLM 자동 분석)</h2>
  <p class="muted">각 항목의 <strong>→ 화면 N</strong> 칩을 누르면 해당 화면 카드로 이동합니다.</p>
  <!-- CRITIQUE_PLACEHOLDER -->
  <p class="critique-placeholder">critique 가 아직 주입되지 않았습니다. autobot-plan-preview 스킬이 이 자리에 분석 결과를 채웁니다.</p>
</section>

<footer>
  <p>이 미리보기는 코드 생성 전 기획·디자인 검토용입니다.</p>
  <p>OK 면 <code>/autobot:resume</code> 으로 Phase 3 부터 진입.<br>
  다시 디자인 받으려면 같은 디렉토리에서 <code>/autobot:plan</code> 재호출.</p>
</footer>

</div>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build plan-preview HTML")
    parser.add_argument("--project-dir", default=".", help="Project directory (default: cwd)")
    parser.add_argument("--output", default=None, help="Output HTML path (default: <project>/.autobot/designs/preview/index.html)")
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    autobot = project / ".autobot"
    arch_md_path = autobot / "architecture.md"
    spec_md_path = autobot / "design-spec.md"
    designs_dir = autobot / "designs"
    icon_path = autobot / "app-icon-1024.png"

    if not arch_md_path.is_file():
        print(f"FATAL: {arch_md_path} not found", file=sys.stderr)
        return 1
    if not spec_md_path.is_file():
        print(f"WARN: {spec_md_path} not found — proceeding with architecture.md only", file=sys.stderr)

    out_path = Path(args.output) if args.output else (designs_dir / "preview" / "index.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arch_md = _read(arch_md_path)
    spec_md = _read(spec_md_path) if spec_md_path.is_file() else ""
    arch_json = _load_arch_json(project)

    state = _load_state(project)
    app_name = state.get("appName") or "App"
    display_name = state.get("displayName") or app_name

    overview = _parse_overview(arch_md)
    features = _parse_features(arch_md)
    screens = _parse_screens(arch_md)
    navigation = _parse_navigation(arch_md)
    colors = _collect_colors(spec_md, arch_md)
    typography = _collect_typography(spec_md, arch_md)
    design_map = _parse_screen_design_map(spec_md)
    states = _parse_states(spec_md)
    interaction = _parse_interaction(spec_md)

    ordered = _order_screens(screens, arch_json)
    cards = _build_cards(designs_dir, ordered, design_map)

    icon_data_uri = _png_data_uri(icon_path) if icon_path.is_file() else ""
    icon_tag = f'<img class="icon" alt="App Icon" src="{icon_data_uri}">' if icon_data_uri else ""

    context = {
        "APP_NAME": _esc(app_name),
        "DISPLAY_NAME": _esc(display_name),
        "ICON_TAG": icon_tag,
        "OVERVIEW": _esc(overview) or '<span class="muted">Overview 섹션을 찾지 못했습니다.</span>',
        "FEATURES_HTML": _features_html(features),
        "SCREENS_HTML": _screens_html(ordered),
        "FLOW_HTML": _flow_html(ordered, arch_json, navigation),
        "GALLERY_HTML": _gallery_html(cards),
        "STATES_SECTION": _states_section_html(states, interaction),
        "SWATCH_HTML": _swatch_html(colors),
        "TYPOGRAPHY_HTML": _typography_html(typography),
    }

    out_path.write_text(_build_html(context), encoding="utf-8")
    matched = sum(1 for c in cards if c.get("png") and not c.get("extra"))
    print(f"OK: preview written to {out_path}")
    print(f"  screens: {len(ordered)} (matched PNGs: {matched}), cards: {len(cards)}")
    print(f"  features: {len(features)}, colors: {len(colors)}, typography: {len(typography)}, states: {len(states)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
