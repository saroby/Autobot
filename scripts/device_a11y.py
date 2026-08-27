#!/usr/bin/env python3
"""device_a11y.py — accessibility-tree reader for /autobot:copy.

Single source of the exploration safety logic, shared by both drivers:

  - WebDriverAgent (real devices, via `device_wda.sh`)  → XML from GET /source
  - idb            (simulators, via `device_idb.sh`)    → JSON from `ui describe-all`

The format is auto-detected, normalized to one element shape, and then the same
guards apply to both. Modes:

  candidates <file>   Tappable elements with tap centers. State-changing labels
                      are withheld; a system dialog suppresses the list entirely.
                      When nothing reports an actionable role — a custom
                      renderer draws the whole screen as AXOther — it falls back
                      to label-leaf targets and says so with `WARN: role-blind
                      screen`. The label guards still apply in that tier, but an
                      unlabelled control is neither offered nor screened, so the
                      caller has to read the screen before tapping.
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
    # 충전: an in-app currency top-up is a purchase under another name. zeta's
    # 마이페이지 offers it as the screen's primary CTA next to a piece balance,
    # and none of the words below matched it (measured 2026-08-27).
    "삭제|제거|지우|비우기|구매|결제|구독|주문|충전|로그아웃|로그 아웃|사인아웃|탈퇴|"
    "초기화|재설정|복원|해지|신고|차단"
    "|delete|remove|erase|clear all|reset|buy|purchase|subscrib|checkout"
    "|top ?up|recharge"
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
    # 등록 is what a Korean creator tool calls Publish — zeta's plot editor ships
    # 등록 next to 임시저장, and neither word appears in the English vocabulary
    # below. Anchored, because 등록된 항목 / 등록 안내 are screens.
    ("publishing", re.compile(
        r"(?:^|\s)(?:게시|게시하기|포스트|등록|등록하기|출품)$"
        r"|^(?:post|publish|submit)(?:\s+(?:reply|thread|entry))?$", re.I)),
    # Saving a draft leaves data behind in the user's own account, which the
    # exploration contract forbids just as much as publishing does.
    ("persisting", re.compile(
        r"(?:^|\s)(?:저장|저장하기|임시저장|임시 저장)$"
        r"|^save(?:\s+(?:draft|changes))?$", re.I)),
    ("communication", re.compile(
        r"(?:^|\s)(?:보내기|전송)$|^send(?:\s+(?:message|reply|post|thread))?$", re.I)),
    # Leaving a room throws the conversation away — zeta offers 대화방 나가기 in
    # the chat menu and as a swipe action in the list, and no delete word
    # matches it. Anchored so 나가기 안내 (a screen) stays navigation.
    ("leaving", re.compile(
        r"(?:^|\s)나가기$|^(?:대화방|채팅방|그룹)\s*나가기$"
        r"|^leave(?:\s+(?:chat|room|group|conversation))?$", re.I)),
    ("recommendation", re.compile(
        r"추천\s*(?:숨기기|제거|무시|안\s*함)|관심\s*없음"
        r"|(?:hide|dismiss)\s+(?:this\s+)?(?:suggestion|recommendation)"
        r"|not interested", re.I)),
    # A control that quotes a price spends the user's money the moment it is
    # tapped, and no purchase word appears anywhere in it — zeta's illustration
    # button reads `스냅샷 15피스` and nothing else (measured 2026-08-27). The
    # signal is the price itself: a number bound to a currency or an in-app
    # token. A balance readout matches too, which costs a withheld target and
    # nothing more.
    ("spend", re.compile(
        r"\d[\d,.]*\s*(?:피스|코인|크레딧|캐시|젬|다이아|포인트|골드|루비)"
        r"|[₩$€£¥]\s*\d"
        r"|\d[\d,.]*\s*(?:coins?|credits?|gems?|tokens?|points?|pieces?|diamonds?)\b", re.I)),
    # Leaving for another app is currently detected AFTER the tap, by noticing a
    # foreign bundle in the foreground and re-activating the target. Detecting it
    # first is strictly better: the exit still costs a tap, a settle, a wasted
    # capture, and whatever the other app did on open (a deep link can act).
    # Korean particles attach to the preceding word with no space — the label is
    # `Instagram으로 전환`, not `Instagram 으로 전환` — so these must NOT be
    # anchored with \s before the particle.
    # `목록으로 전환` and `Switch to List` change the view, they do not leave the
    # app; naming the in-app destinations is narrower than trying to recognise
    # every brand on the other side.
    ("leaving-app", re.compile(
        r"^(?!.*(?:목록|리스트|캘린더|달력|그리드|지도|표|카드|갤러리)\s*(?:으로|로)\s*전환)"
        r"(?:.*(?:으로|로)\s*전환(?:하기)?$|.*에서\s*(?:열기|보기|계속)$)"
        r"|^(?:open|view|watch|listen|continue|switch)\s+(?:in|on|with|to)\s+"
        r"(?!list\b|calendar\b|grid\b|map\b|table\b|gallery\b|card\b)\S"
        r"|^(?:open in|open with)\b", re.I)),
    # Opening the system share sheet can send the post out of the app entirely,
    # and it replaces the target app in the foreground.
    # The Korean noun precedes the verb, so anchoring at ^ missed every real
    # button: zeta labels it 프로필 공유, not 공유. Allow a preceding noun, keep
    # the trailing anchor so 공유 설정 / 공유된 항목 (screens) stay navigation.
    ("sharing", re.compile(
        r"(?:^|\s)(?:공유|공유하기)$|^share(?:\s+(?:post|thread|profile|via.*))?$", re.I)),
    # A control whose label DESCRIBES its current on/off state is a toggle even
    # when its role is a plain button — Threads' post-notification bell reads
    # `알림이 비활성화되었습니다`. Measured 2026-08-23: exploration flipped it on
    # three people's posts, and the audit — which reads this same table — saw
    # nothing, because a hole in the guard is also a hole in the audit.
    ("state-toggle", re.compile(
        r"(?:비)?활성화(?:되었|됐|됨)"
        r"|알림\s*(?:끄기|켜기|받기)"
        r"|turn\s+(?:on|off)\s+notifications?"
        r"|notifications?\s+(?:are\s+)?(?:on|off|enabled|disabled)"
        r"|^(?:mute|unmute)$", re.I)),
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
    """idb `ui describe-all` — flat JSON array (legacy) or `--nested` tree.

    The nested form carries the same keys plus a `children` list per element.
    It is flattened depth-first so `depth`/`parent` line up with `_parse_wda`
    and the ancestor walks (`_ancestor_index`, alert detection) work on both
    drivers. A flat dump has no `children`, so every element lands at depth 0.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = [data]
    out = []
    stack = [(e, 0, -1) for e in reversed(data)]  # (element, depth, parent-index)
    while stack:
        e, depth, parent = stack.pop()
        if not isinstance(e, dict):
            continue
        index = len(out)
        for child in reversed(e.get("children") or []):
            stack.append((child, depth + 1, index))
        f = e.get("frame") if isinstance(e.get("frame"), dict) else {}
        out.append({
            "role": e.get("role") or e.get("type") or "?",
            "label": _clean(e.get("AXLabel")) or _clean(e.get("title")) or _clean(e.get("AXValue")),
            "enabled": e.get("enabled") is not False,
            "visible": None,  # idb does not report it — fall back to a bounds check
            "frame": {k: float(f.get(k, 0) or 0) for k in ("x", "y", "width", "height")},
            "depth": depth,
            "parent": parent,
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
    shape += _chrome_shape(els)
    digest = hashlib.sha1("\n".join(titles + shape).encode()).hexdigest()[:12]
    return digest, shape


# Short enough to be a nav item, a tab, or a filter chip; long enough to exclude
# a card's title, a message, or a feed row's summary. Category names sit right at
# the edge — `Electronics` is 11 — so the cap is not tight.
CHROME_LABEL_MAX = 12

# A number is a reading, not chrome: an unread badge going 9 → 10, a page
# indicator 12 / 80, a cart count. Hashing the value made the same screen a new
# screen. Dropping them outright was the other error — a subway app whose line
# tabs ARE 1/2/9 loses the only thing that distinguishes its screens. So they
# are normalised, not discarded: the fingerprint records that a numeric chip
# sits here, and how many, without the value.
COUNTER_LABEL = re.compile(r"^[\d\s./,:+%-]+$|^\d[\d,.]*[KkMm만천억]?$")


def _chrome_shape(els: list[dict]) -> list[str]:
    """A structural fallback for screens that report no structure.

    The shape above deliberately ignores AXOther, so a custom-rendered app has
    nothing left to hash — measured on zeta, its ranking and contest screens
    both produced sha1(""), and its home and creator tabs produced the same
    digest too. Everything downstream inherits that: statekey collapses, a real
    transition records `changed=false`, and coverage, resume and the flow graph
    merge screens that share nothing.

    What still separates those screens is their CHROME — the nav items, tabs and
    filter chips. Those are short, and they do not scroll away, which is the
    property that matters: hashing every label (what `sig` does) would make a
    feed a new node on every scroll. Measured across 57 captures of zeta, this
    yields 21 groups, each one a genuinely distinct screen, with the home feed's
    seven scroll positions collapsed into one.

    Only when roles explain almost nothing. Counting BUCKETS was not enough: the
    search screen reports two roles for a screen of fifteen unnamed chips, which
    read as "structured" and left it colliding with its own results page. What
    decides is how much of the labelled surface the roles actually account for.
    An app that reports roles keeps the identity it already had, so no existing
    graph or log is re-keyed.
    """
    leaves = _label_leaves(els)
    chrome, unnamed, named, counters = set(), 0, 0, 0
    for index, e in enumerate(els):
        label = (e["label"] or "").strip()
        if not leaves[index] or not label or e["visible"] is False:
            continue
        if e["role"] in CONTAINERS or NOISE.search(label):
            continue
        if _inside_keyboard(els, index) or _inside_modal(els, index):
            continue
        # Both sides of the ratio below must count the SAME population. Weighing
        # every role element — invisible ones, unlabelled ones — against only
        # the visible labelled leaves compared different things: two stray
        # AXStaticText against five AXOther turned the fallback off and merged
        # the screens it exists to separate.
        if e["role"] == "AXOther":
            unnamed += 1
        else:
            named += 1
        if len(label) <= CHROME_LABEL_MAX and "\n" not in label:
            if COUNTER_LABEL.match(label):
                counters += 1
            else:
                chrome.add(label)
    # A genuinely sparse screen (a spinner, an empty state) is not the same
    # thing as a custom-rendered one; without a crowd of unnamed boxes there is
    # nothing here worth disambiguating.
    # Measured across 57 real captures the two populations are cleanly bimodal
    # and never overlap: a custom-rendered screen carries 0-2 named leaves
    # against 13-18 unnamed, while a role-reporting one carries 6-30 named
    # against 0-3 unnamed. So "the unnamed outnumber the named" separates them
    # with room to spare. A ratio (roles must explain under a third) looked
    # stricter and was worse — two stray AXStaticText against five AXOther
    # turned the fallback off on exactly the screens it exists for.
    if unnamed < 5 or not chrome or unnamed <= named:
        return []
    if counters:
        chrome.add(f"#x{counters}")
    return ["chrome:" + hashlib.sha1("|".join(sorted(chrome)).encode()).hexdigest()[:12]]


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
    # A switch can be a local preference or a server-backed account setting, and
    # the accessibility tree cannot tell which. Keep it withheld by default.
    # Explicit probing is only for a target whose round-trip mutation is known to
    # be acceptable; the explore loop must still prove that the revert restored
    # the original state before it continues.
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


def _label_leaves(els: list[dict]) -> list[bool]:
    """Which elements own their label instead of inheriting it from below.

    A custom renderer nests plain `AXOther` boxes, and every ancestor repeats the
    concatenation of everything beneath it — measured on zeta's home screen, the
    window's label was the whole page ("콘테스트 홈 랭킹 퀴즈 … 크리에이터"). Tapping
    such an ancestor means tapping its centre, which is some unrelated child.
    The innermost element carrying a label is the one the user actually sees as
    a control, so that is the only element this tier will target.
    """
    inherited = [False] * len(els)
    for e in els:
        if not e["label"]:
            continue
        parent = e["parent"]
        # Stop at the first ancestor already marked — its own ancestors were
        # marked when that mark was set.
        while parent is not None and 0 <= parent < len(els) and not inherited[parent]:
            inherited[parent] = True
            parent = els[parent]["parent"]
    return [not flag for flag in inherited]


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


def _ancestors(els: list[dict], index: int) -> list[int]:
    """Every ancestor index of `els[index]`, nearest first (self excluded)."""
    out, parent, guard = [], els[index]["parent"], 0
    while parent is not None and 0 <= parent < len(els) and guard < len(els):
        out.append(parent)
        parent = els[parent]["parent"]
        guard += 1
    return out


def _candidate_meta(item: dict, withheld: bool) -> str:
    state_changing = str(item["classification"]["state_changing"]).lower()
    return (
        f"INFO: candidate-meta {item['x']} {item['y']}"
        f" | category={item['classification']['category']}"
        f" | effect={item['classification']['effect']}"
        f" | behavior={item['behavior']}"
        f" | source={item['source']}"
        f" | state_changing={state_changing} | withheld={str(withheld).lower()}"
    )


def _pick(els: list[dict], bw: float, bh: float, leaves: list[bool] | None) -> dict:
    """Collect tap targets, keyed so a control and its inner text collapse.

    `leaves` selects the tier. `None` is the role tier: an element qualifies only
    if its role or traits say it is actionable. A list (from `_label_leaves`) is
    the role-blind tier: an element also qualifies when it is the innermost owner
    of its label, ranked below every real role so the row-containment drop below
    still prefers the larger, real target.
    """
    picked = {}
    for index, e in enumerate(els):
        f, w, h = e["frame"], e["frame"]["width"], e["frame"]["height"]
        if not e["label"] or not e["enabled"] or e["role"] in CONTAINERS:
            continue
        if _inside_keyboard(els, index):
            continue
        rank = _action_rank(e)
        if (rank == 0 and leaves is not None and leaves[index]
                # Roles the vocabulary already knows keep their own verdict. A
                # bare AXStaticText is inert on purpose — an empty state's "입력
                # 항목 없음" is not a control, and promoting it here would hand the
                # loop a dead target on every screen that has nothing to tap.
                # Only a role the vocabulary cannot speak for gets the benefit.
                and e["role"] not in ROLE_RANK and e["role"] not in ACTIONABLE_ROLES
                # A leaf that covers the screen is a backdrop, not a control, and
                # its centre belongs to whatever it sits behind. Across 39
                # captured zeta screens the largest real target was a feed card
                # at 16% of the frame, so this only ever catches backgrounds.
                and not (bw and bh and w * h >= bw * bh * 0.8)):
            rank = 1
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
            picked[key] = (rank, cx, cy, e["role"], e["label"], w * h, f, index,
                           rank == 1)
    return picked


def candidates(els: list[dict]) -> None:
    # An alert, or anything speaking the system-consent vocabulary, suppresses
    # the list outright — "Allow" must never be reachable by a blind tap.
    hard = [
        e for e in els
        if "alert" in e["role"].lower() or SYSTEM_DIALOG.match(e["label"])
    ]
    # A SHEET is different and used to be lumped in with alerts, which
    # contradicted the contract's own escape hatch: suppressing everything
    # removes the plain 취소/Cancel that closes it, so the loop is stuck inside a
    # sheet it is not allowed to touch. An app's own action sheet is ordinary UI
    # whose dangerous entries are withheld by label like anywhere else. Keep the
    # blind loop out of it, but leave the way out.
    sheet = [e for e in els if "sheet" in e["role"].lower()] if not hard else []
    if hard:
        hit = hard[0]
        print(f"WARN: alert/sheet on screen ({hit['label'] or hit['role']}) — a system or "
              "destructive dialog is up; stop and hand back to the user")
        print("OK: 0 tappable, 0 withheld")
        return

    bounds = next((e["frame"] for e in els if e["role"] == "AXApplication"), {})
    bw, bh = bounds.get("width", 0), bounds.get("height", 0)

    if sheet:
        # Descendants of THIS sheet only. Scanning the whole tree offered a
        # 취소 that belonged to the screen behind the sheet — a coordinate under
        # the sheet, so the tap would land on the sheet anyway, at a spot nobody
        # chose.
        sheet_indexes = {id(e) for e in sheet}
        inside = [i for i, e in enumerate(els)
                  if any(id(els[a]) in sheet_indexes for a in _ancestors(els, i))]
        if not inside:
            # A flat idb dump has no parents to walk — every element is depth 0,
            # so ancestry finds nothing and the sheet would offer no way out at
            # all. Fall back to the sheet's frame.
            frame = sheet[0]["frame"]
            inside = [i for i, e in enumerate(els)
                      if e["frame"]["width"] > 0 and e["frame"]["height"] > 0
                      and frame["x"] <= e["frame"]["x"] + e["frame"]["width"] / 2
                      <= frame["x"] + frame["width"]
                      and frame["y"] <= e["frame"]["y"] + e["frame"]["height"] / 2
                      <= frame["y"] + frame["height"]]
        escapes = [els[i] for i in inside
                   if ESCAPE_LABEL.match((els[i]["label"] or "").strip())
                   and els[i]["visible"] is not False and els[i]["enabled"]
                   and els[i]["frame"]["width"] > 0 and els[i]["frame"]["height"] > 0]
        print(f"WARN: sheet on screen ({sheet[0]['label'] or sheet[0]['role']}) — "
              "only the way out is offered; open it again yourself if you need what is inside")
        for e in escapes:
            f = e["frame"]
            cx = int(f["x"] + f["width"] / 2)
            cy = int(f["y"] + f["height"] / 2)
            print(f"INFO: tap {cx} {cy} | {e['role']} | {e['label']}")
            print(f"INFO: candidate-meta {cx} {cy} | category=navigation | effect=none"
                  f" | behavior=sheet-escape | source=escape"
                  f" | state_changing=false | withheld=false")
        print(f"OK: {len(escapes)} tappable, 0 withheld")
        return

    # A custom-rendered app reports no roles at all, so a role-only pass finds
    # nothing and the loop stops on a screen that is perfectly safe to explore.
    # Measured on zeta 3.47.0: 144 elements, 60 labelled, every one of them
    # `XCUIElementTypeOther` with no traits — 0 candidates, including the tab bar.
    # That is the guard misfiring on missing metadata, not refusing a risk.
    #
    # The tier is NOT all-or-nothing per screen. Deciding it by "did the role
    # pass find anything" made one lucky element hide the rest: zeta's search
    # screen reports exactly one AXTextField, which counted as success and left
    # all 15 tag chips invisible. Measured across 39 captured screens, merging
    # the two costs nothing where roles are good (the chat room adds 0) and
    # recovers real controls everywhere else (a `더보기` menu, three model cards,
    # those 15 chips). So label leaves are always offered, ranked below every
    # real role.
    role_only = _pick(els, bw, bh, None)
    picked = _pick(els, bw, bh, _label_leaves(els))
    if not role_only and picked:
        # Worth saying out loud: with no role anywhere, EVERY target here came
        # from a label. The classification below still runs on each one, but a
        # control with no label is neither offered nor screened, so the caller
        # has to read the screen instead of trusting the list.
        print("WARN: role-blind screen — no element reports an actionable role; "
              "every target below came from a label. Weaker guard: unlabelled controls "
              "are not offered and not screened. Read the screen before tapping.")

    # A list row and each line of text inside it are separate elements with
    # DIFFERENT labels, so the same-label collapse above cannot merge them —
    # a real Journal screen produced 31 "targets" for ~6 real ones. Tapping the
    # row is what navigates, so inert text/images sitting inside a bigger
    # candidate are dropped. Actionable roles are never dropped: a button inside
    # a row (e.g. "새로운 일기") is its own target.
    # Label leaves are exempt. This drop reads "an inert thing inside a bigger
    # target is not its own target", and it identifies inert by `rank < 2` — a
    # rank `_action_rank` never returns (it yields 0, 2 or 3; the Journal screen's
    # inert text is removed by the rank-0 filter above, not here). So for role
    # candidates this branch cannot fire, and the only thing that reaches it is a
    # promoted leaf, which is the opposite of inert. Applying it there ate real
    # controls purely because scrollable content passes under sticky chrome: a
    # feed card swallowed 홈/대화/만들기/마이페이지 from behind the tab bar, and a
    # card scrolled off the top swallowed 추천/스토리챗/비주얼 노벨. Containment
    # cannot tell "inside" from "behind", so leaves do not answer to it.
    kept = []
    for c in sorted(picked.values(), key=lambda c: -c[5]):
        rank, cx, cy, _role, _lab, area, _f, _index, from_leaf = c
        if not from_leaf and rank < 2 and any(
            area < k[5]
            and k[6]["x"] <= cx <= k[6]["x"] + k[6]["width"]
            and k[6]["y"] <= cy <= k[6]["y"] + k[6]["height"]
            for k in kept
        ):
            continue
        kept.append(c)

    taps, withheld = [], []
    for _, cx, cy, role, lab, _area, _f, index, _leaf in sorted(kept, key=lambda c: (c[2], c[1])):
        classification = _classification(els[index])
        # `source` is per-candidate on purpose. The screen-level role-blind
        # warning only fires when NOTHING reported a role, so on a mixed screen
        # a label-derived target was indistinguishable from one a role vouched
        # for — and the "read the screen before tapping" rule had nothing to key
        # on. A `label` source means: this control was never classified by
        # anything but its own words.
        item = {"x": cx, "y": cy, "role": role, "label": lab,
                "classification": classification,
                "source": "label" if _leaf else "role",
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


# The way out of a sheet, and NOTHING else. 확인/완료/OK/Done were here and had
# to go: on a sheet those commit — a form saves, a selection applies, a purchase
# confirms. Only words that mean "leave without doing it" belong.
ESCAPE_LABEL = re.compile(r"^(취소|닫기|뒤로)$|^(cancel|close|dismiss|back)$", re.I)


BACK_LABEL = re.compile(r"^(뒤로|뒤로 가기|돌아가기|닫기|취소)$|^(back|go back|close|cancel|done)$", re.I)


def back(els: list[dict]) -> None:
    """The nav bar's leading control, even when it carries no label.

    Every other tap must come from a labelled candidate, and that rule holds:
    a control the tree will not name cannot be screened, so it is not offered.
    The one exception is getting OUT. A detail screen whose back chevron is an
    unlabelled glyph — zeta's creator profile, its search screen — has no
    candidate at all and no tab bar, and the interactive pop gesture does
    nothing there, so exploration dead-ends on a screen it walked into itself
    (measured 2026-08-27, three times in one session).

    This is safe to make an exception for because the slot's meaning is a
    platform convention, not app-specific: the leading edge of the top bar is
    back / close / cancel. It is never a purchase and never a delete. It stays
    a deliberate command rather than a candidate, so nothing taps it by
    accident — the loop asks for it only when it is stuck.
    """
    bounds = next((e["frame"] for e in els if e["role"] == "AXApplication"), None)
    if not bounds or not bounds["width"] or not bounds["height"]:
        print("ERROR: no application frame — cannot locate the nav bar", file=sys.stderr)
        return
    bx, by, bw, bh = bounds["x"], bounds["y"], bounds["width"], bounds["height"]
    hits = []
    for e in els:
        f, w, h = e["frame"], e["frame"]["width"], e["frame"]["height"]
        if w <= 0 or h <= 0 or e["visible"] is False or not e["enabled"]:
            continue
        if e["role"] in CONTAINERS:
            continue
        # A named control is already a candidate and answers to the label guards.
        if e["label"] and not BACK_LABEL.match(e["label"].strip()):
            continue
        cx, cy = f["x"] + w / 2, f["y"] + h / 2
        if not (bx <= cx <= bx + bw * 0.18):
            continue
        # Below the status bar, inside the nav bar.
        if not (by + bh * 0.045 <= cy <= by + bh * 0.16):
            continue
        # A chevron, not a title or a segmented control.
        if w > bw * 0.2 or h > bh * 0.09:
            continue
        hits.append((cy, cx, int(cx), int(cy), e["label"], e["role"]))
    if not hits:
        print("INFO: back 0 — no leading nav control on this screen")
        return
    hits.sort()
    _, _, x, y, label, role = hits[0]
    print(f"INFO: back {x} {y} | {role} | {label or '(unlabelled)'}")
    print(f"OK: 1 back target")


SEARCH_FIELD = re.compile(
    r"검색|찾기|조회|search|find|query|lookup|filter", re.I)


def inputs(els: list[dict]) -> None:
    """Text fields that could be typed into, with the id to type by.

    Exploration never typed, so every search screen was a dead end: the
    results screen behind it can only be reached through the keyboard. The
    choice of what to type belongs to the caller — this only says where.

    Each field is classified `search` or `other`, and that is not cosmetic.
    Typing commits with Return, and Return in a composer SENDS — which walks
    straight around the `communication` guard that withholds the Send button
    itself. A message box, a comment box and a profile field are all just
    "the first text field on screen" to a blind probe. Only a field that says
    it searches is safe to type into unattended.
    """
    found = safe = 0
    for e in els:
        if e["role"] not in TEXT_INPUT_ROLES or e["visible"] is False or not e["enabled"]:
            continue
        if e["frame"]["width"] <= 0 or e["frame"]["height"] <= 0:
            continue
        name = e.get("name") or ""
        if not name:
            continue
        # The role is the strongest signal; the id and the placeholder are what
        # a custom search box has instead of one.
        kind = ("search" if e["role"] == "AXSearchField"
                or SEARCH_FIELD.search(name)
                or SEARCH_FIELD.search(e.get("label") or "")
                or SEARCH_FIELD.search(e.get("value") or "")
                else "other")
        found += 1
        safe += kind == "search"
        print(f"INFO: input {name}\t{e['role']}\t{int(e['frame']['x'] + e['frame']['width'] / 2)}"
              f"\t{int(e['frame']['y'] + e['frame']['height'] / 2)}\t{kind}")
    print(f"INFO: inputs {found} ({safe} search)")


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode in ("candidates", "sig", "nodekey", "statekey", "identity", "inputs", "back") and len(argv) == 3:
        pass
    elif mode == "verify" and len(argv) == 5:
        pass
    else:
        print("ERROR: usage: device_a11y.py candidates|sig|nodekey|statekey|identity|inputs|back <tree> "
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
    {"sig": sig, "nodekey": nodekey, "statekey": statekey, "inputs": inputs,
     "back": back}.get(mode, candidates)(els)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
