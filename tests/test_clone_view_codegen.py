"""clone_view_codegen.py — the measured first pass of a reproduced screen.

The generator exists because Step 5 used to start from an empty placeholder, so
`verify` reported the identical "every element missing" for every screen and the
author could not tell which ones were close. These tests fix the two properties
that make the generated pass trustworthy: it emits one node per measured
element, and it never overwrites a screen a human has taken over.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "clone_view_codegen.py"
_spec = importlib.util.spec_from_file_location("clone_view_codegen", SCRIPT)
codegen = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(codegen)


MEASUREMENT = {
    "screen": {"points": {"width": 375.0, "height": 812.0},
               "pixels": {"width": 1125, "height": 2436}, "scale": 3.0},
    "palette": [{"count": 100, "hex": "#101010"}, {"count": 5, "hex": "#FFFFFF"}],
    "elements": [
        {"role": "AXApplication", "label": "Threads", "enabled": True, "depth": 1,
         "frame": {"x": 0.0, "y": 0.0, "width": 375.0, "height": 812.0},
         "colors": {"background": "#101010", "fill": "#101010"}},
        {"role": "AXStaticText", "label": 'he said "hi"\\back', "enabled": True, "depth": 2,
         "frame": {"x": 60.0, "y": 121.0, "width": 112.0, "height": 19.0},
         "colors": {"background": "#101010", "foreground": "#F3F6F7"},
         "text": {"estimatedPointSize": 14.1, "styleSize": 15}},
        {"role": "AXOther", "label": 'he said "hi"\\back', "enabled": True, "depth": 2,
         "frame": {"x": 60.0, "y": 121.0, "width": 112.0, "height": 19.0},
         "colors": {"background": "#101010", "fill": "#101010"}},
        {"role": "AXImage", "label": "", "enabled": True, "depth": 3,
         "frame": {"x": 8.0, "y": 120.0, "width": 44.0, "height": 44.0},
         "colors": {"background": "#101010", "fill": "#F3F6F7"}},
        {"role": "AXButton", "label": "검색", "enabled": True, "depth": 3,
         "frame": {"x": 335.0, "y": 59.0, "width": 24.0, "height": 24.0},
         "colors": {"background": "#101010", "fill": "#101010"}},
    ],
}


def elements_of(view: Path) -> list[dict]:
    """The records the generated view actually ships.

    The view carries its elements as a JSON array in a Swift raw string literal
    (a big Swift array literal cost minutes of type-checking). Decoding it here
    means these tests assert on the data the app decodes, not on a substring of
    the source that happens to spell it.
    """
    source = view.read_text(encoding="utf-8")
    found = re.search(r'cloneElements\(###"(.*)"###\)', source, re.S)
    assert found, f"no element JSON in {view.name}"
    return json.loads(found.group(1))


def workspace(directory: Path, views: dict[str, str], flow_lines: list[dict]) -> None:
    (directory / "screens").mkdir(parents=True, exist_ok=True)
    (directory / "screens" / "auto-0001.json").write_text(
        json.dumps(MEASUREMENT), encoding="utf-8")
    (directory / "views.json").write_text(
        json.dumps({"version": 1, "views": views}), encoding="utf-8")
    (directory / "flow.jsonl").write_text(
        "\n".join(json.dumps(line) for line in flow_lines) + "\n", encoding="utf-8")


def generate(directory: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), str(directory)],
                          capture_output=True, text=True)


class TestGeneratedView(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        workspace(self.root, {"s1": "Auto0001View"},
                  [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
        self.addCleanup(self._tmp.cleanup)

    def test_every_measured_element_becomes_one_node(self):
        self.assertEqual(generate(self.root).returncode, 0)
        records = elements_of(self.root / "Sources" / "Auto0001View.swift")
        # One record per element — the structural diff needs a rendered
        # counterpart for each, and a container it skipped is a missing element.
        self.assertEqual(len(records), len(MEASUREMENT["elements"]))

    def test_labels_survive_encoding(self):
        generate(self.root)
        records = elements_of(self.root / "Sources" / "Auto0001View.swift")
        self.assertIn('he said "hi"\\back', [record["label"] for record in records])

    def test_the_root_escapes_the_safe_area(self):
        # Without this every measured y renders 8pt low — exactly the structural
        # tolerance, so each screen sits on the edge of "moved".
        generate(self.root)
        swift = (self.root / "Sources" / "Auto0001View.swift").read_text(encoding="utf-8")
        self.assertIn(".ignoresSafeArea()", swift)

    def test_only_measured_type_is_drawn(self):
        """A control's own label is not written on it.

        Tried and measured on 2026-08-23: no pixel gain, and it wrote
        accessibility prose across icons (Threads labels a 37x34pt heart
        "좋아요. 226명이 이 게시물을 좋아합니다."). Every string it appeared to
        add is already drawn from a measured AXStaticText on the same screen.
        """
        generate(self.root)
        drawn = [record.get("text") for record in
                 elements_of(self.root / "Sources" / "Auto0001View.swift")]
        # Drawn once — the wrapper repeating its child's label must not double it.
        self.assertEqual(drawn.count('he said "hi"\\back'), 1)
        # A control with no measured type stays a shape.
        self.assertNotIn("검색", drawn)
        self.assertNotIn("Threads", drawn)

    def test_a_container_filled_with_the_background_paints_nothing(self):
        generate(self.root)
        fills = {record.get("fill") for record in
                 elements_of(self.root / "Sources" / "Auto0001View.swift")}
        self.assertNotIn("#101010", fills)
        self.assertIn("#F3F6F7", fills)

    def test_a_runtime_file_is_emitted_alongside(self):
        generate(self.root)
        self.assertTrue((self.root / "Sources" / codegen.RUNTIME).is_file())


class TestInteractionLayer(unittest.TestCase):
    """Taps live above the replay, not inside it.

    Making 166 stacked, overlapping replayed elements individually tappable
    produced controls the accessibility tree placed correctly and no touch could
    reach (measured 2026-08-23). One target per observed action, drawn last.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        workspace(self.root, {"s1": "Auto0001View", "s2": "Auto0002View"}, [
            {"type": "screen", "statekey": "s1", "name": "auto-0001"},
            {"type": "screen", "statekey": "s2", "name": "auto-0001"},
            {"type": "tap", "from_statekey": "s1", "to_statekey": "s2",
             "label": "검색", "changed": "true"},
        ])
        generate(self.root)
        self.swift = (self.root / "Sources" / "Auto0001View.swift").read_text(encoding="utf-8")
        self.runtime = (self.root / "Sources" / codegen.RUNTIME).read_text(encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def test_the_replay_itself_never_takes_a_touch(self):
        self.assertIn(".allowsHitTesting(false)", self.runtime)

    def test_the_action_layer_is_drawn_after_the_replay(self):
        # Each layer (scrolling or fixed) draws its picture first and its tap
        # targets last, so the targets sit on top.
        first_picture = self.swift.index("CloneElementView(element: element)")
        first_targets = self.swift.index("CloneActionLayer(")
        self.assertLess(first_picture, first_targets)

    def test_a_target_is_addressable_by_identifier(self):
        # A label repeats down the container chain, and a driver asked to tap a
        # repeated label refuses outright unless one element exposes AXUniqueId.
        self.assertIn("CLONE_ACTION_ID)\n                                         "
                      "+ (element.action ?? \"\")", self.runtime)

    def test_targets_smaller_than_a_touch_are_grown(self):
        self.assertIn("max(element.w, CLONE_MIN_TAP)", self.runtime)
        self.assertIn("max(element.h, CLONE_MIN_TAP)", self.runtime)


class TestActionsAbsentFromTheCapture(unittest.TestCase):
    """A live feed is different content every capture.

    The run taps a post; the measurement the screen is reproduced from was taken
    at another moment and does not contain it. Without a target at the recorded
    tap point the reproduction has nothing to tap at all — measured 2026-08-23,
    4 of 42 transitions.
    """

    def workspace_with_absent_label(self, root: Path, views: dict[str, str]) -> None:
        workspace(root, views, [
            {"type": "screen", "statekey": "s1", "name": "auto-0001"},
            {"type": "screen", "statekey": "s2", "name": "auto-0001"},
            {"type": "tap", "from_statekey": "s1", "to_statekey": "s2",
             "label": "a post that has scrolled away", "x": "120", "y": "300",
             "changed": "true"},
        ])

    def test_a_target_is_synthesised_at_the_recorded_tap_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace_with_absent_label(root, {"s1": "Auto0001View", "s2": "Auto0002View"})
            generate(root)
            records = elements_of(root / "Sources" / "Auto0001View.swift")
            target = [record for record in records
                      if record.get("action") == "a post that has scrolled away"]
            self.assertEqual(len(target), 1)
            # Centred on the tap point, at the 44pt minimum.
            self.assertEqual(
                {key: target[0][key] for key in ("x", "y", "w", "h")},
                {"x": 98.0, "y": 278.0, "w": 44.0, "h": 44.0})

    def test_synthesised_targets_are_counted_and_named(self):
        # A target the capture never contained is weaker evidence than one it
        # did. Silence here would let "every transition wired" quietly include
        # edges that only pass because of a square placed at a logged
        # coordinate — the three-way pass/fail/unchecked collapse this repo has
        # been bitten by before.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace_with_absent_label(root, {"s1": "Auto0001View", "s2": "Auto0002View"})
            result = generate(root)
            self.assertIn("1 tap target(s) synthesised", result.stdout)
            self.assertIn("a post that has scrolled away", result.stdout)

    def test_a_synthesised_target_is_distinguishable_in_the_tree(self):
        # The walk attributes a pass to it by identifier prefix, so a driver can
        # tell the two apart without reading this script's output.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace_with_absent_label(root, {"s1": "Auto0001View", "s2": "Auto0002View"})
            generate(root)
            records = elements_of(root / "Sources" / "Auto0001View.swift")
            self.assertTrue(any(record.get("synthetic") for record in records))
            runtime = (root / "Sources" / codegen.RUNTIME).read_text(encoding="utf-8")
            self.assertIn("CLONE_SYNTH_ID", runtime)

    def test_nothing_is_reported_when_every_label_is_in_the_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View", "s2": "Auto0002View"}, [
                {"type": "screen", "statekey": "s1", "name": "auto-0001"},
                {"type": "screen", "statekey": "s2", "name": "auto-0001"},
                {"type": "tap", "from_statekey": "s1", "to_statekey": "s2",
                 "label": "검색", "x": "1", "y": "2", "changed": "true"},
            ])
            result = generate(root)
            self.assertNotIn("synthesised", result.stdout)

    def test_a_screen_with_no_measurement_still_carries_its_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View", "s2": "Auto0002View"}, [
                {"type": "screen", "statekey": "s1", "name": "auto-0001"},
                {"type": "screen", "statekey": "s2", "name": "missing-capture"},
                {"type": "tap", "from_statekey": "s2", "to_statekey": "s1",
                 "label": "돌아가기", "x": "30", "y": "70", "changed": "true"},
            ])
            generate(root)
            view = root / "Sources" / "Auto0002View.swift"
            swift = view.read_text(encoding="utf-8")
            self.assertIn("no measurement", swift)
            # It has no picture, but the flow must still work through it.
            self.assertIn("돌아가기",
                          {record.get("action") for record in elements_of(view)})
            self.assertIn("CloneActionLayer", swift)


class TestCropPlacement(unittest.TestCase):
    """A crop is drawn where it was cut from, not stretched over its element.

    An element can extend past the screen — Threads' AdditionalDimmingOverlay is
    615x286 starting at x=-120 — and the crop is clamped to the capture.
    Stretching it back over the whole frame magnified the pixels inside it, and
    a 14pt line of the feed came out as a banner. Measured 2026-08-23.
    """

    def test_the_picture_uses_the_cropped_region(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View"},
                      [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
            (root / "assets").mkdir(parents=True, exist_ok=True)
            (root / "assets" / "manifest.json").write_text(json.dumps({"assets": [{
                "sourceMeasurement": str(root / "screens" / "auto-0001.json"),
                "sha256": "deadbeef",
                "pointToPixelScale": 3.0,
                "pixelBounds": {"x": 0, "y": 30, "width": 1125, "height": 300},
                "element": {"index": 2, "role": "AXImage", "label": "",
                            "frame": {"x": -120.0, "y": 10.0,
                                      "width": 615.0, "height": 286.0}},
            }]}), encoding="utf-8")
            generate(root)
            records = elements_of(root / "Sources" / "Auto0001View.swift")
            picture = [r for r in records if r.get("asset") == "deadbeef"]
            self.assertEqual(len(picture), 1)
            self.assertEqual({key: picture[0][key] for key in ("x", "y", "w", "h")},
                             {"x": 0.0, "y": 10.0, "w": 375.0, "h": 100.0})

    def test_the_element_keeps_its_own_frame_for_the_structural_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View"},
                      [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
            generate(root)
            records = elements_of(root / "Sources" / "Auto0001View.swift")
            # Same count as the measurement when nothing was cropped.
            self.assertEqual(len(records), len(MEASUREMENT["elements"]))


class TestOrphanShards(unittest.TestCase):
    """A modal's uncovered regions must not ship glyph shards.

    iOS hides everything behind a sheet from the accessibility tree, so the
    background has no measured elements and the uncovered-region pass slices its
    running text into glyph-sized crops. Painted back they read as a layout bug
    — and the structural diff (label→frame matching) still passes. Measured
    2026-08-23 on Threads' post-options sheet: shards of "87", "열심", "점프".
    """

    def _generate_with_uncovered(self, regions):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View"},
                      [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
            (root / "assets").mkdir(parents=True, exist_ok=True)
            (root / "assets" / "manifest.json").write_text(json.dumps({"assets": [
                {"sourceMeasurement": str(root / "screens" / "auto-0001.json"),
                 "sha256": sha,
                 "element": {"role": "uncoveredRegion", "frame": frame}}
                for sha, frame in regions
            ]}), encoding="utf-8")
            generate(root)
            return elements_of(root / "Sources" / "Auto0001View.swift")

    def test_a_glyph_sized_crop_no_element_witnesses_is_dropped(self):
        # y=700 is far from every measured element in MEASUREMENT.
        records = self._generate_with_uncovered([
            ("shard", {"x": 200.0, "y": 700.0, "width": 16.0, "height": 16.0}),
        ])
        self.assertEqual([r for r in records if r.get("asset") == "shard"], [])

    def test_a_crop_bigger_than_a_glyph_is_kept(self):
        records = self._generate_with_uncovered([
            ("avatar", {"x": 200.0, "y": 700.0, "width": 48.0, "height": 48.0}),
        ])
        self.assertEqual(len([r for r in records if r.get("asset") == "avatar"]), 1)

    def test_a_small_crop_inside_a_measured_control_is_kept(self):
        # Overlaps the 24x24 "검색" button at (335, 59) — a real icon.
        records = self._generate_with_uncovered([
            ("icon", {"x": 336.0, "y": 60.0, "width": 20.0, "height": 20.0}),
        ])
        self.assertEqual(len([r for r in records if r.get("asset") == "icon"]), 1)


class TestScrolling(unittest.TestCase):
    """The content scrolls; the chrome does not.

    A replayed screen was a fixed stack, so a swipe did nothing at all — the
    reproduction read as broken before anyone looked at a colour. The tree
    already keeps the top bar and tab bar OUTSIDE the feed, so the two are
    rendered as what they are.
    """

    def build(self, root: Path):
        measurement = {
            "screen": {"points": {"width": 375.0, "height": 812.0},
                       "pixels": {"width": 1125, "height": 2436}, "scale": 3.0},
            "palette": [{"count": 100, "hex": "#101010"}],
            "elements": [
                {"role": "AXApplication", "label": "", "parent": -1, "depth": 1,
                 "frame": {"x": 0.0, "y": 0.0, "width": 375.0, "height": 812.0}, "colors": {}},
                {"role": "AXCollectionView", "label": "feed", "parent": 0, "depth": 2,
                 "frame": {"x": 0.0, "y": 100.0, "width": 375.0, "height": 600.0}, "colors": {}},
                {"role": "AXStaticText", "label": "첫 글", "parent": 1, "depth": 3,
                 "frame": {"x": 16.0, "y": 120.0, "width": 200.0, "height": 20.0},
                 "colors": {"foreground": "#FFFFFF"}, "text": {"estimatedPointSize": 14.0}},
                {"role": "AXStaticText", "label": "먼 글", "parent": 1, "depth": 3,
                 "frame": {"x": 16.0, "y": 900.0, "width": 200.0, "height": 20.0},
                 "colors": {"foreground": "#FFFFFF"}, "text": {"estimatedPointSize": 14.0}},
                {"role": "AXButton", "label": "검색", "parent": 0, "depth": 2,
                 "frame": {"x": 335.0, "y": 59.0, "width": 24.0, "height": 24.0}, "colors": {}},
            ],
        }
        (root / "screens").mkdir(parents=True, exist_ok=True)
        (root / "screens" / "auto-0001.json").write_text(json.dumps(measurement), encoding="utf-8")
        (root / "views.json").write_text(json.dumps({"version": 1, "views": {"s1": "Auto0001View"}}),
                                         encoding="utf-8")
        (root / "flow.jsonl").write_text(
            json.dumps({"type": "screen", "statekey": "s1", "name": "auto-0001"}) + "\n",
            encoding="utf-8")
        generate(root)
        return (root / "Sources" / "Auto0001View.swift").read_text(encoding="utf-8")

    def test_the_feed_is_inside_a_scroll_area_sized_to_its_content(self):
        with tempfile.TemporaryDirectory() as directory:
            swift = self.build(Path(directory))
            self.assertIn("CloneScrollArea(viewport: CGSize(width: 375.0, height: 600.0)", swift)
            # Content reaches y=920 inside a container starting at y=100.
            self.assertIn("content: CGSize(width: 375.0, height: 820.0)", swift)

    def test_the_drag_lives_on_the_screen_root_not_on_the_scroll_area(self):
        # A gesture on the full-screen scroll area — a sibling drawn under the
        # chrome — stole the tab bar's taps (measured 2026-08-23: remove it and
        # the tab bar works again). On the root, an ancestor of every target, a
        # simultaneousGesture composes with their taps instead of competing.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            swift = self.build(root)
            runtime = (root / "Sources" / codegen.RUNTIME).read_text(encoding="utf-8")
            self.assertIn(".modifier(CloneScrollDrag(offset: $scrollOffset, maxOffset: 220.0))", swift)
            area = runtime[runtime.index("struct CloneScrollArea"):runtime.index("struct CloneScrollDrag")]
            self.assertNotIn("Gesture", area)
            self.assertNotIn("ScrollView(", runtime)

    def test_a_platform_scroll_view_is_never_emitted(self):
        # Under the iOS 26 simulator a ScrollView beneath fixed chrome in a
        # ZStack swallowed that chrome's taps near the screen edges.
        with tempfile.TemporaryDirectory() as directory:
            swift = self.build(Path(directory))
            self.assertNotIn("ScrollView(", swift)

    def test_scrolling_elements_are_re_origined_to_the_container(self):
        with tempfile.TemporaryDirectory() as directory:
            self.build(Path(directory))
            records = elements_of(Path(directory) / "Sources" / "Auto0001View.swift")
            inside = {r["label"]: r for r in records if r.get("scroll") == 1}
            outside = {r["label"]: r for r in records if r.get("scroll") != 1}
            self.assertEqual(inside["첫 글"]["y"], 20.0)   # 120 - 100
            self.assertIn("검색", outside)                # chrome stays fixed
            self.assertEqual(outside["검색"]["y"], 59.0)

    def test_a_screen_without_a_scroll_container_has_no_scroll_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View"},
                      [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
            generate(root)
            swift = (root / "Sources" / "Auto0001View.swift").read_text(encoding="utf-8")
            self.assertNotIn("CloneScrollArea(", swift)
            self.assertNotIn("CloneScrollDrag(", swift)


class TestOwnership(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        workspace(self.root, {"s1": "Auto0001View"},
                  [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
        self.addCleanup(self._tmp.cleanup)

    def test_a_hand_authored_view_is_never_clobbered(self):
        target = self.root / "Sources" / "Auto0001View.swift"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// mine\nstruct Auto0001View {}\n", encoding="utf-8")
        result = generate(self.root)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "// mine\nstruct Auto0001View {}\n")
        self.assertIn("kept hand-authored Auto0001View", result.stdout)

    def test_a_previously_generated_view_is_regenerated(self):
        generate(self.root)
        target = self.root / "Sources" / "Auto0001View.swift"
        target.write_text(codegen.MARKER + "\n// stale\n", encoding="utf-8")
        generate(self.root)
        self.assertEqual(len(elements_of(target)), len(MEASUREMENT["elements"]))


class TestUnmeasuredState(unittest.TestCase):
    def test_a_mapped_state_without_a_measurement_still_gets_its_type(self):
        # device_render.sh compiles Sources/ as one unit and the generated router
        # names every mapped view, so a missing type fails the build for every
        # OTHER screen — 30 identical failures with the wrong cause named.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View", "s2": "Auto0002View"},
                      [{"type": "screen", "statekey": "s1", "name": "auto-0001"}])
            result = generate(root)
            self.assertEqual(result.returncode, 0)
            self.assertIn("no measurement", result.stderr)
            self.assertIn("Auto0002View", result.stderr)
            swift = (root / "Sources" / "Auto0002View.swift").read_text(encoding="utf-8")
            self.assertIn("struct Auto0002View: View", swift)


class TestObservedActions(unittest.TestCase):
    def test_a_label_this_run_saw_move_the_app_becomes_a_tap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View", "s2": "Auto0002View"}, [
                {"type": "screen", "statekey": "s1", "name": "auto-0001"},
                {"type": "screen", "statekey": "s2", "name": "auto-0001"},
                {"type": "tap", "from_statekey": "s1", "to_statekey": "s2",
                 "label": "검색", "changed": "true"},
            ])
            generate(root)
            actions = {record.get("action") for record in
                       elements_of(root / "Sources" / "Auto0001View.swift")}
            self.assertIn("검색", actions)

    def test_a_tap_that_changed_nothing_is_not_wired(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace(root, {"s1": "Auto0001View"}, [
                {"type": "screen", "statekey": "s1", "name": "auto-0001"},
                {"type": "tap", "from_statekey": "s1", "to_statekey": "s2",
                 "label": "검색", "changed": "false"},
            ])
            generate(root)
            actions = {record.get("action") for record in
                       elements_of(root / "Sources" / "Auto0001View.swift")}
            self.assertEqual(actions, {None})


if __name__ == "__main__":
    unittest.main()
