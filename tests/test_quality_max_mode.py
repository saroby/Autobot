"""quality-max opt-in mode — gates tighten ONLY when state.qualityMax is set.

The default autonomous /mvp path (no flag) must keep its exact prior behavior:
a missing peer review / Axiom audit and a Stitch fallback are benign skips
(green). With qualityMax, those become DEGRADED (skipped+degraded) — shipping-
blocking but NOT a hard fail (a hard fail would increment retryCount and could
trip the global circuit breaker, halting the autonomous build — build.py:119).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.review import (  # noqa: E402
    check_axiom_critical_audit_acceptable,
    check_peer_review_acceptable,
)
from gate_checks.design import check_design_assets_exist_or_fallback  # noqa: E402
from gate_checks.build import check_backend_deploy_readiness  # noqa: E402

APP = "App"
PROJ = Path("/tmp")  # axiom/peer skip paths don't touch disk


def _peer_state(qmax: bool) -> dict:
    st = {
        "phases": {"5": {"metadata": {"peerReview": {
            "verdict": "skipped", "skipReason": "peer_unavailable",
            "host": "claude", "peer": "codex",
        }}}},
        "environment": {},
    }
    if qmax:
        st["qualityMax"] = True
    return st


def _axiom_state(qmax: bool) -> dict:
    st = {"environment": {"axiom": False}, "phases": {"5": {"metadata": {}}}}
    if qmax:
        st["qualityMax"] = True
    return st


class TestAxiomQualityMax(unittest.TestCase):
    def test_default_unavailable_is_benign_skip(self):
        r = check_axiom_critical_audit_acceptable(PROJ, APP, _axiom_state(False))[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))  # green by default

    def test_qmax_unavailable_is_degraded(self):
        r = check_axiom_critical_audit_acceptable(PROJ, APP, _axiom_state(True))[0]
        self.assertTrue(r["passed"])       # not a hard fail
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))  # shipping-blocking


class TestPeerQualityMax(unittest.TestCase):
    def test_default_skipped_is_benign(self):
        r = check_peer_review_acceptable(PROJ, APP, _peer_state(False))[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_qmax_skipped_is_degraded(self):
        r = check_peer_review_acceptable(PROJ, APP, _peer_state(True))[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))


class TestDesignFallbackQualityMax(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot" / "designs").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _state(self, qmax: bool) -> dict:
        st = {"phases": {"2": {"status": "fallback"}}}
        if qmax:
            st["qualityMax"] = True
        return st

    def _add_mockup(self):
        (self.proj / ".autobot" / "designs" / "Home.png").write_bytes(b"\x89PNG\r\n")

    def test_default_fallback_no_png_is_benign(self):
        r = check_design_assets_exist_or_fallback(self.proj, APP, self._state(False))[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertFalse(r.get("degraded", False))

    def test_qmax_fallback_no_png_is_degraded(self):
        r = check_design_assets_exist_or_fallback(self.proj, APP, self._state(True))[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r.get("skipped"))
        self.assertTrue(r.get("degraded"))

    def test_qmax_fallback_with_mockup_is_benign(self):
        self._add_mockup()
        r = check_design_assets_exist_or_fallback(self.proj, APP, self._state(True))[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))  # has a real mockup → satisfied


class TestBackendDeployReadinessQualityMax(unittest.TestCase):
    """backend_required app's Release.xcconfig must point at a deployed host in
    quality-max (else the shipped app's auth/AI calls fail). Default mode is
    benign; quality-max → DEGRADED. Skips entirely when no backend needed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _xcconfig(self, value: str):
        (self.proj / "Release.xcconfig").write_text(f"API_BASE_URL = {value}\n")

    def test_no_backend_skips(self):
        r = check_backend_deploy_readiness(self.proj, APP, {"backend_required": False})[0]
        self.assertTrue(r["passed"])
        self.assertTrue(r["skipped"])
        self.assertFalse(r.get("degraded", False))

    def test_placeholder_default_is_benign(self):
        self._xcconfig("https://$(PRODUCTION_HOST)")
        r = check_backend_deploy_readiness(self.proj, APP, {"backend_required": True})[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))  # default: localhost OK pre-deploy

    def test_placeholder_quality_max_is_degraded(self):
        self._xcconfig("https://$(PRODUCTION_HOST)")
        r = check_backend_deploy_readiness(self.proj, APP, {"backend_required": True, "qualityMax": True})[0]
        self.assertTrue(r["passed"])       # not a hard fail
        self.assertTrue(r.get("degraded"))  # shipping-blocked

    def test_real_host_quality_max_passes(self):
        self._xcconfig("https://api.myapp.com")
        r = check_backend_deploy_readiness(self.proj, APP, {"backend_required": True, "qualityMax": True})[0]
        self.assertTrue(r["passed"])
        self.assertFalse(r.get("degraded", False))  # deploy-ready


class TestQualityMaxFlagAllowed(unittest.TestCase):
    def test_qualitymax_in_allowed_flags(self):
        import json
        spec = json.load(open(Path(__file__).resolve().parent.parent / "spec" / "pipeline.json"))
        self.assertIn("qualityMax", spec["policies"]["allowedFlags"])


if __name__ == "__main__":
    unittest.main()
