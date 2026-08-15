"""device_flow.py — exploration coverage, resume, and the flow map, offline.

The log this reads is the only durable state of an exploration. On a real phone
the run ends early far more often than it completes (session timeout, lock
screen, login wall), so rebuilding the frontier from the log is not a nicety —
it is how a second run avoids starting over.

Coverage claims are pinned here for the same reason the SKILL counts missing
elements: silent truncation reads as "explored everything" when it wasn't.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "device_flow.py"
FLOW_SPEC = importlib.util.spec_from_file_location("device_flow_under_test", SCRIPT)
DEVICE_FLOW = importlib.util.module_from_spec(FLOW_SPEC)
assert FLOW_SPEC.loader is not None
FLOW_SPEC.loader.exec_module(DEVICE_FLOW)

TREE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<AppiumAUT>'
    '<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App" label="App"'
    ' enabled="true" visible="true" x="0" y="0" width="375" height="812">'
    '<XCUIElementTypeButton type="XCUIElementTypeButton" label="가" name="가" enabled="true"'
    ' visible="true" x="0" y="100" width="100" height="40"/>'
    '<XCUIElementTypeButton type="XCUIElementTypeButton" label="나" name="나" enabled="true"'
    ' visible="true" x="0" y="200" width="100" height="40"/>'
    '</XCUIElementTypeApplication></AppiumAUT>'
)


class FlowCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.tree = self.dir / "01-home.xml"
        self.tree.write_text(TREE, encoding="utf-8")
        self.log = self.dir / "flow.jsonl"
        self.addCleanup(self._dir.cleanup)

    def write(self, events: list[dict]) -> None:
        self.log.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                            encoding="utf-8")

    def run_flow(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", str(SCRIPT), *args], capture_output=True, text=True)

    def screen(self, node="n1", name="01-home", statekey=None, tree=None) -> dict:
        event = {"type": "screen", "node": node, "sig": "s1", "name": name,
                 "tree": str(tree or self.tree), "png": ""}
        if statekey is not None:
            event["statekey"] = statekey
        return event


class TestFrontier(FlowCase):
    def test_untapped_candidates_are_the_resume_queue(self):
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n2", "label": "가",
                     "x": "50", "y": "120", "changed": "true"}])
        r = self.run_flow("next", str(self.log))
        self.assertEqual(r.returncode, 0)
        self.assertIn("나", r.stdout)      # never tapped — still on the queue
        self.assertNotIn("| 가", r.stdout)  # already explored
        self.assertIn(str(self.tree), r.stdout)  # the tree to re-capture from

    def test_a_target_stays_explored_when_the_capture_drifts_a_pixel(self):
        # Live: the same screen reported its back button at (38,72) once and
        # (38,71) minutes later. On exact-coordinate matching that target would
        # be "unexplored" forever, and `next` would keep proposing a done tap.
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n2", "label": "가",
                     "x": "51", "y": "119", "changed": "true"}])   # candidate is (50,120)
        r = self.run_flow("next", str(self.log))
        self.assertNotIn("| 가", r.stdout)
        self.assertIn("나", r.stdout)

    def test_a_different_target_at_a_near_coordinate_is_not_confused(self):
        # Tolerance must not swallow a genuinely different control nearby.
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n2", "label": "다른것",
                     "x": "51", "y": "119", "changed": "true"}])
        self.assertIn("| 가", self.run_flow("next", str(self.log)).stdout)

    def test_a_fully_explored_screen_reports_an_empty_frontier(self):
        self.write([self.screen()] + [
            {"type": "tap", "from": "n1", "to": "n1", "label": lab, "x": "50", "y": str(y),
             "changed": "false"}
            for lab, y in (("가", 120), ("나", 220))])
        r = self.run_flow("next", str(self.log))
        self.assertIn("frontier empty", r.stdout)

    def test_duplicate_taps_do_not_inflate_coverage_denominator(self):
        self.write([self.screen()] + [
            {"type": "tap", "from": "n1", "to": "n2", "label": "가",
             "x": "50", "y": "120", "changed": "true"},
            {"type": "tap", "from": "n1", "to": "n2", "label": "가",
             "x": "50", "y": "120", "changed": "true"},
        ])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("1/2 explored", r.stdout)
        self.assertNotIn("2/3 explored", r.stdout)


class TestBehaviorClassFrontier(FlowCase):
    def threads_tree(self) -> Path:
        tree = self.dir / "threads-like.xml"
        rows = "".join(
            f'<XCUIElementTypeCell type="XCUIElementTypeCell" label="{user}" name="{user}"'
            f' enabled="true" visible="true" x="0" y="{y}" width="375" height="60">'
            f'<XCUIElementTypeButton type="XCUIElementTypeButton" label="팔로우" name="팔로우"'
            f' enabled="true" visible="true" x="290" y="{y + 10}" width="70" height="40"/>'
            f'</XCUIElementTypeCell>'
            for user, y in (("user.one", 100), ("user.two", 160))
        )
        tree.write_text(TREE.replace(
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="가" name="가" enabled="true"'
            ' visible="true" x="0" y="100" width="100" height="40"/>', "").replace(
            '<XCUIElementTypeButton type="XCUIElementTypeButton" label="나" name="나" enabled="true"'
            ' visible="true" x="0" y="200" width="100" height="40"/>', rows),
            encoding="utf-8")
        return tree

    def test_repeated_rows_report_raw_and_behavior_coverage(self):
        tree = self.threads_tree()
        self.write([self.screen(tree=tree)])
        stats = self.run_flow("stats", str(self.log))
        self.assertIn("targets 0/2 explored, 2 left", stats.stdout)
        self.assertIn("behavior classes 0/1 explored, 1 left", stats.stdout)
        self.assertIn("withheld state-changing 2 (not safe pending work)", stats.stdout)

        next_run = self.run_flow("next", str(self.log))
        self.assertEqual(next_run.stdout.count("INFO:   tap "), 1)
        self.assertNotIn("| 팔로우", next_run.stdout)

    def test_one_repeated_row_covers_behavior_but_not_raw_targets(self):
        tree = self.threads_tree()
        self.write([
            self.screen(tree=tree),
            {"type": "tap", "from": "n1", "to": "n1", "label": "user.one",
             "x": "187", "y": "130", "changed": "false"},
        ])
        stats = self.run_flow("stats", str(self.log))
        self.assertIn("targets 1/2 explored, 1 left", stats.stdout)
        self.assertIn("behavior classes 1/1 explored, 0 left", stats.stdout)
        self.assertIn("complete (behavior classes; 1 repeated raw targets unvisited)", stats.stdout)
        self.assertIn("frontier empty", self.run_flow("next", str(self.log)).stdout)

    def test_explicit_behavior_fingerprint_wins_over_coordinate_inference(self):
        behavior_for_na = hashlib.sha1("AXButton|navigation|나".encode()).hexdigest()[:12]
        self.write([
            self.screen(),
            {"type": "tap", "from": "n1", "to": "n1", "label": "가",
             "x": "50", "y": "120", "behavior": behavior_for_na,
             "changed": "false"},
        ])
        stats = self.run_flow("stats", str(self.log))
        self.assertIn("targets 1/2 explored, 1 left", stats.stdout)
        self.assertIn("behavior classes 1/2 explored, 1 left", stats.stdout)
        pending = self.run_flow("next", str(self.log)).stdout
        self.assertIn("| 가", pending)
        self.assertNotIn("| 나", pending)


class TestStateIdentity(FlowCase):
    def test_states_of_one_coarse_node_are_grouped_separately(self):
        self.write([
            self.screen(statekey="state-base", name="01-base"),
            {"type": "tap", "from": "n1", "to": "n1",
             "from_statekey": "state-base", "to_statekey": "state-focused",
             "label": "가", "x": "50", "y": "120", "changed": "true"},
            self.screen(statekey="state-focused", name="02-focused"),
        ])
        stats = self.run_flow("stats", str(self.log))
        self.assertIn("screens 2", stats.stdout)
        self.assertIn("targets 1/4 explored, 3 left", stats.stdout)
        self.assertIn("behavior classes 1/4 explored, 3 left", stats.stdout)
        self.assertNotIn("destination capture", stats.stdout)

        out = self.dir / "state-map.html"
        result = self.run_flow("map", str(self.log), str(out))
        self.assertIn("2 screens, 1 transitions", result.stdout)

    def test_state_screen_keeps_coarse_node_alongside_graph_key(self):
        event = self.screen(node="coarse-home", statekey="home-focused")
        rows = DEVICE_FLOW.frontier([event])
        self.assertEqual(rows[0]["key"], "home-focused")
        self.assertEqual(rows[0]["statekey"], "home-focused")
        self.assertEqual(rows[0]["node"], "coarse-home")

    def test_state_screen_without_coarse_node_is_rejected(self):
        event = self.screen(statekey="home-focused")
        del event["node"]
        self.write([event])
        result = self.run_flow("stats", str(self.log))
        self.assertEqual(result.returncode, 1)
        self.assertIn("screen event requires coarse node", result.stderr)

    def test_state_action_requires_both_statekey_endpoints(self):
        self.write([
            self.screen(statekey="state-base"),
            {"type": "tap", "from_statekey": "state-base", "from": "n1", "to": "n1",
             "label": "가", "x": "50", "y": "120", "changed": "false"},
        ])
        result = self.run_flow("stats", str(self.log))
        self.assertEqual(result.returncode, 1)
        self.assertIn("both from_statekey and to_statekey", result.stderr)

    def test_unofficial_state_aliases_are_rejected(self):
        event = self.screen()
        event["state"] = "home-focused"
        self.write([event])
        result = self.run_flow("stats", str(self.log))
        self.assertEqual(result.returncode, 1)
        self.assertIn("use statekey/from_statekey/to_statekey", result.stderr)

    def test_legacy_node_from_to_logs_remain_supported(self):
        self.write([
            self.screen(),
            {"type": "tap", "from": "n1", "to": "n1", "label": "가",
             "x": "50", "y": "120", "changed": "false"},
        ])
        stats = self.run_flow("stats", str(self.log))
        self.assertIn("screens 1", stats.stdout)
        self.assertIn("targets 1/2 explored, 1 left", stats.stdout)


class TestCoverage(FlowCase):
    def test_partial_coverage_is_stated_not_implied(self):
        self.write([self.screen()])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("0/2 explored", r.stdout)
        self.assertIn("partial", r.stdout)

    def test_taps_that_change_nothing_are_counted(self):
        # A target that goes nowhere is real flow data, not a failed tap.
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n1", "label": "가",
                     "x": "50", "y": "120", "changed": "false"}])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("no-op taps 1", r.stdout)

    def test_changed_destination_without_capture_is_incomplete(self):
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n2", "label": "가",
                     "x": "50", "y": "120", "changed": "true"}])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("destination capture", r.stdout)
        self.assertIn("incomplete", r.stdout)

    def test_changed_transition_to_existing_node_still_requires_new_capture(self):
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n1", "label": "가",
                     "x": "50", "y": "120", "changed": "true"}])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("destination capture", r.stdout)
        self.assertIn("incomplete", r.stdout)

    def test_a_missed_capture_is_repairable_by_a_later_capture(self):
        # A gap must never be a life sentence: the WARN tells the agent to
        # re-visit the destination and capture it, so a durable capture that
        # lands LATER in the log (after other taps) has to clear the gap.
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n2", "label": "가",
                     "x": "50", "y": "120", "changed": "true"},
                    {"type": "tap", "from": "n1", "to": "n2", "label": "나",
                     "x": "50", "y": "220", "changed": "true"},
                    self.screen(node="n2", name="02-detail")])
        r = self.run_flow("stats", str(self.log))
        self.assertNotIn("destination capture", r.stdout)
        self.assertNotIn("incomplete", r.stdout)

    def test_an_older_capture_never_satisfies_a_new_transition(self):
        self.write([self.screen(),
                    self.screen(node="n2", name="02-detail"),
                    {"type": "tap", "from": "n2", "to": "n1", "label": "가",
                     "x": "50", "y": "120", "changed": "true"}])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("destination capture", r.stdout)
        self.assertIn("incomplete", r.stdout)

    def test_an_unresolved_destination_is_cleared_by_a_capture_after_the_tap(self):
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "?", "label": "가",
                     "x": "50", "y": "120", "changed": "true"},
                    self.screen(node="n2", name="02-detail")])
        r = self.run_flow("stats", str(self.log))
        self.assertNotIn("no resolvable destination", r.stdout)
        self.assertNotIn("incomplete", r.stdout)

    def test_changed_swipe_without_a_followup_capture_is_incomplete(self):
        self.write([self.screen(),
                    {"type": "swipe", "from": "n1", "to": "n1",
                     "x1": "180", "y1": "700", "x2": "180", "y2": "200",
                     "changed": "true"}])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("destination capture", r.stdout)
        self.assertIn("incomplete", r.stdout)

    def test_scroll_captures_union_candidates_for_the_same_node(self):
        scrolled = self.dir / "02-home-scroll.xml"
        scrolled.write_text(
            TREE.replace(
                "</XCUIElementTypeApplication>",
                '<XCUIElementTypeButton type="XCUIElementTypeButton" label="다" name="다" '
                'enabled="true" visible="true" x="0" y="300" width="100" height="40"/>'
                "</XCUIElementTypeApplication>",
            ),
            encoding="utf-8",
        )
        capture = self.screen(node="n1", name="02-home-scroll")
        capture["tree"] = str(scrolled)
        self.write([self.screen(),
                    {"type": "swipe", "from": "n1", "to": "n1",
                     "x1": "180", "y1": "700", "x2": "180", "y2": "200",
                     "changed": "true"},
                    capture])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("0/3 explored", r.stdout)
        self.assertNotIn("incomplete", r.stdout)
        r = self.run_flow("next", str(self.log))
        self.assertIn("| 다", r.stdout)
        self.assertIn(str(scrolled), r.stdout)

    def test_missing_tree_is_incomplete(self):
        event = self.screen()
        event["tree"] = str(self.dir / "missing.xml")
        self.write([event])
        r = self.run_flow("stats", str(self.log))
        self.assertIn("no accessibility tree", r.stdout)
        self.assertIn("incomplete", r.stdout)


class TestMap(FlowCase):
    def test_the_map_names_what_was_not_explored(self):
        self.write([self.screen()])
        out = self.dir / "map.html"
        r = self.run_flow("map", str(self.log), str(out))
        self.assertEqual(r.returncode, 0)
        page = out.read_text(encoding="utf-8")
        self.assertIn("미탐험", page)
        self.assertIn("0/2", r.stdout + page.replace(" ", ""))

    def test_no_op_transitions_are_not_drawn_as_edges(self):
        self.write([self.screen(),
                    {"type": "tap", "from": "n1", "to": "n1", "label": "가",
                     "x": "50", "y": "120", "changed": "false"}])
        out = self.dir / "map.html"
        self.assertIn("0 transitions", self.run_flow("map", str(self.log), str(out)).stdout)

    def test_unexplored_targets_are_drawn_as_empty_nodes(self):
        self.write([self.screen()])
        out = self.dir / "map.html"
        self.run_flow("map", str(self.log), str(out))
        page = out.read_text(encoding="utf-8")
        # Two untapped candidates in the fixture → two blank nodes, each wired
        # back to the screen that offers it.
        self.assertEqual(page.count('class="node todo"'), 2)
        self.assertEqual(page.count('class="edge todo"'), 2)

    def test_nodes_do_not_overlap_and_edges_land_on_them(self):
        # The layout is computed here, not by a browser, so nothing else would
        # catch a geometry regression.
        self.write([self.screen()] + [self.screen(node=f"n{i}", name=f"s{i}") for i in range(2, 6)])
        out = self.dir / "map.html"
        self.run_flow("map", str(self.log), str(out))
        page = out.read_text(encoding="utf-8")
        boxes = [tuple(map(int, m)) for m in re.findall(
            r"left:(\d+)px; top:(\d+)px; width:(\d+)px; height:(\d+)px", page)]
        self.assertGreater(len(boxes), 4)
        for i, (ax, ay, aw, ah) in enumerate(boxes):
            for bx, by, bw, bh in boxes[i + 1:]:
                self.assertFalse(ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah,
                                 "two nodes overlap")
        anchors = {(x + w / 2, y + h) for x, y, w, h in boxes}
        anchors |= {(x + w / 2, y) for x, y, w, h in boxes}
        for x1, y1, x2, y2 in re.findall(
                r'd="M([\d.]+),([\d.]+) C[\d.]+,[\d.]+ [\d.]+,[\d.]+ ([\d.]+),([\d.]+)"', page):
            self.assertIn((float(x1), float(y1)), anchors)
            self.assertIn((float(x2), float(y2)), anchors)

    def test_a_screen_with_many_untapped_targets_wraps_instead_of_widening(self):
        # 51 candidates laid out flat made the canvas 9000px wide and unreadable.
        tree = self.dir / "wide.xml"
        buttons = "".join(
            f'<XCUIElementTypeButton type="XCUIElementTypeButton" label="b{i}" name="b{i}"'
            f' enabled="true" visible="true" x="0" y="{100 + i * 20}" width="80" height="18"/>'
            for i in range(20))
        tree.write_text(TREE.replace(
            "</XCUIElementTypeApplication>", buttons + "</XCUIElementTypeApplication>"),
            encoding="utf-8")
        ev = self.screen()
        ev["tree"] = str(tree)
        self.write([ev])
        out = self.dir / "map.html"
        self.run_flow("map", str(self.log), str(out))
        page = out.read_text(encoding="utf-8")
        width = int(re.search(r"\.stage \{ position:relative; width:(\d+)px", page).group(1))
        self.assertLess(width, 1200)

    def test_screenshots_are_linked_relative_to_the_page(self):
        png = self.dir / "raw" / "01-home.png"
        png.parent.mkdir()
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        ev = self.screen()
        ev["png"] = str(png)
        self.write([ev])
        out = self.dir / "map.html"
        self.run_flow("map", str(self.log), str(out))
        self.assertIn('src="raw/01-home.png"', out.read_text(encoding="utf-8"))


class TestRefusals(FlowCase):
    def test_a_missing_log_says_what_writes_it(self):
        r = self.run_flow("next", str(self.dir / "nope.jsonl"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("device_wda.sh screen", r.stderr)

    def test_a_corrupt_log_is_not_silently_empty(self):
        self.log.write_text("{not json\n", encoding="utf-8")
        r = self.run_flow("stats", str(self.log))
        self.assertEqual(r.returncode, 1)
        self.assertIn("corrupt", r.stderr)


if __name__ == "__main__":
    unittest.main()
