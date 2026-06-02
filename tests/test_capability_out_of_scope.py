"""capability_coverage — unsupported capabilities the architect declared in
``## Out of Scope`` are reported as deliberate exclusions, not silent gaps (#5).

The pipeline never generates StoreKit/Push/Widgets/etc. When the idea asks for
one, the architect should declare it excluded in ``## Out of Scope``. This lets
coverage distinguish "excluded by design" from "requested but silently missing"
— it does NOT auto-implement (that stays out of scope, per the verdict).
"""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

import capability_coverage as cc  # noqa: E402


class TestOutOfScopeAcknowledgement(unittest.TestCase):
    def test_unsupported_detected(self):
        hits = cc._detect_unsupported("a notes app with push notifications and a home widget")
        cats = {h["category"] for h in hits}
        self.assertIn("Push notifications (APNs / remote)", cats)
        self.assertIn("Home-screen widgets (WidgetKit)", cats)

    def test_silent_gap_when_no_out_of_scope_section(self):
        hits = cc._detect_unsupported("a notes app with push notifications")
        cc._mark_acknowledged(hits, "# Arch\n## Features\n- take notes\n")
        self.assertTrue(hits)
        self.assertTrue(all(h["acknowledged"] is False for h in hits))

    def test_acknowledged_when_declared_out_of_scope(self):
        hits = cc._detect_unsupported("a notes app with push notifications")
        arch = (
            "# Arch\n\n## Out of Scope\n"
            "Push notifications (APNs) are not built in this MVP — excluded by design.\n\n"
            "## Features\n- take notes\n"
        )
        cc._mark_acknowledged(hits, arch)
        self.assertTrue(all(h["acknowledged"] is True for h in hits))

    def test_partial_acknowledgement(self):
        # Push declared out of scope, widgets not → one ack, one silent gap.
        hits = cc._detect_unsupported("notes app with push notifications and a home widget")
        arch = "# Arch\n## Out of Scope\nPush (APNs) excluded.\n## Features\n- x\n"
        cc._mark_acknowledged(hits, arch)
        by_cat = {h["category"]: h["acknowledged"] for h in hits}
        self.assertTrue(by_cat["Push notifications (APNs / remote)"])
        self.assertFalse(by_cat["Home-screen widgets (WidgetKit)"])

    def test_render_separates_ack_from_silent_gap(self):
        coverage = {"scope": {"unsupportedRequested": [
            {"category": "Push notifications (APNs / remote)", "matched": "push", "acknowledged": True},
            {"category": "Home-screen widgets (WidgetKit)", "matched": "widget", "acknowledged": False},
        ]}}
        md = cc.render(coverage)
        self.assertIn("Intentionally out of scope", md)
        self.assertIn("silent gap", md)


if __name__ == "__main__":
    unittest.main()
