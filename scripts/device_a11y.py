#!/usr/bin/env python3
"""device_a11y.py — accessibility-tree reader for /autobot:copy.

Single source of the exploration safety logic, shared by both drivers:

  - WebDriverAgent (real devices, via `device_wda.sh`)  → XML from GET /source
  - idb            (simulators, via `device_idb.sh`)    → JSON from `ui describe-all`

The format is auto-detected, normalized to one element shape, and then the same
guards apply to both. Modes:

  candidates <file>   Tappable elements with tap centers. Destructive labels are
                      withheld; a system dialog suppresses the list entirely.
  sig <file>          Screen signature (hash of the label set) — the exploration
                      loop's termination primitive.

Output follows CONVENTIONS.md prefixes (OK:/INFO:/WARN:/ERROR:).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

# Anything a blind tap must never hit. Bilingual — the tree carries the app's own
# locale, so a Korean build says 삭제 where an English one says Delete.
# NOTE: bare 취소/Cancel is deliberately absent — dismissing a sheet is the loop's
# escape hatch. Only the subscription sense (구독 취소/해지) is withheld.
DESTRUCTIVE = re.compile(
    "삭제|제거|지우|비우기|구매|결제|구독|주문|로그아웃|로그 아웃|사인아웃|탈퇴|"
    "초기화|재설정|복원|해지|신고|차단"
    "|delete|remove|erase|clear all|reset|buy|purchase|subscrib|checkout"
    "|sign ?out|log ?out|pay\\b|payment|restore|unsubscribe|cancel (account|subscription|plan)"
    "|deactivate|block|report",
    re.I,
)

# Verified against a live ATT prompt: idb reports system dialogs as a flat
# StaticText/Button tree under a blank AXApplication with NO alert role anywhere.
# So vocabulary is the primary signal, not role. A false positive costs a stop
# (safe); a false negative taps "Allow" (not safe). High-specificity only —
# generic 확인/취소/OK/Continue also appear on ordinary screens.
SYSTEM_DIALOG = re.compile(
    "^(허용|허용 안 함|한 번 허용|앱을 사용하는 동안|앱에 추적 금지 요청|추적 허용|"
    "알림 허용|위치 정보 허용|설정 열기)$"
    "|^(allow|don.t allow|allow once|allow while using( the app)?|while using the app"
    "|ask app not to track|allow tracking|open settings|keep current setting)$",
    re.I,
)

# Containers: their children are the tap targets, they are not. Both spellings —
# idb reports AX* roles, WDA reports XCUIElementType* which we map to AX*.
CONTAINERS = {
    "AXApplication", "AXWindow", "AXScrollArea", "AXScrollView", "AXTable",
    "AXCollection", "AXCollectionView", "AXTabBar", "AXNavigationBar",
    "AXToolbar", "AXSplitGroup", "AXList", "AXKeyboard", "AXStatusBar",
}

# Decoration that is exposed as an element but navigates nowhere.
NOISE = re.compile("스크롤 막대|scroll bar|페이지 컨트롤|page control", re.I)

# When one label sits at one spot under several roles, tap the real control.
ROLE_RANK = {"AXButton": 3, "AXCell": 3, "AXLink": 3, "AXSwitch": 2, "AXStaticText": 1}


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _parse_wda(raw: str) -> list[dict]:
    """WebDriverAgent GET /source — nested XML with x/y/width/height attributes.

    Depth and parent index are carried through: `candidates` does not need them,
    but reproduction does — stack direction and nesting are only recoverable
    from the hierarchy, and flattening it loses the layout.
    """
    out = []
    stack = [(ET.fromstring(raw), -1, -1)]  # (node, depth, index-in-out)
    while stack:
        node, depth, parent = stack.pop()
        index = -1
        kind = node.get("type") or node.tag
        role = "AX" + kind[len("XCUIElementType"):] if kind.startswith("XCUIElementType") else kind
        try:
            frame = {k: float(node.get(k, 0) or 0) for k in ("x", "y", "width", "height")}
        except ValueError:
            frame = None
        if frame is not None:
            index = len(out)
            out.append({
                "role": role,
                "label": _clean(node.get("label")) or _clean(node.get("name")) or _clean(node.get("value")),
                "enabled": node.get("enabled") != "false",
                # WDA reports visibility directly — more reliable than a bounds check.
                "visible": None if node.get("visible") is None else node.get("visible") == "true",
                "frame": frame,
                "depth": depth + 1,
                "parent": parent,
            })
        for child in reversed(list(node)):
            stack.append((child, depth + 1, index if index >= 0 else parent))
    return out


def _parse_idb(raw: str) -> list[dict]:
    """idb `ui describe-all` — a flat JSON array (or one object per line)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = [data]
    out = []
    for e in data:
        if not isinstance(e, dict):
            continue
        f = e.get("frame") if isinstance(e.get("frame"), dict) else {}
        out.append({
            "role": e.get("role") or e.get("type") or "?",
            "label": _clean(e.get("AXLabel")) or _clean(e.get("title")) or _clean(e.get("AXValue")),
            "enabled": e.get("enabled") is not False,
            "visible": None,  # idb does not report it — fall back to a bounds check
            "frame": {k: float(f.get(k, 0) or 0) for k in ("x", "y", "width", "height")},
            # idb's dump is already flat: no hierarchy to recover.
            "depth": None,
            "parent": -1,
        })
    return out


def load(path: str) -> list[dict]:
    raw = open(path, encoding="utf-8").read().strip()
    if not raw:
        return []
    return _parse_wda(raw) if raw.startswith("<") else _parse_idb(raw)


def sig(els: list[dict]) -> None:
    labels = sorted({e["label"] for e in els if e["label"]})
    digest = hashlib.sha1("\n".join(labels).encode()).hexdigest()[:12]
    print(f"INFO: sig {digest}")
    print(f"INFO: elements {len(els)} labelled {len(labels)}")


# Element counts are bucketed so that scrolling a list — which changes how many
# rows are on screen — does not mint a new screen. Buckets are wide enough to
# absorb a row or two and narrow enough that an empty list (0 cells) and a
# populated one (5 cells) stay different screens: those ARE different layouts to
# reproduce.
def _bucket(n: int) -> str:
    for edge in (0, 1, 2, 4, 8, 16):
        if n <= edge:
            return str(edge)
    return "16+"


def nodekey(els: list[dict]) -> None:
    """Structural screen identity — the node key for the flow graph.

    `sig` hashes the label set, which is right for the tap guard (any change
    means the screen moved) but wrong for a graph: the same list with different
    data, or scrolled by one row, would be a new node and the exploration queue
    would never drain. This hashes structure instead — role counts plus the
    navigation bar's own label, which names the screen rather than its data.
    """
    # Containers and keyboard keys are excluded: they are plumbing, not identity.
    # The same empty-list screen was captured twice minutes apart and split into
    # two nodes because one dump carried an AXToolbar wrapper and the other put
    # the same button under an AXOther — a graph that doubles its nodes on
    # wrapper churn cannot report coverage.
    counts = Counter(e["role"] for e in els
                     if e["frame"]["width"] > 0
                     and e["role"] not in CONTAINERS
                     and e["role"] not in ("AXOther", "AXKey"))
    shape = [f"{role}:{_bucket(n)}" for role, n in sorted(counts.items())]
    titles = sorted({e["label"] for e in els
                     if e["role"] in ("AXNavigationBar", "AXTabBar") and e["label"]})
    digest = hashlib.sha1("\n".join(titles + shape).encode()).hexdigest()[:12]
    print(f"INFO: nodekey {digest}")
    print(f"INFO: shape {' '.join(shape)}")


def candidates(els: list[dict]) -> None:
    modal = [
        e for e in els
        if "alert" in e["role"].lower() or "sheet" in e["role"].lower()
        or SYSTEM_DIALOG.match(e["label"])
    ]
    if modal:
        hit = modal[0]
        print(f"WARN: alert/sheet on screen ({hit['label'] or hit['role']}) — a system or "
              "destructive dialog is up; stop and hand back to the user")
        print("OK: 0 tappable, 0 withheld")
        return

    bounds = next((e["frame"] for e in els if e["role"] == "AXApplication"), {})
    bw, bh = bounds.get("width", 0), bounds.get("height", 0)

    picked = {}
    for e in els:
        f, w, h = e["frame"], e["frame"]["width"], e["frame"]["height"]
        if not e["label"] or not e["enabled"] or e["role"] in CONTAINERS:
            continue
        if w <= 0 or h <= 0 or e["visible"] is False or NOISE.search(e["label"]):
            continue
        cx, cy = int(f["x"] + w / 2), int(f["y"] + h / 2)
        # Offscreen check only where visibility is not reported (idb).
        if e["visible"] is None and (cx < 0 or cy < 0 or (bw and cx > bw) or (bh and cy > bh)):
            continue
        # A control and its inner text land on the same spot with the same label
        # (verified: a WDA Button "계속" wrapping a StaticText "계속"). Collapse
        # them into one target and keep the most actionable role.
        key = (e["label"], cx // 12, cy // 12)
        rank = ROLE_RANK.get(e["role"], 0)
        if key not in picked or rank > picked[key][0]:
            picked[key] = (rank, cx, cy, e["role"], e["label"], w * h, f)

    # A list row and each line of text inside it are separate elements with
    # DIFFERENT labels, so the same-label collapse above cannot merge them —
    # a real Journal screen produced 31 "targets" for ~6 real ones. Tapping the
    # row is what navigates, so inert text/images sitting inside a bigger
    # candidate are dropped. Actionable roles are never dropped: a button inside
    # a row (e.g. "새로운 일기") is its own target.
    kept = []
    for c in sorted(picked.values(), key=lambda c: -c[5]):
        rank, cx, cy, _role, _lab, area, _f = c
        if rank < 2 and any(
            area < k[5]
            and k[6]["x"] <= cx <= k[6]["x"] + k[6]["width"]
            and k[6]["y"] <= cy <= k[6]["y"] + k[6]["height"]
            for k in kept
        ):
            continue
        kept.append(c)

    taps, withheld = [], []
    for _, cx, cy, role, lab, _area, _f in sorted(kept, key=lambda c: (c[2], c[1])):
        (withheld if DESTRUCTIVE.search(lab) else taps).append((cx, cy, role, lab))

    for cx, cy, role, lab in taps:
        print(f"INFO: tap {cx} {cy} | {role} | {lab}")
    for cx, cy, role, lab in withheld:
        print(f"WARN: withheld {cx} {cy} | {role} | {lab} — destructive; ask the user instead of tapping")
    print(f"OK: {len(taps)} tappable, {len(withheld)} withheld")


def verify(els: list[dict], x: int, y: int) -> int:
    """Is (x, y) a tap target this tree actually offered?

    The exploration loop must only tap coordinates that came out of
    `candidates`. Checking that here makes the rule mechanical instead of a
    line in a document an agent can drift past.
    """
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        candidates(els)
    for line in buf.getvalue().splitlines():
        if line.startswith("INFO: tap "):
            cx, cy = line.split()[2:4]
            if (int(cx), int(cy)) == (x, y):
                return 0
    for line in buf.getvalue().splitlines():
        if line.startswith("WARN: withheld ") and tuple(map(int, line.split()[2:4])) == (x, y):
            print(f"ERROR: {x},{y} is a WITHHELD target (destructive) — ask the user instead",
                  file=sys.stderr)
            return 1
    print(f"ERROR: {x},{y} is not a tap candidate of this screen — "
          "re-run `candidates` and pick from its INFO: tap lines", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("candidates", "sig", "nodekey") and len(argv) == 3:
        pass
    elif mode == "verify" and len(argv) == 5:
        pass
    else:
        print("ERROR: usage: device_a11y.py candidates|sig|nodekey <tree> "
              "| verify <tree> <x> <y>", file=sys.stderr)
        return 1
    try:
        els = load(argv[2])
    except (OSError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read accessibility tree {argv[2]}: {exc}", file=sys.stderr)
        return 1
    if mode == "verify":
        try:
            return verify(els, int(argv[3]), int(argv[4]))
        except ValueError:
            print("ERROR: verify needs integer <x> <y>", file=sys.stderr)
            return 1
    {"sig": sig, "nodekey": nodekey}.get(mode, candidates)(els)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
