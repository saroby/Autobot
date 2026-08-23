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
        return subprocess.run(
            ["python3", str(SCRIPT), mode, fixture],
            capture_output=True, text=True,
        )
    finally:
        Path(fixture).unlink()


def idb(elements: list[dict], mode: str = "candidates") -> subprocess.CompletedProcess:
    return run(mode, json.dumps(elements), ".json")


def idb_probing(elements: list[dict]) -> subprocess.CompletedProcess:
    """`candidates` with CLONE_PROBE_SWITCHES=1 — switches become reversible taps."""
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

    def test_describing_a_screen_is_still_navigation(self):
        """The leading-clause check must not swallow ordinary navigation.

        `답글 달기` opens the reply composer (a screen); the publish button is
        `게시`. `좋아요한 글` is the profile's liked-posts tab, not the like button.
        """
        labels = ["답글 달기. 35명이 이 게시물에 답글을 달았습니다.",
                  "좋아요한 글", "게시 옵션", "게시물 만들기", "내가 팔로우하는 사람"]
        r = idb([ROOT] + [el(label, 0, 200 + 40 * i) for i, label in enumerate(labels)])
        self.assertIn(f"OK: {len(labels)} tappable, 0 withheld", r.stdout)
        self.assertNotIn("category=state-changing", r.stdout)

    def test_follow_suggestions_navigation_is_not_misclassified(self):
        r = idb([ROOT, el("팔로우 추천", 0, 200), el("Follow suggestions", 0, 260)])
        self.assertIn("OK: 2 tappable, 0 withheld", r.stdout)
        self.assertNotIn("category=state-changing", r.stdout)

    def test_switch_is_withheld_by_default(self):
        # The tree cannot tell a local toggle from an account setting, and the
        # bar here is no account write at all — net-zero included.
        r = idb([ROOT, el("비공개 프로필", 0, 200, role="AXSwitch")])
        self.assertIn("WARN: withheld", r.stdout)
        self.assertIn("effect=toggle", r.stdout)

    def test_switch_is_a_reversible_tap_when_probing_is_on(self):
        # CLONE_PROBE_SWITCHES=1: exploration taps it and flips it back in the
        # same step. Only labels that reach the server stay withheld.
        r = idb_probing([ROOT, el("비공개 프로필", 0, 200, role="AXSwitch")])
        self.assertIn("OK: 1 tappable, 0 withheld", r.stdout)
        self.assertIn("category=reversible | effect=toggle", r.stdout)

    def test_two_switches_on_one_screen_are_two_behaviors(self):
        r = idb_probing([ROOT, el("알림", 0, 200, role="AXSwitch"), el("다크 모드", 0, 260, role="AXSwitch")])
        behaviors = {line.split("behavior=")[1].split(" | ")[0]
                     for line in r.stdout.splitlines() if "candidate-meta" in line}
        self.assertEqual(len(behaviors), 2, msg=r.stdout)

    def test_switch_with_a_subscription_label_stays_withheld_even_when_probing(self):
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
