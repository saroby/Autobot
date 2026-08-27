"""device_a11y.py — tap-candidate safety and screen signatures, offline.

Both driver formats are covered: WebDriverAgent XML (real devices) and idb JSON
(simulators). The fixtures below are shaped after real captures taken on
2026-07-25 — a live Journal app tree over WDA and a live ATT prompt over idb —
not from guesses about the schema. That distinction matters: the first version
of the modal guard was written against an assumed shape and the real ATT tree
walked straight through it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_a11y.py"
SPEC = importlib.util.spec_from_file_location("device_a11y_under_test", SCRIPT)
DEVICE_A11Y = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DEVICE_A11Y)


def run(mode: str, body: str, suffix: str) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(body)
        fixture = f.name
    try:
        env = os.environ.copy()
        env.pop("CLONE_PROBE_SWITCHES", None)
        return subprocess.run(
            ["python3", str(SCRIPT), mode, fixture],
            capture_output=True, text=True,
            env=env,
        )
    finally:
        Path(fixture).unlink()


def idb(elements: list[dict], mode: str = "candidates") -> subprocess.CompletedProcess:
    return run(mode, json.dumps(elements), ".json")


def idb_probing(elements: list[dict]) -> subprocess.CompletedProcess:
    """`candidates` with explicit switch probing enabled."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write(json.dumps(elements))
        fixture = f.name
    try:
        return subprocess.run(["python3", str(SCRIPT), "candidates", fixture],
                              capture_output=True, text=True,
                              env={**os.environ, "CLONE_PROBE_SWITCHES": "1"})
    finally:
        Path(fixture).unlink()


def wda(inner: str, mode: str = "candidates") -> subprocess.CompletedProcess:
    """Wrap elements in the application root WDA always reports."""
    return run(mode, (
        '<?xml version="1.0" encoding="UTF-8"?>\n<AppiumAUT>'
        '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
        ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
        f'{inner}</XCUIElementTypeApplication></AppiumAUT>'
    ), ".xml")


def el(label: str, x: int, y: int, w: int = 100, h: int = 40, **kw) -> dict:
    return {
        "AXLabel": label,
        "role": kw.pop("role", "AXButton"),
        "enabled": kw.pop("enabled", True),
        "frame": {"x": x, "y": y, "width": w, "height": h},
        **kw,
    }


ROOT = el("App", 0, 0, 393, 852, role="AXApplication")


def node(kind: str, label: str, x: int, y: int, w: int = 100, h: int = 40,
         visible: str = "true", **metadata) -> str:
    attrs = "".join(
        f' {key}="{str(value).lower() if isinstance(value, bool) else value}"'
        for key, value in metadata.items()
    )
    return (f'<XCUIElementType{kind} type="XCUIElementType{kind}" label="{label}" name="{label}"'
            f' enabled="true" visible="{visible}" x="{x}" y="{y}" width="{w}" height="{h}"'
            f'{attrs}/>')


class TestActionabilityMetadata(unittest.TestCase):
    def test_wda_retains_optional_metadata(self):
        parsed = DEVICE_A11Y._parse_wda(
            '<AppiumAUT>'
            + node("StaticText", "Custom action", 10, 20, accessible=True,
                   traits="Button, Selected", focused=False, selected=True)
            + '</AppiumAUT>'
        )
        action = next(e for e in parsed if e["label"] == "Custom action")
        self.assertTrue(action["accessible"])
        self.assertEqual(action["traits"], ["Button", "Selected"])
        self.assertFalse(action["focused"])
        self.assertTrue(action["selected"])

    def test_idb_retains_optional_metadata(self):
        parsed = DEVICE_A11Y._parse_idb(json.dumps([el(
            "Search", 10, 20, role="AXTextField", AXAccessible=True,
            AXTraits=["TextField"], AXFocused=True, AXSelected=False,
        )]))
        action = parsed[0]
        self.assertTrue(action["accessible"])
        self.assertEqual(action["traits"], ["TextField"])
        self.assertTrue(action["focused"])
        self.assertFalse(action["selected"])

    def test_old_fixtures_get_non_breaking_unknown_defaults(self):
        action = DEVICE_A11Y._parse_idb(json.dumps([el("계속", 10, 20)]))[0]
        self.assertIsNone(action["accessible"])
        self.assertEqual(action["traits"], [])
        self.assertIsNone(action["focused"])
        self.assertIsNone(action["selected"])

    def test_idb_nested_dump_is_flattened_with_depth_and_parent(self):
        # `idb ui describe-all --json --nested` — same keys plus `children`.
        tree = [dict(el("", 0, 0, 402, 874, role="AXApplication"), children=[
            dict(el("", 0, 0, 402, 874, role="AXTabBar"), children=[
                el("홈", 0, 800, 100, 60, role="AXButton"),
                el("검색", 100, 800, 100, 60, role="AXButton"),
            ]),
            el("게시물", 0, 100, 402, 200, role="AXCell"),
        ])]
        parsed = DEVICE_A11Y._parse_idb(json.dumps(tree))
        self.assertEqual([e["role"] for e in parsed],
                         ["AXApplication", "AXTabBar", "AXButton", "AXButton", "AXCell"])
        self.assertEqual([e["depth"] for e in parsed], [0, 1, 2, 2, 1])
        self.assertEqual([e["parent"] for e in parsed], [-1, 0, 1, 1, 0])
        # The ancestor walk that the WDA path relies on now works for idb too.
        self.assertEqual(DEVICE_A11Y._ancestor_index(parsed, 2, {"AXTabBar"}), 1)
        self.assertIsNone(DEVICE_A11Y._ancestor_index(parsed, 4, {"AXTabBar"}))

    def test_idb_flat_dump_still_parses_at_depth_zero(self):
        parsed = DEVICE_A11Y._parse_idb(json.dumps([el("a", 0, 0), el("b", 0, 50)]))
        self.assertEqual([(e["depth"], e["parent"]) for e in parsed], [(0, -1), (0, -1)])


class TestWdaFormat(unittest.TestCase):
    """Real-device path: WebDriverAgent GET /source."""

    def test_emits_center_coordinates(self):
        r = wda(node("Button", "계속", 38, 722, 299, 52))
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("INFO: tap 187 748 | AXButton | 계속", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_collapses_control_and_its_inner_text(self):
        # Verified on a live Journal screen: a Button "계속" wrapping a StaticText
        # "계속" at the same spot must yield ONE target, and the Button wins.
        r = wda(node("Button", "계속", 38, 722, 299, 52) + node("StaticText", "계속", 40, 724, 295, 48))
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)
        self.assertIn("AXButton", r.stdout)

    def test_drops_invisible_and_container_and_noise(self):
        r = wda(
            node("Button", "숨김", 0, 100, visible="false")
            + node("NavigationBar", "일기", 0, 40, 375, 44)
            + node("Other", "수직 스크롤 막대, 1페이지", 350, 300, 10, 400)
        )
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_withholds_destructive(self):
        r = wda(node("Button", "일기 삭제", 38, 400, 299, 52))
        self.assertNotIn("INFO: tap", r.stdout)
        self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)


class TestIdbFormat(unittest.TestCase):
    """Simulator path: idb `ui describe-all`."""

    def test_emits_center_coordinates(self):
        r = idb([ROOT, el("보관함", 20, 100, 100, 40)])
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("INFO: tap 70 120 | AXButton | 보관함", r.stdout)

    def test_skips_containers_disabled_and_offscreen(self):
        r = idb([
            ROOT,
            el("Scroll", 0, 0, 393, 800, role="AXScrollArea"),
            el("Off", 0, 3000),
            el("Dimmed", 0, 300, enabled=False),
            el("Zero", 0, 400, 0, 0),
        ])
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_preserves_legitimate_links_cells_and_text_inputs(self):
        r = idb([
            ROOT,
            el("프로필", 0, 100, role="AXLink"),
            el("추천 계정", 0, 160, role="AXCell"),
            el("검색", 0, 220, role="AXSearchField"),
            el("설명", 0, 280, role="AXStaticText"),
        ])
        self.assertIn("AXLink | 프로필", r.stdout)
        self.assertIn("AXCell | 추천 계정", r.stdout)
        self.assertIn("AXSearchField | 검색", r.stdout)
        self.assertNotIn("AXStaticText | 설명", r.stdout)
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)


class TestDestructiveGuard(unittest.TestCase):
    """The blacklist lives at the producer — this is the only place it is enforced."""

    def test_withholds_destructive_labels(self):
        for label in ("삭제", "Delete Account", "구독하기", "Sign Out", "결제"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertNotIn("INFO: tap", r.stdout)
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)

    def test_allows_plain_cancel_as_the_escape_hatch(self):
        r = idb([ROOT, el("취소", 0, 200), el("Cancel", 0, 260)])
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)

    def test_withholds_only_the_subscription_sense_of_cancel(self):
        r = idb([ROOT, el("구독 취소", 0, 200), el("Cancel Subscription", 0, 260)])
        self.assertIn("OK: 0 tappable, 2 withheld", r.stdout)

    def test_withholds_in_app_currency_top_up(self):
        # zeta's 마이페이지 sells pieces behind a button labelled only 충전 —
        # a purchase none of the purchase words caught (measured 2026-08-27).
        for label in ("충전", "피스 충전", "Top Up", "Recharge"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)
                self.assertIn("destructive", r.stdout)


class TestStateChangingGuard(unittest.TestCase):
    def test_threads_like_account_mutations_are_categorized_and_withheld(self):
        cases = {
            "팔로우": "social-follow",
            "Unfollow user.one": "social-follow",
            "좋아요": "social-like",
            "Like post": "social-like",
            "리포스트": "social-repost",
            "Repost thread": "social-repost",
            "게시": "publishing",
            "Post reply": "publishing",
            "보내기": "communication",
            "Send message": "communication",
            "추천 숨기기": "recommendation",
            "Dismiss suggestion": "recommendation",
        }
        for label, effect in cases.items():
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("WARN: withheld", r.stdout)
                self.assertIn("category=state-changing", r.stdout)
                self.assertIn(f"effect={effect}", r.stdout)
                self.assertIn("withheld=true", r.stdout)

    def test_the_real_labels_a_device_reports_are_withheld(self):
        """Observed on a connected iPhone running Threads, 2026-08-22.

        A real accessibility label names the action and then describes it —
        `좋아요. 226명이 이 게시물을 좋아합니다.`, not `좋아요`. Every pattern here
        is anchored at the end (so that `팔로우 추천` stays navigation), so
        matching the whole label let all of these through: exploration tapped
        like and share on another person's post from the user's own account.
        The bare-label cases above never caught it because no device emits them.
        """
        cases = {
            "좋아요. 226명이 이 게시물을 좋아합니다.": "social-like",
            "좋아요. 2,732명이 이 게시물을 좋아합니다.": "social-like",
            "리포스트. 4명이 이 게시물을 리포스트했습니다.": "social-repost",
            "공유하기. 183명이 이 게시물을 공유했습니다.": "sharing",
            "Like. 226 people liked this post.": "social-like",
        }
        for label, effect in cases.items():
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("WARN: withheld", r.stdout)
                self.assertIn(f"effect={effect}", r.stdout)
                self.assertIn("withheld=true", r.stdout)

    def test_state_describing_toggle_buttons_are_withheld(self):
        """Observed on Threads 2026-08-23: the post-notification bell.

        Its label describes the CURRENT state — `알림이 비활성화되었습니다` — so
        it matched no action pattern and read as navigation. Two runs toggled
        it on three people's posts, and the audit, reading this same table,
        reported zero state-changing taps: a hole in the guard is also a hole
        in the audit.
        """
        cases = ["알림이 비활성화되었습니다.", "알림이 활성화되었습니다.",
                 "알림 끄기", "Turn on notifications", "Notifications off",
                 "Mute"]
        for label in cases:
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("WARN: withheld", r.stdout)
                self.assertIn("effect=state-toggle", r.stdout)

    def test_describing_a_screen_is_still_navigation(self):
        """The leading-clause check must not swallow ordinary navigation.

        `답글 달기` opens the reply composer (a screen); the publish button is
        `게시`. `좋아요한 글` is the profile's liked-posts tab, not the like button.
        """
        labels = ["답글 달기. 35명이 이 게시물에 답글을 달았습니다.",
                  "좋아요한 글", "게시 옵션", "게시물 만들기", "내가 팔로우하는 사람",
                  "알림", "알림 설정", "Muted words"]
        r = idb([ROOT] + [el(label, 0, 200 + 40 * i) for i, label in enumerate(labels)])
        self.assertIn(f"OK: {len(labels)} tappable, 0 withheld", r.stdout)
        self.assertNotIn("category=state-changing", r.stdout)

    def test_a_control_quoting_a_price_is_withheld(self):
        # zeta's illustration button is labelled `스냅샷 15피스` — it debits the
        # balance on tap and carries no purchase word at all.
        for label in ("스냅샷 15피스", "100 코인으로 열기", "Unlock for 3 credits", "₩1,500"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)
                self.assertIn("effect=spend", r.stdout)

    def test_priceless_labels_are_still_navigation(self):
        r = idb([ROOT, el("피스 내역", 0, 200), el("포인트", 0, 260), el("3개의 답글", 0, 320)])
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)

    def test_a_creator_tool_publish_and_draft_buttons_are_withheld(self):
        # zeta's plot editor ships 등록 (publish) beside 임시저장 (save draft).
        # Neither word was in the vocabulary, and both leave content behind in
        # the user's own account.
        for label in ("등록", "임시저장", "출품", "저장하기", "Publish", "Save draft"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)

    def test_screens_about_registration_are_still_navigation(self):
        r = idb([ROOT, el("등록된 항목", 0, 200), el("등록 안내", 0, 260),
                 el("저장된 대화", 0, 320)])
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)

    def test_leaving_a_room_is_withheld(self):
        # 나가기 discards the conversation; no delete word matches it.
        for label in ("대화방 나가기", "나가기", "Leave chat"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)
                self.assertIn("effect=leaving", r.stdout)

    def test_share_button_named_after_what_it_shares_is_withheld(self):
        # Korean puts the noun first, so anchoring at ^ missed the real button:
        # zeta's profile share reads 프로필 공유 and opened the system sheet,
        # which replaces the target app in the foreground.
        r = idb([ROOT, el("프로필 공유", 0, 200), el("Share profile", 0, 260)])
        self.assertIn("OK: 0 tappable, 2 withheld", r.stdout)
        self.assertIn("effect=sharing", r.stdout)

    def test_screens_about_sharing_are_still_navigation(self):
        r = idb([ROOT, el("공유 설정", 0, 200), el("공유된 항목", 0, 260)])
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)

    def test_follow_suggestions_navigation_is_not_misclassified(self):
        r = idb([ROOT, el("팔로우 추천", 0, 200), el("Follow suggestions", 0, 260)])
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)
        self.assertNotIn("category=state-changing", r.stdout)

    def test_switch_is_withheld_by_default(self):
        # The tree cannot tell a local preference from an account setting.
        r = idb([ROOT, el("비공개 프로필", 0, 200, role="AXSwitch")])
        self.assertIn("WARN: withheld", r.stdout)
        self.assertIn("effect=toggle", r.stdout)

    def test_switch_is_reversible_only_when_probing_is_explicitly_enabled(self):
        r = idb_probing([ROOT, el("비공개 프로필", 0, 200, role="AXSwitch")])
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)
        self.assertIn("category=reversible | effect=toggle", r.stdout)

    def test_two_switches_on_one_screen_are_two_behaviors(self):
        r = idb_probing([ROOT, el("알림", 0, 200, role="AXSwitch"), el("다크 모드", 0, 260, role="AXSwitch")])
        behaviors = {line.split("behavior=")[1].split(" | ")[0]
                     for line in r.stdout.splitlines() if "candidate-meta" in line}
        self.assertEqual(len(behaviors), 2, msg=r.stdout)

    def test_switch_with_a_subscription_label_stays_withheld(self):
        r = idb_probing([ROOT, el("구독 자동 갱신", 0, 200, role="AXSwitch")])
        self.assertIn("WARN: withheld", r.stdout)


class TestModalGuard(unittest.TestCase):
    def test_system_consent_dialog_without_alert_role_is_suppressed(self):
        # Shape taken from a live `idb ui describe-all` of an ATT prompt: a flat
        # StaticText/Button tree under a blank AXApplication, no AXAlert at all.
        # Role-based detection alone missed this and offered "Allow" as a tap.
        r = idb([
            el(" ", 0, 0, 402, 874, role="AXApplication"),
            el("Allow “Foo” to track your activity?", 71, 371, 260, 64, role="AXStaticText"),
            el("Ask App Not to Track", 57, 521, 288, 48),
            el("Allow", 57, 577, 288, 48),
        ])
        self.assertIn("WARN: alert/sheet on screen", r.stdout)
        self.assertNotIn("INFO: tap", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_alert_role_also_suppresses(self):
        r = idb([ROOT, el("위치 접근", 0, 400, role="AXAlert"), el("나중에", 100, 500)])
        self.assertIn("WARN: alert/sheet on screen", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_ordinary_confirm_buttons_do_not_stop_the_loop(self):
        # 확인/계속 are too generic to mean "system dialog" — stopping there
        # would strand exploration on ordinary app screens.
        r = idb([ROOT, el("확인", 0, 200), el("계속", 0, 260)])
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)


class TestRowCollapsing(unittest.TestCase):
    """A real Journal screen offered 31 "targets" for ~6 real ones before this."""

    ROW = node("Cell", "일기 항목", 0, 400, 375, 60)
    INNER_TEXT = node("StaticText", "0 개의 입력 항목(올해)", 20, 415, 200, 20)
    INNER_BUTTON = node("Button", "새로운 일기", 320, 410, 40, 40)

    def test_inert_text_inside_a_row_is_dropped(self):
        r = wda(self.ROW + self.INNER_TEXT)
        self.assertIn("일기 항목", r.stdout)
        self.assertNotIn("0 개의 입력 항목", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_actionable_control_inside_a_row_survives(self):
        # Tapping the row and tapping its trailing button do different things.
        r = wda(self.ROW + self.INNER_BUTTON)
        self.assertIn("새로운 일기", r.stdout)
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)

    def test_inert_standalone_text_is_dropped(self):
        r = wda(node("StaticText", "입력 항목 없음", 100, 470, 175, 30))
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_static_text_with_button_trait_is_actionable(self):
        r = wda(node("StaticText", "프로필 열기", 100, 470, 175, 30, traits="Button"))
        self.assertIn("INFO: tap", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_repeated_data_rows_share_a_behavior_fingerprint(self):
        rows = (
            '<XCUIElementTypeCell type="XCUIElementTypeCell" label="user.one" name="user.one"'
            ' enabled="true" visible="true" x="0" y="300" width="375" height="60"/>'
            '<XCUIElementTypeCell type="XCUIElementTypeCell" label="user.two" name="user.two"'
            ' enabled="true" visible="true" x="0" y="360" width="375" height="60"/>'
        )
        r = wda(rows)
        fingerprints = [part.split("behavior=", 1)[1].split(" | ", 1)[0]
                        for part in r.stdout.splitlines() if "behavior=" in part]
        self.assertEqual(len(fingerprints), 2)
        self.assertEqual(fingerprints[0], fingerprints[1])


def branch(kind: str, label: str, x: int, y: int, w: int, h: int,
           children: str = "", visible: str = "true") -> str:
    """A container node that can hold children — `node` is self-closing."""
    return (f'<XCUIElementType{kind} type="XCUIElementType{kind}" label="{label}" name="{label}"'
            f' enabled="true" visible="{visible}" x="{x}" y="{y}" width="{w}" height="{h}">'
            f'{children}</XCUIElementType{kind}>')


class TestRoleBlindFallback(unittest.TestCase):
    """Custom renderers report every box as AXOther with no traits.

    Shaped after a real zeta 3.47.0 home capture (2026-08-27): 144 elements, 60
    of them labelled, not one reporting an actionable role — the role tier
    returned 0 candidates including the tab bar, so exploration could not move.
    """

    def test_labelled_other_leaves_become_targets_when_no_role_is_reported(self):
        r = wda(branch("Other", "홈 대화 만들기", 0, 760, 393, 52,
                       node("Other", "홈", 28, 774, 48, 39)
                       + node("Other", "대화", 124, 774, 49, 39)
                       + node("Other", "만들기", 220, 774, 49, 39)))
        self.assertIn("WARN: role-blind screen", r.stdout)
        self.assertIn("INFO: tap 52 793 | AXOther | 홈", r.stdout)
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)

    def test_an_ancestor_that_only_inherits_its_label_is_not_a_target(self):
        # The wrapper's label is the concatenation of its children, and its
        # centre belongs to whichever child happens to sit there. Tapping it is
        # never what the user sees, so only the leaves are offered.
        r = wda(branch("Other", "홈 대화 만들기", 0, 760, 393, 52,
                       node("Other", "홈", 28, 774, 48, 39)
                       + node("Other", "대화", 124, 774, 49, 39)
                       + node("Other", "만들기", 220, 774, 49, 39)))
        self.assertNotIn("홈 대화 만들기", r.stdout.replace("WARN: role-blind screen", ""))

    def test_destructive_labels_are_still_withheld(self):
        r = wda(node("Other", "구독 결제하기", 38, 400, 299, 52))
        self.assertIn("WARN: role-blind screen", r.stdout)
        self.assertNotIn("INFO: tap", r.stdout)
        self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)

    def test_state_changing_labels_are_still_withheld(self):
        r = wda(node("Other", "팔로우", 38, 400, 299, 52))
        self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)

    def test_a_system_dialog_still_suppresses_everything(self):
        r = wda(node("Other", "허용", 100, 400) + node("Other", "홈", 28, 774, 48, 39))
        self.assertIn("WARN: alert/sheet on screen", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_a_screen_covering_leaf_is_a_backdrop_not_a_target(self):
        # Its centre belongs to whatever it sits behind, so tapping it is either
        # a no-op or a surprise.
        r = wda(node("Button", "계속", 38, 722, 299, 52) + node("Other", "배경", 0, 0, 393, 700))
        self.assertNotIn("배경", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_the_warning_is_only_for_screens_with_no_role_at_all(self):
        # Leaves are always merged, but the "read the screen yourself" warning
        # means something specific: NOTHING here was vouched for by a role.
        r = wda(node("Button", "계속", 38, 722, 299, 52) + node("Other", "더보기", 340, 60, 40, 40))
        self.assertNotIn("WARN: role-blind screen", r.stdout)
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)

    def test_one_role_does_not_hide_the_rest_of_the_screen(self):
        # zeta's search screen reports exactly one AXTextField. Treating that as
        # "the role tier worked" left all 15 tag chips invisible and made the
        # screen a dead end (measured 2026-08-27).
        chips = "".join(node("Other", f"#태그{i}", 16 + 70 * i, 184, 60, 30) for i in range(4))
        r = wda(node("TextField", "search-input", 55, 76, 280, 36) + chips)
        self.assertIn("#태그0", r.stdout)
        self.assertIn("#태그3", r.stdout)
        self.assertIn("OK: 5 tappable, 0 withheld", r.stdout)

    def test_scrollable_content_does_not_swallow_the_chrome_it_passes_under(self):
        # Containment cannot tell "inside" from "behind". A feed card reaches
        # under the translucent tab bar, and a card scrolled off the top reaches
        # under the sticky filter chips — both contain that chrome's centre.
        under_tabbar = wda(node("Other", "카드", 16, 580, 177, 288)
                           + node("Other", "홈", 28, 774, 48, 39))
        self.assertIn("INFO: tap 52 793 | AXOther | 홈", under_tabbar.stdout)
        self.assertIn("OK: 2 tappable, 0 withheld", under_tabbar.stdout)

        under_chips = wda(node("Other", "카드", 16, -14, 177, 288)
                          + node("Other", "추천", 16, 119, 45, 28))
        self.assertIn("INFO: tap 38 133 | AXOther | 추천", under_chips.stdout)

    def test_the_inert_text_rule_still_removes_what_it_always_did(self):
        # Journal's inner text goes at the rank filter, not at containment.
        r = wda(node("Cell", "일기 항목", 0, 400, 375, 60)
                + node("StaticText", "0 개의 입력 항목", 20, 415, 200, 20))
        self.assertNotIn("0 개의 입력 항목", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_inert_static_text_is_never_promoted(self):
        # An empty state is candidate-less on purpose. The fallback is for a
        # missing role vocabulary, not for a screen with nothing to tap.
        r = wda(node("StaticText", "입력 항목 없음", 38, 460, 299, 50))
        self.assertNotIn("WARN: role-blind screen", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_geometric_overlap_does_not_swallow_a_leaf(self):
        # zeta's feed cards extend behind the translucent tab bar, so the row
        # containment drop removed every tab item and left the loop with no way
        # out of the feed. Leaves never nest, so overlap here is geometric only.
        r = wda(node("Other", "카드 제목 설명 태그", 16, 580, 177, 288)
                + node("Other", "홈", 28, 774, 48, 39))
        self.assertIn("INFO: tap 52 793 | AXOther | 홈", r.stdout)
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)

    def test_verify_accepts_a_fallback_candidate(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<AppiumAUT>'
                    '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App"'
                    ' label="App" enabled="true" visible="true" x="0" y="0" width="375"'
                    f' height="812">{node("Other", "대화", 124, 774, 49, 39)}'
                    '</XCUIElementTypeApplication></AppiumAUT>')
            fixture = f.name
        try:
            ok = subprocess.run(["python3", str(SCRIPT), "verify", fixture, "148", "793"],
                                capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, msg=ok.stderr)
            miss = subprocess.run(["python3", str(SCRIPT), "verify", fixture, "10", "10"],
                                  capture_output=True, text=True)
            self.assertEqual(miss.returncode, 1)
        finally:
            Path(fixture).unlink()


class TestKeyboardFiltering(unittest.TestCase):
    def test_axkey_is_never_a_generic_candidate(self):
        r = wda(node("Key", "ㅂ", 0, 600))
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_keyboard_descendants_are_never_generic_candidates(self):
        keyboard = (
            '<XCUIElementTypeKeyboard type="XCUIElementTypeKeyboard" label="키보드" name="키보드"'
            ' enabled="true" visible="true" x="0" y="500" width="375" height="312">'
            + node("Button", "완료", 300, 510, 60, 40, traits="Button")
            + '</XCUIElementTypeKeyboard>'
        )
        r = wda(keyboard)
        self.assertNotIn("완료", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_flat_idb_keyboard_geometry_suppresses_children(self):
        r = idb([
            ROOT,
            el("키보드", 0, 500, 393, 352, role="AXKeyboard"),
            el("완료", 300, 510, 60, 40, role="AXButton", AXTraits=["Button"]),
        ])
        self.assertNotIn("완료", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_keyboard_key_trait_suppresses_wda_siblings_outside_keyboard_frame(self):
        # iOS may expose globe/dictation buttons as AXButton siblings whose
        # centers fall below the AXKeyboard container's reported frame.
        tree = (
            '<XCUIElementTypeKeyboard type="XCUIElementTypeKeyboard" enabled="true" '
            'visible="true" x="0" y="512" width="375" height="242"/>'
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="다음 키보드" '
            'enabled="true" visible="true" x="9" y="740" width="74" height="75" '
            'traits="KeyboardKey, Button"/>'
        )
        r = wda(tree)
        self.assertNotIn("다음 키보드", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)


class TestVerify(unittest.TestCase):
    """`verify` is what makes "never tap outside candidates" mechanical.

    A live run drifted past that rule as prose: after an unexpected screen the
    next tap still used the previous tree's coordinates and walked out of the
    target app entirely.
    """

    def _verify(self, inner: str, x: int, y: int) -> subprocess.CompletedProcess:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<AppiumAUT>'
            '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
            ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
            f'{inner}</XCUIElementTypeApplication></AppiumAUT>'
        )
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
            f.write(body)
            fixture = f.name
        try:
            return subprocess.run(
                ["python3", str(SCRIPT), "verify", fixture, str(x), str(y)],
                capture_output=True, text=True,
            )
        finally:
            Path(fixture).unlink()

    def test_accepts_a_real_candidate(self):
        r = self._verify(node("Button", "계속", 38, 722, 299, 52), 187, 748)
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_rejects_a_coordinate_the_screen_never_offered(self):
        r = self._verify(node("Button", "계속", 38, 722, 299, 52), 100, 100)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a tap candidate", r.stderr)

    def test_rejects_a_withheld_destructive_target_by_name(self):
        r = self._verify(node("Button", "일기 삭제", 38, 400, 299, 52), 187, 426)
        self.assertEqual(r.returncode, 1)
        self.assertIn("WITHHELD", r.stderr)

    def test_rejects_everything_while_a_system_dialog_is_up(self):
        r = self._verify(
            node("StaticText", "‘Foo’이(가) 추적하도록 허용하겠습니까?", 71, 371, 260, 64)
            + node("Button", "허용", 57, 577, 288, 48),
            201, 601,
        )
        self.assertEqual(r.returncode, 1)


class TestSignature(unittest.TestCase):
    """`sig` is the exploration loop's only guard against looping forever."""

    def test_same_labels_different_order_hash_equal(self):
        a = idb([el("홈", 0, 0), el("설정", 0, 60)], mode="sig")
        b = idb([el("설정", 0, 60), el("홈", 0, 0)], mode="sig")
        self.assertEqual(a.returncode, 0, msg=a.stderr)
        self.assertIn("INFO: sig ", a.stdout)
        self.assertEqual(a.stdout.splitlines()[0], b.stdout.splitlines()[0])

    def test_different_screen_hashes_differ(self):
        a = idb([el("홈", 0, 0)], mode="sig")
        b = idb([el("상세", 0, 0)], mode="sig")
        self.assertNotEqual(a.stdout.splitlines()[0], b.stdout.splitlines()[0])

    def test_both_formats_agree_on_the_same_label_set(self):
        # Same screen seen through either driver must hash identically, or a
        # driver switch would look like a brand-new screen forever.
        a = idb([el("App", 0, 0, 375, 812, role="AXApplication"),
                 el("홈", 0, 0, role="AXButton")], mode="sig")
        b = wda(node("Button", "홈", 0, 0), mode="sig")  # helper supplies the same root
        self.assertEqual(a.stdout.splitlines()[0], b.stdout.splitlines()[0])


class TestNodeKey(unittest.TestCase):
    """Screen identity for the flow graph — deliberately blunter than `sig`.

    `sig` moves on any label change, which is what the tap guard needs. A graph
    node must not: scrolling a list would mint a screen per scroll position and
    the exploration frontier would never drain.
    """

    def key(self, inner: str) -> str:
        out = wda(inner, mode="nodekey").stdout
        return next(l.split()[-1] for l in out.splitlines() if l.startswith("INFO: nodekey"))

    def test_the_same_screen_with_different_data_is_one_node(self):
        a = self.key(node("Cell", "월요일 산책", 16, 100) + node("Cell", "화요일 회의", 16, 160))
        b = self.key(node("Cell", "제주 여행", 16, 100) + node("Cell", "치과 예약", 16, 160))
        self.assertEqual(a, b)

    def test_scrolling_one_row_into_view_is_not_a_new_screen(self):
        rows = [node("Cell", f"항목 {i}", 16, 100 + i * 60) for i in range(5)]
        self.assertEqual(self.key("".join(rows)), self.key("".join(rows + [
            node("Cell", "항목 5", 16, 400)])))

    def test_empty_and_populated_are_different_screens(self):
        # These are different layouts to reproduce, so they must stay separate.
        empty = self.key(node("StaticText", "입력 항목 없음", 125, 462))
        full = self.key("".join(node("Cell", f"항목 {i}", 16, 100 + i * 60) for i in range(5)))
        self.assertNotEqual(empty, full)

    def test_wrapper_churn_does_not_split_a_screen_in_two(self):
        # Live: the same empty-list screen was captured twice minutes apart. One
        # dump put the create button under an AXToolbar, the other under an
        # AXOther, and the graph gained a phantom second node.
        content = node("Button", "생성", 323, 760) + node("StaticText", "항목 없음", 125, 462)
        wrapped = (
            '<XCUIElementTypeToolbar type="XCUIElementTypeToolbar" label="" name=""'
            ' enabled="true" visible="true" x="0" y="740" width="375" height="72">'
            + node("Button", "생성", 323, 760) + '</XCUIElementTypeToolbar>'
            + node("StaticText", "항목 없음", 125, 462)
        )
        self.assertEqual(self.key(content), self.key(wrapped))

    def test_the_keyboard_is_not_part_of_screen_identity(self):
        # The keyboard animates in; capturing before and after must not fork the node.
        base = node("TextField", "제목", 20, 300)
        keys = "".join(node("Key", c, i * 30, 600) for i, c in enumerate("ㅂㅈㄷㄱ"))
        self.assertEqual(self.key(base), self.key(base + keys))

    def test_the_navigation_title_separates_look_alike_screens(self):
        # Two settings-style screens with identical structure are told apart by
        # the bar that names them.
        a = self.key(node("NavigationBar", "알림", 0, 50) + node("Cell", "항목", 16, 110))
        b = self.key(node("NavigationBar", "개인정보", 0, 50) + node("Cell", "항목", 16, 110))
        self.assertNotEqual(a, b)

    def test_custom_header_trait_separates_look_alike_screens(self):
        # Threads uses Header static text instead of AXNavigationBar for titles
        # such as 메시지/설정; role counts alone collapse those distinct routes.
        a = self.key(node("StaticText", "메시지", 16, 51, traits="Header")
                     + node("Button", "메뉴", 335, 59))
        b = self.key(node("StaticText", "설정", 172, 61, traits="Header")
                     + node("Button", "메뉴", 335, 59))
        self.assertNotEqual(a, b)

    def test_header_inside_list_row_does_not_split_dynamic_data(self):
        def row(title: str) -> str:
            return (
                '<XCUIElementTypeCell type="XCUIElementTypeCell" label="" name=""'
                ' enabled="true" visible="true" x="0" y="100" width="375" height="60">'
                + node("StaticText", title, 16, 110, traits="Header")
                + '</XCUIElementTypeCell>'
            )
        self.assertEqual(self.key(row("첫 게시물")), self.key(row("다른 게시물")))

    def test_full_screen_cell_wrapper_does_not_hide_custom_header(self):
        def screen(title: str) -> str:
            return (
                '<XCUIElementTypeCell type="XCUIElementTypeCell" label="" name=""'
                ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
                + node("StaticText", title, 16, 51, traits="Header")
                + node("Button", "메뉴", 335, 59)
                + '</XCUIElementTypeCell>'
            )
        self.assertNotEqual(self.key(screen("메시지")), self.key(screen("설정")))


class TestStateKey(unittest.TestCase):
    def key(self, mode: str, inner: str) -> str:
        out = wda(inner, mode=mode).stdout
        return next(line.split()[-1] for line in out.splitlines()
                    if line.startswith(f"INFO: {mode}"))

    def test_keyboard_changes_state_but_not_coarse_node(self):
        base = node("TextField", "검색", 20, 120, 335, 44)
        keyboard = (
            '<XCUIElementTypeKeyboard type="XCUIElementTypeKeyboard" label="키보드" name="키보드"'
            ' enabled="true" visible="true" x="0" y="500" width="375" height="312">'
            + node("Key", "ㅂ", 0, 600)
            + node("Button", "완료", 300, 510, 60, 40, traits="Button")
            + '</XCUIElementTypeKeyboard>'
        )
        self.assertEqual(self.key("nodekey", base), self.key("nodekey", base + keyboard))
        self.assertNotEqual(self.key("statekey", base), self.key("statekey", base + keyboard))

    def test_focused_input_changes_state(self):
        idle = node("TextField", "검색", 20, 120, 335, 44, focused=False)
        focused = node("TextField", "검색", 20, 120, 335, 44, focused=True)
        self.assertEqual(self.key("nodekey", idle), self.key("nodekey", focused))
        self.assertNotEqual(self.key("statekey", idle), self.key("statekey", focused))

    def test_selected_tab_identity_is_preserved(self):
        def tabs(home: bool) -> str:
            return (
                '<XCUIElementTypeTabBar type="XCUIElementTypeTabBar" label="탭" name="탭"'
                ' enabled="true" visible="true" x="0" y="740" width="375" height="72">'
                + node("Button", "홈", 0, 740, 187, 72, selected=home)
                + node("Button", "검색", 188, 740, 187, 72, selected=not home)
                + '</XCUIElementTypeTabBar>'
            )
        self.assertEqual(self.key("nodekey", tabs(True)), self.key("nodekey", tabs(False)))
        self.assertNotEqual(self.key("statekey", tabs(True)), self.key("statekey", tabs(False)))

    def test_modal_changes_state_but_not_coarse_node(self):
        base = node("Button", "도움말", 320, 60, 44, 44)
        sheet = (
            '<XCUIElementTypeSheet type="XCUIElementTypeSheet" label="정보" name="정보"'
            ' enabled="true" visible="true" x="0" y="200" width="375" height="612">'
            + node("Button", "닫기", 300, 220, 60, 40)
            + '</XCUIElementTypeSheet>'
        )
        self.assertEqual(self.key("nodekey", base), self.key("nodekey", base + sheet))
        self.assertNotEqual(self.key("statekey", base), self.key("statekey", base + sheet))

    def test_switch_value_changes_state_but_not_coarse_node(self):
        off = node("Switch", "알림", 300, 200, 51, 31, value=0)
        on = node("Switch", "알림", 300, 200, 51, 31, value=1)
        self.assertEqual(self.key("nodekey", off), self.key("nodekey", on))
        self.assertNotEqual(self.key("statekey", off), self.key("statekey", on))

    def test_list_data_churn_does_not_change_state(self):
        first = node("Cell", "user.one", 0, 200, 375, 60) + node("Cell", "user.two", 0, 260, 375, 60)
        second = (node("Cell", "another.user", 0, 200, 375, 60)
                  + node("Cell", "new.user", 0, 260, 375, 60)
                  + node("Cell", "third.user", 0, 320, 375, 60))
        self.assertEqual(self.key("statekey", first), self.key("statekey", second))


if __name__ == "__main__":
    unittest.main()


class TestBackEscape(unittest.TestCase):
    """The only tap allowed to come from an unlabelled element.

    A detail screen whose back chevron carries no label has no candidate and no
    tab bar, and zeta ignores the interactive pop gesture — measured 2026-08-27,
    exploration dead-ended three times on screens it had walked into itself. The
    leading edge of a nav bar means back/close/cancel by platform convention, so
    it is safe to name geometrically; it stays a deliberate command rather than a
    candidate so nothing taps it by accident.
    """

    def back(self, inner: str):
        return wda(inner, mode="back")

    def test_an_unlabelled_chevron_in_the_nav_slot_is_found(self):
        r = self.back('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                      ' enabled="true" visible="true" x="6" y="67" width="36" height="36"/>')
        self.assertIn("INFO: back 24 85", r.stdout)
        self.assertIn("(unlabelled)", r.stdout)

    def test_a_labelled_back_button_is_found_too(self):
        r = self.back(node("Button", "Go back", 10, 66, 24, 36))
        self.assertIn("INFO: back 22 84", r.stdout)

    def test_a_tab_root_offers_no_back(self):
        # The top-leading control here is the first segment of a nav bar, which
        # is a candidate in its own right and does not leave the screen.
        r = self.back(node("Other", "콘테스트", 10, 68, 81, 34)
                      + node("Other", "홈", 90, 68, 30, 34))
        self.assertIn("INFO: back 0", r.stdout)

    def test_a_wide_control_is_a_title_not_a_chevron(self):
        r = self.back('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                      ' enabled="true" visible="true" x="0" y="67" width="200" height="36"/>')
        self.assertIn("INFO: back 0", r.stdout)

    def test_something_below_the_nav_bar_is_not_a_back_control(self):
        r = self.back('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                      ' enabled="true" visible="true" x="6" y="400" width="36" height="36"/>')
        self.assertIn("INFO: back 0", r.stdout)

    def test_a_trailing_control_is_not_a_back_control(self):
        r = self.back('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                      ' enabled="true" visible="true" x="340" y="67" width="36" height="36"/>')
        self.assertIn("INFO: back 0", r.stdout)

    def test_an_invisible_chevron_is_not_offered(self):
        r = self.back('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                      ' enabled="true" visible="false" x="6" y="67" width="36" height="36"/>')
        self.assertIn("INFO: back 0", r.stdout)

    def test_unlabelled_elements_are_still_never_tap_candidates(self):
        # `back` is an exception for one slot, not a loosening of the rule.
        r = wda('<XCUIElementTypeOther type="XCUIElementTypeOther" label="" name=""'
                ' enabled="true" visible="true" x="6" y="67" width="36" height="36"/>')
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)


class TestCandidateProvenance(unittest.TestCase):
    """Which candidates were vouched for by a role, and which only by words.

    The screen-level role-blind warning only fires when NOTHING reported a role,
    so on a mixed screen a label-derived target looked exactly like one a role
    vouched for — measured on zeta's search screen, 15 of 16 candidates came
    from labels alone while the lone AXTextField suppressed the warning.
    """

    def test_a_role_backed_candidate_is_marked_role(self):
        r = wda(node("Button", "계속", 38, 722, 299, 52))
        self.assertIn("source=role", r.stdout)
        self.assertNotIn("source=label", r.stdout)

    def test_a_label_leaf_candidate_is_marked_label(self):
        r = wda(node("Other", "홈", 28, 774, 48, 39))
        self.assertIn("source=label", r.stdout)

    def test_a_mixed_screen_marks_each_candidate_separately(self):
        r = wda(node("TextField", "search-input", 55, 76, 280, 36)
                + node("Other", "#태그", 16, 184, 60, 30))
        self.assertNotIn("WARN: role-blind screen", r.stdout)
        self.assertEqual(r.stdout.count("source=role"), 1)
        self.assertEqual(r.stdout.count("source=label"), 1)


class TestTypeableFields(unittest.TestCase):
    """Typing commits with Return, and Return in a composer SENDS.

    That is the `communication` guard walked around by the keyboard: the Send
    button is withheld, but a blind probe typing into "the first text field"
    and pressing Return sends the message anyway.
    """

    def fields(self, inner: str):
        return wda(inner, mode="inputs")

    def test_a_search_field_is_typeable(self):
        r = self.fields(node("SearchField", "q", 10, 60, 300, 36))
        self.assertIn("\tsearch", r.stdout)
        self.assertIn("inputs 1 (1 search)", r.stdout)

    def test_a_field_named_for_search_is_typeable(self):
        for name in ("search-input", "검색어", "Find a plot"):
            with self.subTest(name=name):
                r = self.fields(node("TextField", name, 10, 60, 300, 36))
                self.assertIn("\tsearch", r.stdout)

    def test_a_message_composer_is_offered_but_not_marked_search(self):
        # Still listed — the caller may need to know it exists — but the driver
        # only types into fields marked `search`.
        r = self.fields(node("TextField", "메시지 입력", 10, 700, 300, 36))
        self.assertIn("\tother", r.stdout)
        self.assertIn("inputs 1 (0 search)", r.stdout)

    def test_a_comment_box_is_not_search(self):
        r = self.fields(node("TextField", "댓글을 입력하세요", 10, 700, 300, 36))
        self.assertIn("\tother", r.stdout)

    def test_a_multiline_composer_is_not_typeable_at_all(self):
        # AXTextView is outside TEXT_INPUT_ROLES, so a multi-line composer never
        # reaches the probe. That is the safe direction, and it is why the guard
        # above is belt-and-braces rather than the only thing standing there.
        r = self.fields(node("TextView", "내용 입력하기", 10, 700, 300, 60))
        self.assertIn("inputs 0 (0 search)", r.stdout)


class TestSheetEscape(unittest.TestCase):
    """A sheet is not an alert. Suppressing it entirely trapped the loop inside.

    Lumping AXSheet in with AXAlert removed the plain 취소/Cancel that closes it,
    which is the one thing the contract promises stays available — so the loop
    was stuck in a sheet it was also forbidden to touch.
    """

    SHEET = ('<XCUIElementTypeSheet type="XCUIElementTypeSheet" label="옵션" name="옵션"'
             ' enabled="true" visible="true" x="0" y="400" width="375" height="412">'
             '{inner}</XCUIElementTypeSheet>')

    def sheet(self, inner: str):
        return wda(self.SHEET.format(inner=inner))

    def test_only_the_way_out_is_offered(self):
        r = self.sheet(node("Button", "취소", 20, 760, 335, 44)
                       + node("Button", "사진 보관함", 20, 600, 335, 44))
        self.assertIn("WARN: sheet on screen", r.stdout)
        self.assertIn("| 취소", r.stdout)
        self.assertNotIn("사진 보관함", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)

    def test_a_sheet_with_no_way_out_offers_nothing(self):
        r = self.sheet(node("Button", "삭제", 20, 600, 335, 44))
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_an_alert_still_suppresses_everything(self):
        r = wda('<XCUIElementTypeAlert type="XCUIElementTypeAlert" label="위치 접근"'
                ' name="위치 접근" enabled="true" visible="true" x="0" y="300"'
                f' width="375" height="200">{node("Button", "취소", 20, 440, 150, 44)}'
                '</XCUIElementTypeAlert>')
        self.assertIn("WARN: alert/sheet on screen", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)

    def test_system_consent_vocabulary_wins_over_the_sheet_path(self):
        # An ATT prompt reported as a sheet must not hand back "Allow".
        r = self.sheet(node("Button", "Allow", 20, 600, 335, 44)
                       + node("Button", "취소", 20, 760, 335, 44))
        self.assertIn("WARN: alert/sheet on screen", r.stdout)
        self.assertIn("OK: 0 tappable, 0 withheld", r.stdout)


class TestLeavingTheApp(unittest.TestCase):
    """Leaving for another app was detected only AFTER the tap.

    Recovery works, but the exit still costs a tap, a settle, a wasted capture,
    and whatever the other app did on open — a deep link can act.
    """

    def test_app_switch_labels_are_withheld(self):
        # Korean particles attach to the preceding word with no space, so an
        # \\s-anchored pattern matches none of these.
        for label in ("Instagram으로 전환", "App Store에서 열기", "브라우저에서 보기",
                      "Open in Safari", "Switch to Threads", "Continue in Chrome"):
            with self.subTest(label=label):
                r = idb([ROOT, el(label, 0, 200)])
                self.assertIn("OK: 0 tappable, 1 withheld", r.stdout)
                self.assertIn("effect=leaving-app", r.stdout)

    def test_labels_that_only_look_like_a_switch_are_navigation(self):
        r = idb([ROOT, el("전환 안내", 0, 200), el("열기", 0, 260), el("홈", 0, 320)])
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)


class TestChromeFingerprintIdentity(unittest.TestCase):
    """Structural identity for apps that report no structure.

    `_node_identity` ignores AXOther on purpose, so a custom-rendered app had
    nothing left to hash — measured on zeta, its ranking and contest screens
    both produced sha1(""), and home and the creator tab produced one digest
    between them. statekey is layered on top, so a real transition recorded
    `changed=false` and coverage, resume and the graph merged unrelated screens.
    """

    def custom(self, *labels: str, extra: str = "") -> str:
        # A crowd of unnamed boxes, which is what a custom renderer emits.
        return extra + "".join(
            node("Other", lab, 10 + 60 * i, 68, 50, 34) for i, lab in enumerate(labels))

    def key(self, inner: str) -> str:
        out = wda(inner, mode="nodekey").stdout
        return next(l.split()[-1] for l in out.splitlines() if l.startswith("INFO: nodekey"))

    def test_screens_with_different_chrome_are_different_nodes(self):
        ranking = self.key(self.custom("트렌딩", "베스트", "신작", "전체", "홈", "대화"))
        contest = self.key(self.custom("연애", "성장", "미스터리", "전체", "홈", "대화"))
        self.assertNotEqual(ranking, contest)

    def test_scrolling_does_not_make_a_new_node(self):
        # The chrome stays; only the long content labels change.
        chrome = ("추천", "스토리챗", "비주얼", "홈", "대화", "만들기")
        top = self.key(self.custom(*chrome, extra=node("Other", "23.4만 어떤 긴 카드 제목", 16, 300, 177, 300)))
        down = self.key(self.custom(*chrome, extra=node("Other", "43.7만 완전히 다른 카드", 16, 300, 177, 300)))
        self.assertEqual(top, down)

    def test_an_app_that_reports_roles_keeps_its_identity(self):
        # No re-keying of existing graphs or logs. Measured, a role-reporting
        # screen carries 6-30 named leaves against 0-3 unnamed, so a handful of
        # decorative boxes never flips it into the fallback.
        rich = "".join(node("Button", f"버튼{i}", 20, 100 + 50 * i, 299, 40)
                       for i in range(8))
        before = self.key(rich)
        after = self.key(rich + "".join(
            node("Other", f"칩{i}", 10 + 40 * i, 60, 30, 24) for i in range(3)))
        self.assertEqual(before, after)

    def test_a_sparse_screen_is_not_treated_as_custom_rendered(self):
        # An empty state has no crowd of unnamed boxes to disambiguate.
        self.assertNotIn("chrome:", wda(node("Other", "홈", 28, 774, 48, 39),
                                        mode="nodekey").stdout)


class TestChromeFingerprintEdges(unittest.TestCase):
    """Where the fingerprint must NOT move, and where it must."""

    def key(self, inner: str) -> str:
        out = wda(inner, mode="nodekey").stdout
        return next(l.split()[-1] for l in out.splitlines() if l.startswith("INFO: nodekey"))

    def custom(self, *labels: str) -> str:
        return "".join(node("Other", lab, 10 + 55 * i, 68, 50, 34)
                       for i, lab in enumerate(labels))

    def test_a_badge_count_does_not_make_a_new_screen(self):
        # An unread badge ticking 9 → 10, a page indicator 12 / 80, a cart
        # count: readings, not chrome. Hashing them re-keyed the same screen.
        for before, after in (("9", "10"), ("12 / 80", "13 / 80"), ("5/8", "6/8"),
                              ("23.4만", "23.5만")):
            with self.subTest(counter=before):
                a = self.key(self.custom("홈", "대화", "만들기", "마이페이지", "추천", before))
                b = self.key(self.custom("홈", "대화", "만들기", "마이페이지", "추천", after))
                self.assertEqual(a, b)

    def test_a_category_name_still_counts_as_chrome(self):
        # `Electronics` is 11 characters — a tighter cap dropped exactly the
        # labels that separate one category screen from another.
        a = self.key(self.custom("Home", "Search", "Cart", "Profile", "All", "Electronics"))
        b = self.key(self.custom("Home", "Search", "Cart", "Profile", "All", "Home Garden"))
        self.assertNotEqual(a, b)

    def test_stray_named_elements_do_not_switch_the_fallback_off(self):
        # The ratio has to weigh the same population on both sides. Counting
        # every role element against only the visible labelled leaves let two
        # stray AXStaticText turn the fallback off and merge the screens.
        stray = node("StaticText", "제목", 20, 20, 100, 20) + node("StaticText", "부제", 20, 44, 100, 20)
        a = self.key(stray + self.custom("트렌딩", "베스트", "신작", "전체", "홈"))
        b = self.key(stray + self.custom("연애", "성장", "미스터리", "전체", "홈"))
        self.assertNotEqual(a, b)


class TestSheetEscapeOnFlatDumps(unittest.TestCase):
    def test_a_flat_dump_still_finds_the_way_out(self):
        # idb reports a flat array: every element is depth 0, so ancestry finds
        # nothing and descendant-scoping alone left the sheet with no exit.
        r = idb([
            el("App", 0, 0, 393, 852, role="AXApplication"),
            el("옵션", 0, 440, 393, 412, role="AXSheet"),
            el("취소", 20, 780, 353, 44),
            el("사진 보관함", 20, 500, 353, 44),
        ])
        self.assertIn("WARN: sheet on screen", r.stdout)
        self.assertIn("| 취소", r.stdout)
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)


class TestLeavingTheAppPrecision(unittest.TestCase):
    def test_real_handoff_ctas_are_withheld(self):
        for label in ("Watch on YouTube", "View on Instagram", "Listen on Spotify",
                      "Continue in Chrome", "Instagram으로 전환", "브라우저에서 보기"):
            with self.subTest(label=label):
                self.assertIn("effect=leaving-app", idb([ROOT, el(label, 0, 200)]).stdout)

    def test_screens_that_merely_name_a_browser_are_navigation(self):
        # A bare brand word blocked in-app screens: `Safari 사용법` is a help
        # page, `Browser history` is a list.
        r = idb([ROOT, el("Safari 사용법", 0, 200), el("Browser history", 0, 260),
                 el("열기", 0, 320)])
        self.assertIn("OK: 3 tappable, 0 withheld", r.stdout)


class TestNumericChromeIsNormalised(unittest.TestCase):
    def key(self, inner: str) -> str:
        out = wda(inner, mode="nodekey").stdout
        return next(l.split()[-1] for l in out.splitlines() if l.startswith("INFO: nodekey"))

    def custom(self, *labels: str) -> str:
        return "".join(node("Other", lab, 10 + 55 * i, 68, 50, 34)
                       for i, lab in enumerate(labels))

    def test_how_many_numeric_chips_still_counts(self):
        # Dropping numbers outright lost the only thing separating a subway
        # app's line tabs. Normalising keeps the structure, not the reading.
        one = self.key(self.custom("홈", "대화", "만들기", "설정", "전체", "1"))
        three = self.key(self.custom("홈", "대화", "만들기", "설정", "전체", "1", "2", "9"))
        self.assertNotEqual(one, three)

    def test_but_the_value_does_not(self):
        a = self.key(self.custom("홈", "대화", "만들기", "설정", "전체", "1", "2", "9"))
        b = self.key(self.custom("홈", "대화", "만들기", "설정", "전체", "3", "4", "7"))
        self.assertEqual(a, b)


class TestInAppViewSwitchIsNotLeaving(unittest.TestCase):
    def test_changing_the_view_is_navigation(self):
        for label in ("목록으로 전환", "캘린더로 전환", "Switch to List", "View in Calendar"):
            with self.subTest(label=label):
                self.assertNotIn("leaving-app", idb([ROOT, el(label, 0, 200)]).stdout)

    def test_handing_off_to_another_app_is_still_withheld(self):
        for label in ("Instagram으로 전환", "Watch on YouTube", "Open in Safari"):
            with self.subTest(label=label):
                self.assertIn("effect=leaving-app", idb([ROOT, el(label, 0, 200)]).stdout)


class TestSheetEscapeProvenance(unittest.TestCase):
    def test_the_way_out_is_not_a_label_guess(self):
        # Marked `source=label` it was refused by the mechanical gate, which
        # shut the blind loop inside a sheet it was also forbidden to touch.
        r = wda('<XCUIElementTypeSheet type="XCUIElementTypeSheet" label="옵션" name="옵션"'
                ' enabled="true" visible="true" x="0" y="400" width="375" height="412">'
                + node("Button", "취소", 20, 760, 335, 44)
                + '</XCUIElementTypeSheet>')
        self.assertIn("source=escape", r.stdout)
