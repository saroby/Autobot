"""Gate 1->2 feature-spec checks — the per-feature spine is now mandatory.
Absent feature-spec.json is a HARD FAIL (not a skip), unlike legacy app-intent.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_runner import (  # noqa: E402
    check_feature_spec_declared,
    check_feature_spec_quality,
)


def _write(root: Path, payload: dict) -> None:
    (root / ".autobot").mkdir(parents=True, exist_ok=True)
    (root / ".autobot" / "feature-spec.json").write_text(json.dumps(payload), encoding="utf-8")


def _feat(fid="f1", priority="P0", anchor="autobot.f1.cta", pc="count_increased",
          with_acceptance=True) -> dict:
    acc = [{
        "id": f"{fid}.a1", "kind": "flow",
        "steps": [{"action": "tap", "anchor": anchor}],
        "postcondition": {"kind": pc, "params": {}},
    }] if with_acceptance else []
    return {"id": fid, "title": fid, "priority": priority, "screen": "Home",
            "anchor": anchor, "acceptance": acc}


class TestFeatureSpecDeclared(unittest.TestCase):
    def test_valid_p0_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), {"features": [_feat()]})
            r = check_feature_spec_declared(Path(tmp), "Demo", {})
            self.assertTrue(r[0]["passed"], r[0]["message"])
            self.assertFalse(r[0].get("skipped"))

    def test_p0_lacking_acceptance_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), {"features": [_feat(with_acceptance=False)]})
            r = check_feature_spec_declared(Path(tmp), "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertFalse(r[0].get("skipped"))
            self.assertIn("acceptance", r[0]["message"])

    def test_absent_is_hard_fail_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = check_feature_spec_declared(Path(tmp), "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertFalse(r[0].get("skipped"))
            self.assertFalse(r[0].get("degraded"))
            self.assertIn("feature-spec.json", r[0]["message"])


class TestFeatureSpecQuality(unittest.TestCase):
    def test_behavioral_postcondition_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), {"features": [_feat(pc="value_persisted_after_relaunch")]})
            r = check_feature_spec_quality(Path(tmp), "Demo", {})
            self.assertTrue(r[0]["passed"], r[0]["message"])

    def test_anchor_only_postcondition_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), {"features": [_feat(pc="anchor_present")]})
            r = check_feature_spec_quality(Path(tmp), "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertIn("postcondition", r[0]["message"])

    def test_absent_is_hard_fail_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = check_feature_spec_quality(Path(tmp), "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertFalse(r[0].get("skipped"))
            self.assertIn("feature-spec.json", r[0]["message"])

    def test_zero_p0_spec_is_hard_fail(self):
        # An all-P1/P2 spec would let every flow fail while the suite still
        # "passes" (P1 failures only warn) — the VERIFIED-badge laundering
        # hole. Gate 1->2 must reject it (deterministic P0 count → hard fail
        # is safe).
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), {"features": [_feat(priority="P1")]})
            r = check_feature_spec_quality(Path(tmp), "Demo", {})
            self.assertFalse(r[0]["passed"])
            self.assertFalse(r[0].get("skipped"))
            self.assertFalse(r[0].get("degraded"))
            self.assertIn("P0", r[0]["message"])


if __name__ == "__main__":
    unittest.main()
