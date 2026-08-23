#!/usr/bin/env python3
"""device_a11y.py — accessibility-tree reader for /autobot:copy.

Single source of the exploration safety logic, shared by both drivers:

  - WebDriverAgent (real devices, via `device_wda.sh`)  → XML from GET /source
  - idb            (simulators, via `device_idb.sh`)    → JSON from `ui describe-all`

The format is auto-detected, normalized to one element shape, and then the same
guards apply to both. Modes:

  candidates <file>   Tappable elements with tap centers. State-changing labels
                      are withheld; a system dialog suppresses the list entirely.
  sig <file>          Screen signature (hash of the label set) — the exploration
                      loop's termination primitive.
  nodekey <file>      Coarse structural identity for screens.
  statekey <file>     Interaction-state identity layered on top of nodekey.

Output follows CONVENTIONS.md prefixes (OK:/INFO:/WARN:/ERROR:).
"""

from __future__ import annotations

import hashlib
import json
import os
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

TEXT_INPUT_ROLES = {"AXTextField", "AXTextArea", "AXSearchField", "AXSecureTextField"}
ACTIONABLE_ROLES = {
    "AXButton", "AXCell", "AXLink", "AXSwitch", "AXSlider", "AXSegment",
    "AXRadioButton", "AXCheckBox", "AXMenuItem", "AXDisclosureTriangle",
    *TEXT_INPUT_ROLES,
}
ACTIONABLE_TRAITS = re.compile(
    r"\b(button|link|adjustable|switch|toggle|text\s*field|search\s*field)\b", re.I
)

# Blind exploration must not mutate the user's account or publish content. Keep
# these categories narrower than ordinary navigation labels: "팔로우 추천" and
# "Follow suggestions" are screens, while "팔로우" and "Follow all" are actions.
STATE_CHANGING = (
    ("social-follow", re.compile(
        r"(?:^|\s)(?:모두\s+)?(?:언)?팔로우(?:\s*(?:취소|해제))?$"
        r"|^(?:follow|unfollow)(?:\s+(?!suggestions?\b|recommendations?\b).+)?$"
        r"|^following$", re.I)),
    ("social-like", re.compile(
        r"(?:^|\s)좋아요(?:\s*(?:취소|해제))?$"
        r"|^(?:like|unlike)(?:\s+(?:post|thread|reply))?$", re.I)),
    ("social-repost", re.compile(
        r"(?:^|\s)(?:리포스트|재게시)(?:\s*(?:취소|삭제))?$"
        r"|^(?:repost|undo repost)(?:\s+(?:post|thread))?$", re.I)),
    ("publishing", re.compile(
        r"(?:^|\s)(?:게시|게시하기|포스트)$|^(?:post|publish)(?:\s+(?:reply|thread))?$", re.I)),
    ("communication", re.compile(
        r"(?:^|\s)(?:보내기|전송)$|^send(?:\s+(?:message|reply|post|thread))?$", re.I)),
    ("recommendation", re.compile(
        r"추천\s*(?:숨기기|제거|무시|안\s*함)|관심\s*없음"
        r"|(?:hide|dismiss)\s+(?:this\s+)?(?:suggestion|recommendation)"
        r"|not interested", re.I)),
    # Opening the system share sheet can send the post out of the app entirely,
    # and it replaces the target app in the foreground.
    ("sharing", re.compile(
        r"^(?:공유|공유하기)$|^share(?:\s+(?:post|thread|via.*))?$", re.I)),
)


def _label_clauses(label: str) -> tuple[str, ...]:
    """The label, plus its leading clause.

    Real accessibility labels name the action and then describe it:
    Threads writes `좋아요. 226명이 이 게시물을 좋아합니다.` for its like button,
    not `좋아요`. The patterns above are anchored at the end on purpose — that is
    what keeps `팔로우 추천` (a screen) from reading as `팔로우` (an action) — so
    matching the whole label alone let every one of those buttons through.
    Measured on a real device 2026-08-22: exploration tapped like and share on
    another person's post. Checking the leading clause too keeps the precision
    and closes the hole.
    """
    head = re.split(r"[.。!?\n]", label, maxsplit=1)[0].strip()
    return (label,) if head == label or not head else (label, head)


def _clean(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    return None


def _traits(value: object) -> list[str]:
    """Normalize traits without requiring newer fields in old fixtures."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                return _traits(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in re.split(r"[,|]", raw) if item.strip()]
    return [str(value)]


def _first(mapping: dict, *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


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
                "accessible": _optional_bool(node.get("accessible")),
                "traits": _traits(node.get("traits") or node.get("accessibilityTraits")),
                "focused": _optional_bool(node.get("focused")),
                "selected": _optional_bool(node.get("selected")),
                # The accessibility id, kept apart from the label: it is what
                # Appium's `accessibility id` locator matches, and it is how a
                # text field can be typed into without guessing coordinates.
                "name": _clean(node.get("name")),
                # A switch's on/off lives here, not in the label.
                "value": _clean(node.get("value")),
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
            "depth": e.get("depth") if isinstance(e.get("depth"), int) else None,
            "parent": e.get("parent") if isinstance(e.get("parent"), int) else -1,
            "accessible": _optional_bool(_first(
                e, "accessible", "AXAccessible", "isAccessibilityElement",
                "is_accessibility_element")),
            "traits": _traits(_first(e, "AXTraits", "traits", "accessibilityTraits")),
            "focused": _optional_bool(_first(e, "AXFocused", "focused")),
            "selected": _optional_bool(_first(e, "AXSelected", "selected")),
            "name": _clean(_first(e, "AXUniqueId", "identifier", "name")),
            "value": _clean(_first(e, "AXValue", "value")),
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


def _node_identity(els: list[dict]) -> tuple[str, list[str]]:
    counts = Counter(e["role"] for index, e in enumerate(els)
                     if e["frame"]["width"] > 0
                     and e["role"] not in CONTAINERS
                     and e["role"] not in ("AXOther", "AXKey")
                     and e["role"] != "AXCell"
                     and _data_cell_index(els, index) is None
                     and not _inside_keyboard(els, index)
                     and not _inside_modal(els, index))
    shape = [f"{role}:{_bucket(n)}" for role, n in sorted(counts.items())]
    if any(e["role"] == "AXCell" and e["frame"]["width"] > 0
           and _is_data_cell(els, index) for index, e in enumerate(els)):
        shape.append("AXCell:present")
    titles = sorted({e["label"] for index, e in enumerate(els)
                     if e["label"]
                     and (e["role"] in ("AXNavigationBar", "AXTabBar")
                          or any(trait.casefold() in ("header", "heading")
                                 for trait in e.get("traits", [])))
                     and _data_cell_index(els, index) is None
                     and not _inside_keyboard(els, index)
                     and not _inside_modal(els, index)})
    digest = hashlib.sha1("\n".join(titles + shape).encode()).hexdigest()[:12]
    return digest, shape


def nodekey(els: list[dict]) -> None:
    """Structural screen identity — the coarse node key for the flow graph.

    `sig` hashes the label set, which is wrong for a graph: the same list with
    different data, or scrolled by one row, would be a new node and the
    exploration queue would never drain. It is wrong for the tap guard too, for
    the same reason — measured on Threads, a like count ticking 226 -> 227
    changed `sig` while the screen stood still, so the guard rejected every
    candidate and exploration made 0 steps. The guard uses `statekey`.
    This hashes structure instead — role counts plus the
    navigation bar or custom Header trait label, which names the screen rather
    than its row data. Apps such as Threads draw their own top bar without an
    AXNavigationBar container, so omitting Header landmarks merges unrelated
    screens that happen to have the same role counts.
    """
    # Containers and keyboard keys are excluded: they are plumbing, not identity.
    # The same empty-list screen was captured twice minutes apart and split into
    # two nodes because one dump carried an AXToolbar wrapper and the other put
    # the same button under an AXOther — a graph that doubles its nodes on
    # wrapper churn cannot report coverage.
    digest, shape = _node_identity(els)
    print(f"INFO: nodekey {digest}")
    print(f"INFO: shape {' '.join(shape)}")


def _ancestor_index(els: list[dict], index: int, roles: set[str]) -> int | None:
    seen = set()
    parent = els[index].get("parent", -1)
    while isinstance(parent, int) and 0 <= parent < len(els) and parent not in seen:
        if els[parent]["role"] in roles:
            return parent
        seen.add(parent)
        parent = els[parent].get("parent", -1)
    return None


def _is_data_cell(els: list[dict], index: int) -> bool:
    """Distinguish a list row from an app's full-screen collection wrapper."""
    if not (0 <= index < len(els)) or els[index]["role"] != "AXCell":
        return False
    frame = els[index]["frame"]
    viewport = max(
        (e["frame"] for e in els
         if e["role"] in ("AXApplication", "AXWindow")
         and e["frame"]["width"] > 0 and e["frame"]["height"] > 0),
        key=lambda item: item["width"] * item["height"],
        default=None,
    )
    if viewport and frame["width"] >= viewport["width"] * 0.9 \
            and frame["height"] >= viewport["height"] * 0.75:
        return False
    return frame["width"] > 0 and frame["height"] > 0


def _data_cell_index(els: list[dict], index: int) -> int | None:
    cell = _ancestor_index(els, index, {"AXCell"})
    return cell if cell is not None and _is_data_cell(els, cell) else None


def _inside_keyboard(els: list[dict], index: int) -> bool:
    e = els[index]
    traits = " ".join(e.get("traits", []))
    if (e["role"] == "AXKey" or re.search(r"\bkeyboard\s*key\b", traits, re.I)
            or _ancestor_index(els, index, {"AXKeyboard"}) is not None):
        return True
    # idb is usually flat. When it still reports the keyboard container, use
    # geometry to suppress its descendants without pretending hierarchy exists.
    f = e["frame"]
    cx, cy = f["x"] + f["width"] / 2, f["y"] + f["height"] / 2
    return any(
        i != index and keyboard["role"] == "AXKeyboard"
        and keyboard["frame"]["width"] > 0 and keyboard["frame"]["height"] > 0
        and keyboard["frame"]["x"] <= cx <= keyboard["frame"]["x"] + keyboard["frame"]["width"]
        and keyboard["frame"]["y"] <= cy <= keyboard["frame"]["y"] + keyboard["frame"]["height"]
        for i, keyboard in enumerate(els)
    )


def _inside_modal(els: list[dict], index: int) -> bool:
    role = els[index]["role"].lower()
    if "alert" in role or "sheet" in role:
        return True
    parent = els[index].get("parent", -1)
    seen = set()
    while isinstance(parent, int) and 0 <= parent < len(els) and parent not in seen:
        parent_role = els[parent]["role"].lower()
        if "alert" in parent_role or "sheet" in parent_role:
            return True
        seen.add(parent)
        parent = els[parent].get("parent", -1)
    return False


def _normalized_label(label: str) -> str:
    value = label.casefold().strip()
    value = re.sub(r"https?://\S+|@[\w.]+", "<data>", value)
    value = re.sub(r"\d+(?:[.,:]\d+)*", "#", value)
    return re.sub(r"\s+", " ", value)


def _state_control_id(els: list[dict], index: int) -> str:
    e = els[index]
    row = (index if e["role"] == "AXCell" and _is_data_cell(els, index)
           else _data_cell_index(els, index))
    if row is not None:
        return f"row:{e['role']}"
    f = e["frame"]
    return f"{e['role']}@{int(f['x']) // 44}:{int(f['y']) // 44}"


def statekey(els: list[dict]) -> None:
    """Interaction identity: coarse node plus keyboard/focus/selection/modal state."""
    node, _shape = _node_identity(els)
    tokens = []
    keyboard_visible = any(
        e["role"] in ("AXKeyboard", "AXKey") and e["visible"] is not False
        and e["frame"]["width"] > 0 and e["frame"]["height"] > 0
        for e in els
    )
    if keyboard_visible:
        tokens.append("keyboard")
    for index, e in enumerate(els):
        if e.get("focused") is True:
            tokens.append("focus:" + _state_control_id(els, index))
        if e.get("selected") is True:
            parent_is_tab = _ancestor_index(els, index, {"AXTabBar", "AXNavigationBar"}) is not None
            identity = _normalized_label(e["label"]) if parent_is_tab else _state_control_id(els, index)
            tokens.append("selected:" + identity)
        if "alert" in e["role"].lower() or "sheet" in e["role"].lower() or SYSTEM_DIALOG.match(e["label"]):
            tokens.append("modal:" + e["role"])
        # On/off is interaction state: the probe below flips a switch and must
        # see a different statekey, or the toggle records as a no-op tap.
        if e["role"] == "AXSwitch" and e.get("value"):
            tokens.append(f"switch:{_normalized_label(e['label'])}={e['value']}")
    state = hashlib.sha1("\n".join([node] + sorted(set(tokens))).encode()).hexdigest()[:12]
    print(f"INFO: statekey {state}")
    print(f"INFO: state {' '.join(sorted(set(tokens))) or 'base'}")


def _classification(e: dict) -> dict:
    label = e["label"]
    clauses = _label_clauses(label)
    if DESTRUCTIVE.search(label):
        return {"category": "state-changing", "effect": "destructive", "state_changing": True}
    for effect, pattern in STATE_CHANGING:
        if any(pattern.search(clause) for clause in clauses):
            return {"category": "state-changing", "effect": effect, "state_changing": True}
    # A switch flips and flips back, so with CLONE_PROBE_SWITCHES=1 the explore
    # loop taps it, captures the flipped state, and taps it again in the same
    # step. Off by default: the tree cannot tell a local toggle from an account
    # setting (Threads' "비공개 프로필" is a Switch), and this repo's bar is no
    # account write at all, net-zero included. Labels that reach the server were
    # caught above and stay withheld whatever the role or the flag.
    if e["role"] == "AXSwitch":
        if os.environ.get("CLONE_PROBE_SWITCHES") == "1":
            return {"category": "reversible", "effect": "toggle", "state_changing": False}
        return {"category": "state-changing", "effect": "toggle", "state_changing": True}
    if e["role"] in TEXT_INPUT_ROLES:
        return {"category": "input", "effect": "none", "state_changing": False}
    return {"category": "navigation", "effect": "none", "state_changing": False}


def _action_rank(e: dict) -> int:
    traits = " ".join(e.get("traits", []))
    if e["role"] == "AXStaticText":
        return 2 if ACTIONABLE_TRAITS.search(traits) else 0
    if e["role"] in ROLE_RANK:
        return ROLE_RANK[e["role"]]
    if e["role"] in ACTIONABLE_ROLES or ACTIONABLE_TRAITS.search(traits):
        return 2
    return 0


def _behavior_fingerprint(els: list[dict], index: int, classification: dict) -> str:
    e = els[index]
    row = (index if e["role"] == "AXCell" and _is_data_cell(els, index)
           else _data_cell_index(els, index))
    if classification["effect"] == "toggle":
        # Row-control grouping would make every switch in a settings list one
        # behavior and probe only the first. Each switch is its own setting.
        subject = "toggle:" + _normalized_label(e["label"])
    elif classification["effect"] != "none":
        subject = classification["effect"]
    elif row is not None and e["role"] == "AXCell":
        subject = "row-item"
    elif row is not None:
        row_frame, frame = els[row]["frame"], e["frame"]
        width, height = max(row_frame["width"], 1), max(row_frame["height"], 1)
        relative_x = (frame["x"] + frame["width"] / 2 - row_frame["x"]) / width
        relative_y = (frame["y"] + frame["height"] / 2 - row_frame["y"]) / height
        column = max(0, min(4, int(relative_x * 5)))
        band = max(0, min(2, int(relative_y * 3)))
        subject = f"row-control:{column}:{band}"
    else:
        subject = _normalized_label(e["label"])
    source = "|".join((e["role"], classification["category"], subject))
    return hashlib.sha1(source.encode()).hexdigest()[:12]


def _candidate_meta(item: dict, withheld: bool) -> str:
    state_changing = str(item["classification"]["state_changing"]).lower()
    return (
        f"INFO: candidate-meta {item['x']} {item['y']}"
        f" | category={item['classification']['category']}"
        f" | effect={item['classification']['effect']}"
        f" | behavior={item['behavior']}"
        f" | state_changing={state_changing} | withheld={str(withheld).lower()}"
    )


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
    for index, e in enumerate(els):
        f, w, h = e["frame"], e["frame"]["width"], e["frame"]["height"]
        if not e["label"] or not e["enabled"] or e["role"] in CONTAINERS:
            continue
        if _inside_keyboard(els, index):
            continue
        rank = _action_rank(e)
        if rank == 0:
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
        if key not in picked or rank > picked[key][0]:
            picked[key] = (rank, cx, cy, e["role"], e["label"], w * h, f, index)

    # A list row and each line of text inside it are separate elements with
    # DIFFERENT labels, so the same-label collapse above cannot merge them —
    # a real Journal screen produced 31 "targets" for ~6 real ones. Tapping the
    # row is what navigates, so inert text/images sitting inside a bigger
    # candidate are dropped. Actionable roles are never dropped: a button inside
    # a row (e.g. "새로운 일기") is its own target.
    kept = []
    for c in sorted(picked.values(), key=lambda c: -c[5]):
        rank, cx, cy, _role, _lab, area, _f, _index = c
        if rank < 2 and any(
            area < k[5]
            and k[6]["x"] <= cx <= k[6]["x"] + k[6]["width"]
            and k[6]["y"] <= cy <= k[6]["y"] + k[6]["height"]
            for k in kept
        ):
            continue
        kept.append(c)

    taps, withheld = [], []
    for _, cx, cy, role, lab, _area, _f, index in sorted(kept, key=lambda c: (c[2], c[1])):
        classification = _classification(els[index])
        item = {"x": cx, "y": cy, "role": role, "label": lab,
                "classification": classification,
                "behavior": _behavior_fingerprint(els, index, classification)}
        (withheld if classification["state_changing"] else taps).append(item)

    for item in taps:
        print(f"INFO: tap {item['x']} {item['y']} | {item['role']} | {item['label']}")
        print(_candidate_meta(item, False))
    for item in withheld:
        reason = ("destructive" if item["classification"]["effect"] == "destructive"
                  else f"state-changing/{item['classification']['effect']}")
        print(f"WARN: withheld {item['x']} {item['y']} | {item['role']} | {item['label']}"
              f" — {reason}; ask the user instead of tapping")
        print(_candidate_meta(item, True))
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
            print(f"ERROR: {x},{y} is a WITHHELD target (state-changing) — ask the user instead",
                  file=sys.stderr)
            return 1
    print(f"ERROR: {x},{y} is not a tap candidate of this screen — "
          "re-run `candidates` and pick from its INFO: tap lines", file=sys.stderr)
    return 1


def inputs(els: list[dict]) -> None:
    """Text fields that could be typed into, with the id to type by.

    Exploration never typed, so every search screen was a dead end: the
    results screen behind it can only be reached through the keyboard. The
    choice of what to type belongs to the caller — this only says where.
    """
    found = 0
    for e in els:
        if e["role"] not in TEXT_INPUT_ROLES or e["visible"] is False or not e["enabled"]:
            continue
        if e["frame"]["width"] <= 0 or e["frame"]["height"] <= 0:
            continue
        name = e.get("name") or ""
        if not name:
            continue
        found += 1
        print(f"INFO: input {name}\t{e['role']}\t{int(e['frame']['x'] + e['frame']['width'] / 2)}"
              f"\t{int(e['frame']['y'] + e['frame']['height'] / 2)}")
    print(f"INFO: inputs {found}")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("candidates", "sig", "nodekey", "statekey", "identity", "inputs") and len(argv) == 3:
        pass
    elif mode == "verify" and len(argv) == 5:
        pass
    else:
        print("ERROR: usage: device_a11y.py candidates|sig|nodekey|statekey|identity|inputs <tree> "
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
    if mode == "identity":
        # All three in one parse. The settle loop asked for sig and statekey in
        # two separate processes per poll — two interpreter starts and two XML
        # parses for one dump — and it polls up to ten times per tap.
        sig(els)
        nodekey(els)
        statekey(els)
        return 0
    {"sig": sig, "nodekey": nodekey, "statekey": statekey, "inputs": inputs}.get(mode, candidates)(els)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
