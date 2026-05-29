"""run-summary surfaces a loud VERIFIED / DEGRADED badge from gate 5->6."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from run_summary import build_summary, render_markdown  # noqa: E402


def _seed(project_root: Path, *, gate56_status):
    (project_root / ".autobot").mkdir()
    state = {"buildId": "b1", "appName": "X", "phases": {"5": {"status": "completed"}}}
    if gate56_status is not None:
        state["gates"] = {"5->6": {"status": gate56_status}}
    (project_root / ".autobot" / "build-state.json").write_text(json.dumps(state))
    (project_root / ".autobot" / "build-log.jsonl").write_text("")


class TestFunctionalVerificationBadge(unittest.TestCase):
    def _summary(self, status):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status=status)
            return build_summary(proj)

    def test_passed_yields_verified_badge(self):
        fv = self._summary("passed")["functionalVerification"]
        self.assertEqual(fv["badge"], "VERIFIED")
        self.assertEqual(fv["gate56Status"], "passed")
        self.assertTrue(fv["shippable"])

    def test_degraded_yields_degraded_badge_not_shippable(self):
        fv = self._summary("degraded")["functionalVerification"]
        self.assertEqual(fv["badge"], "DEGRADED")
        self.assertFalse(fv["shippable"])

    def test_missing_gate_yields_unverified(self):
        fv = self._summary(None)["functionalVerification"]
        self.assertEqual(fv["badge"], "UNVERIFIED")
        self.assertFalse(fv["shippable"])

    def test_markdown_renders_loud_degraded_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status="degraded")
            md = render_markdown(build_summary(proj))
        self.assertIn("## Verification", md)
        self.assertIn("DEGRADED", md)
        self.assertIn("functional unverified", md.lower())

    def test_markdown_renders_verified_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _seed(proj, gate56_status="passed")
            md = render_markdown(build_summary(proj))
        self.assertIn("## Verification", md)
        self.assertIn("VERIFIED", md)


if __name__ == "__main__":
    unittest.main()
