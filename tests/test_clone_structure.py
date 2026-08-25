"""clone_structure.py — the repeating units measurement alone cannot see.

A feed of 30 cards measures as 30 independent element groups, so the generated
view replays 30 absolute-positioned blocks. A person reading it says "that is
one card in a ForEach" instantly; nothing in the pipeline could say it at all.
This is where that layer enters, machine-drafted so a person confirms rather
than authors.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.clone_structure import MARKER, detect_repeats, write_structure


def card(top: float, name: str, name_width: float) -> list[dict]:
    """One feed card: a container holding an avatar and a name."""
    return [
        {"role": "AXOther", "label": "", "parent": 0,
         "frame": {"x": 0.0, "y": top, "width": 390.0, "height": 100.0}},
        {"role": "AXImage", "label": "avatar", "parent": -1,
         "frame": {"x": 8.0, "y": top + 8, "width": 40.0, "height": 40.0}},
        {"role": "AXStaticText", "label": name, "parent": -1,
         "frame": {"x": 56.0, "y": top + 8, "width": name_width, "height": 20.0}},
    ]


def feed(*cards: list[dict]) -> dict:
    """Wrap card subtrees in a scroll container, fixing up parent indices."""
    elements = [{"role": "AXScrollView", "label": "", "parent": -1,
                 "frame": {"x": 0.0, "y": 0.0, "width": 390.0, "height": 600.0}}]
    for group in cards:
        base = len(elements)
        container, *kids = group
        elements.append(container)
        for kid in kids:
            elements.append({**kid, "parent": base})
    return {"elements": elements}


class TestRepeatDetection(unittest.TestCase):
    def test_three_identical_card_subtrees_are_one_repeat_group(self):
        """Per-item text differs in content and width — the unit is still one unit.

        Requiring identical widths would find nothing on a real feed, where the
        only thing that never varies is the shape.
        """
        measurement = feed(
            card(0.0, "Alice", 100.0),
            card(100.0, "Bob", 80.0),
            card(200.0, "Carol", 120.0),
        )

        groups = detect_repeats(measurement)

        self.assertEqual(len(groups), 1, msg=f"expected one group, got {groups}")
        self.assertEqual(groups[0]["children"], [1, 4, 7])
        self.assertEqual(groups[0]["axis"], "vertical")

    def test_same_shape_at_an_irregular_pitch_is_not_a_repeat(self):
        """Shape alone is not a pattern — a false ForEach is worse than none.

        Three same-shaped blocks scattered down a page are three blocks. Calling
        them a repeat makes the generator emit a loop the screen does not have,
        which is a structural lie that reads as confident code.
        """
        measurement = feed(
            card(0.0, "Alice", 100.0),
            card(100.0, "Bob", 80.0),
            card(350.0, "Carol", 120.0),
        )

        self.assertEqual(detect_repeats(measurement), [])

    def test_a_row_repeats_along_the_horizontal_axis(self):
        measurement = feed(
            card(0.0, "Alice", 100.0),
            card(0.0, "Bob", 80.0),
            card(0.0, "Carol", 120.0),
        )
        for slot, left in zip((1, 4, 7), (0.0, 120.0, 240.0)):
            measurement["elements"][slot]["frame"]["x"] = left
            measurement["elements"][slot]["frame"]["width"] = 110.0

        groups = detect_repeats(measurement)

        self.assertEqual(len(groups), 1, msg=f"expected one group, got {groups}")
        self.assertEqual(groups[0]["axis"], "horizontal")
        self.assertEqual(groups[0]["pitch"], 120.0)

    def test_siblings_of_different_shapes_are_not_a_repeat(self):
        measurement = feed(
            card(0.0, "Alice", 100.0),
            card(100.0, "Bob", 80.0),
            card(200.0, "Carol", 120.0),
        )
        measurement["elements"][8]["role"] = "AXButton"   # third card diverges

        groups = detect_repeats(measurement)

        self.assertEqual(groups, [], "two of three is below the pattern floor")


class TestStructureArtifact(unittest.TestCase):
    """The draft a person confirms, under the ownership rule the repo already uses."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        (self.root / "screens").mkdir()
        measurement = feed(
            card(0.0, "Alice", 100.0),
            card(100.0, "Bob", 80.0),
            card(200.0, "Carol", 120.0),
        )
        (self.root / "screens" / "01-home.json").write_text(
            json.dumps(measurement), encoding="utf-8")
        self.target = self.root / "structure" / "01-home.json"

    def test_a_detected_group_is_written_as_a_confirmable_draft(self):
        write_structure(self.root)

        payload = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(payload[MARKER], True,
                         "the draft must say it is machine-owned")
        self.assertEqual(len(payload["groups"]), 1)
        self.assertEqual(payload["groups"][0]["children"], [1, 4, 7])
        self.assertIn("component", payload["groups"][0],
                      "codegen needs a name to give the extracted unit")

    def test_a_draft_a_person_took_over_is_never_overwritten(self):
        """Same ownership boundary as the generated views: drop the marker, own the file.

        Without it the confirm step is worthless — every correction a person
        makes is erased by the next observe, which is the loop that made prose
        specs pointless in the first place.
        """
        write_structure(self.root)
        self.target.write_text(json.dumps({"groups": [], "note": "not a feed"}),
                               encoding="utf-8")

        write_structure(self.root)

        payload = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(payload["groups"], [])
        self.assertEqual(payload["note"], "not a feed")


if __name__ == "__main__":
    unittest.main()
