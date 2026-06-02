"""flow DSL — coordinate math for swipe/long_press actions (#4 flow DSL).

AXe's tap/type are anchor/text-based, but swipe/touch are coordinate-based, so
flow_runner derives the point from the anchor's describe-ui frame. That math is
pure and unit-tested here. The AXe subprocess invocation itself (axe swipe/type/
touch) is documented at axe-cli.com/docs/command-reference but only verified on a
real simulator — these tests cover the deterministic coordinate derivation, not
the AXe execution.
"""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

from flow_runner import _anchor_frame, _frame_center, _swipe_endpoint  # noqa: E402


class TestAnchorFrame(unittest.TestCase):
    def test_found_by_axuniqueid(self):
        els = [{"AXUniqueId": "autobot.cta", "frame": {"x": 10, "y": 20, "width": 100, "height": 40}}]
        self.assertEqual(_anchor_frame(els, "autobot.cta"), (10.0, 20.0, 100.0, 40.0))

    def test_found_by_identifier_fallback(self):
        els = [{"identifier": "autobot.row", "frame": {"x": 0, "y": 0, "width": 50, "height": 50}}]
        self.assertEqual(_anchor_frame(els, "autobot.row"), (0.0, 0.0, 50.0, 50.0))

    def test_missing_anchor_returns_none(self):
        els = [{"AXUniqueId": "other", "frame": {"x": 1, "y": 2, "width": 3, "height": 4}}]
        self.assertIsNone(_anchor_frame(els, "autobot.cta"))

    def test_malformed_frame_returns_none(self):
        els = [{"AXUniqueId": "autobot.cta", "frame": {"x": "nope"}}]
        self.assertIsNone(_anchor_frame(els, "autobot.cta"))


class TestFrameCenter(unittest.TestCase):
    def test_center(self):
        self.assertEqual(_frame_center((10.0, 20.0, 100.0, 40.0)), (60.0, 40.0))


class TestSwipeEndpoint(unittest.TestCase):
    # screen y grows downward → 'up' subtracts y, 'down' adds y.
    def test_up(self):
        self.assertEqual(_swipe_endpoint(50.0, 300.0, "up", 200.0), (50.0, 100.0))

    def test_down(self):
        self.assertEqual(_swipe_endpoint(50.0, 100.0, "down", 200.0), (50.0, 300.0))

    def test_left(self):
        self.assertEqual(_swipe_endpoint(300.0, 50.0, "left", 200.0), (100.0, 50.0))

    def test_right(self):
        self.assertEqual(_swipe_endpoint(100.0, 50.0, "right", 200.0), (300.0, 50.0))

    def test_unknown_direction_defaults_up(self):
        self.assertEqual(_swipe_endpoint(50.0, 300.0, "sideways", 200.0), (50.0, 100.0))


if __name__ == "__main__":
    unittest.main()
