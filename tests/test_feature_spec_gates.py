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
    check_feature_spec_depth,
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


def _deep_feat(fid, priority, screen, role, pc, steps=1) -> dict:
    return {
        "id": fid, "title": fid, "priority": priority, "screen": screen,
        "anchor": f"autobot.{fid}", "role": role,
        "acceptance": [{
            "id": f"{fid}.a1", "kind": "flow",
            "steps": [{"action": "tap", "anchor": f"autobot.{fid}"}] * steps,
            "postcondition": {"kind": pc, "params": {}},
        }],
    }


def _deep_spec() -> dict:
    """Clears every depth floor (P0+P1=5, P0=2, screens>=3, kinds>=3,
    hook+retention roles, one multi-step journey)."""
    return {"features": [
        _deep_feat("log", "P0", "Home", "hook", "count_increased", steps=2),
        _deep_feat("stats", "P0", "Stats", "insight", "navigated_to"),
        _deep_feat("history", "P1", "History", "retention", "value_persisted_after_relaunch"),
        _deep_feat("edit", "P1", "Home", "table-stakes", "count_increased"),
        _deep_feat("settings", "P1", "Settings", "table-stakes", "navigated_to"),
    ]}


class TestFeatureSpecDepth(unittest.TestCase):
    """check_feature_spec_depth — depth floor is DEGRADED by default (never a
    circuit-breaker-consuming hard fail), hard only under quality-max; the
    one-tap degenerate spec is the sole default-mode hard fail."""

    def _depth_row(self, results):
        return next(r for r in results if r["check"] == "feature_spec_depth")

    def test_deep_spec_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), _deep_spec())
            r = self._depth_row(check_feature_spec_depth(Path(tmp), "Demo", {}))
            self.assertTrue(r["passed"], r["message"])
            self.assertFalse(r.get("degraded", False))

    def test_thin_spec_is_degraded_not_hard_in_default_mode(self):
        spec = {"features": [
            _deep_feat("log", "P0", "Home", "hook", "count_increased", steps=3),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), spec)
            r = self._depth_row(check_feature_spec_depth(Path(tmp), "Demo", {}))
            self.assertFalse(r["passed"])
            self.assertTrue(r.get("skipped"), "thin spec must DEGRADE, not hard-fail")
            self.assertTrue(r.get("degraded"))
            self.assertIn("THIN-SPEC", r["message"])

    def test_thin_spec_is_hard_fail_under_quality_max(self):
        spec = {"features": [
            _deep_feat("log", "P0", "Home", "hook", "count_increased", steps=3),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), spec)
            r = self._depth_row(check_feature_spec_depth(
                Path(tmp), "Demo", {"qualityMax": True}))
            self.assertFalse(r["passed"])
            self.assertFalse(r.get("skipped", False))
            self.assertFalse(r.get("degraded", False))

    def test_one_tap_demo_is_hard_fail_even_in_default_mode(self):
        spec = {"features": [
            _deep_feat("tap", "P0", "Home", "hook", "count_increased", steps=1),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), spec)
            r = self._depth_row(check_feature_spec_depth(Path(tmp), "Demo", {}))
            self.assertFalse(r["passed"])
            self.assertFalse(r.get("skipped", False))
            self.assertIn("demo", r["message"])

    def test_advisories_warn_in_default_and_degrade_in_quality_max(self):
        spec = _deep_spec()
        # two extra P1s so the spec also clears the quality-max P0+P1 floor (7)
        spec["features"].append(_deep_feat("export", "P1", "Stats", "table-stakes", "artifact_generated"))
        spec["features"].append(_deep_feat("archive", "P1", "History", "table-stakes", "count_decreased"))
        for f in spec["features"]:
            f.pop("role")  # legacy spec → advisory only
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), spec)
            r = self._depth_row(check_feature_spec_depth(Path(tmp), "Demo", {}))
            self.assertTrue(r["passed"], r["message"])
            self.assertFalse(r.get("degraded", False))
            self.assertIn("warnings", r["message"])
            r = self._depth_row(check_feature_spec_depth(
                Path(tmp), "Demo", {"qualityMax": True}))
            self.assertTrue(r["passed"])
            self.assertTrue(r.get("degraded"), r)

    def test_quality_max_p2_stub_pressure_is_degraded_row(self):
        spec = _deep_spec()
        spec["features"].append({
            "id": "share", "title": "Share", "priority": "P2",
            "screen": "Home", "anchor": "autobot.share", "acceptance": [],
        })
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), spec)
            out = check_feature_spec_depth(Path(tmp), "Demo", {"qualityMax": True})
            row = next(r for r in out if r["check"] == "feature_spec_p2_downgrade")
            self.assertTrue(row.get("skipped"))
            self.assertTrue(row.get("degraded"))
            self.assertIn("share", row["message"])
            # default mode: no downgrade-pressure row at all
            out = check_feature_spec_depth(Path(tmp), "Demo", {})
            self.assertFalse(any(r["check"] == "feature_spec_p2_downgrade" for r in out))


if __name__ == "__main__":
    unittest.main()
