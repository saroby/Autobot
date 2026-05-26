"""Tests for scripts/error_signature.py — normalization stability and the
2-repeat circuit-breaker trip semantics that policies.circuitBreaker
.errorSignatureRepeat in spec/pipeline.json contracts.
"""

from __future__ import annotations

import unittest

from conftest import import_runtime_modules

import_runtime_modules()

from error_signature import check, normalize, record  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_strips_path_line_col_and_drops_notes(self):
        raw = (
            "/Users/foo/Bar.swift:42:5: error: type 'X' not found\n"
            "/Users/foo/Bar.swift:43:5: warning: this is ignored\n"
            "note: did you mean Y?\n"
        )
        canonical, digest = normalize(raw)
        # Notes are dropped; warnings keep their line content but get path stripped
        self.assertNotIn("note:", canonical)
        self.assertNotIn("/Users/foo/Bar.swift", canonical)
        self.assertIn("type 'X' not found", canonical)
        self.assertEqual(len(digest), 16)

    def test_same_error_different_paths_yields_same_hash(self):
        a = "/a/path/Foo.swift:1:1: error: cannot find type 'Bar' in scope"
        b = "/totally/different/Foo.swift:99:42: error: cannot find type 'Bar' in scope"
        _, ha = normalize(a)
        _, hb = normalize(b)
        self.assertEqual(ha, hb)

    def test_different_errors_yield_different_hashes(self):
        _, ha = normalize("error: cannot find type 'Bar' in scope")
        _, hb = normalize("error: cannot find type 'Baz' in scope")
        self.assertNotEqual(ha, hb)

    def test_hex_and_timestamps_normalized(self):
        a = "crash at 0x7fff8a1b 2026-05-26T12:00:00Z"
        b = "crash at 0x7fff999c 2026-05-27T13:00:00Z"
        _, ha = normalize(a)
        _, hb = normalize(b)
        self.assertEqual(ha, hb, "addresses + timestamps must normalize to same signature")


class _SpecOverride:
    """Use a stub spec so tests don't depend on the real spec policy value."""

    @staticmethod
    def policy_enabled(max_repeats: int = 2) -> dict:
        return {
            "policies": {
                "circuitBreaker": {
                    "errorSignatureRepeat": {
                        "enabled": True,
                        "maxRepeats": max_repeats,
                    }
                }
            }
        }

    @staticmethod
    def policy_disabled() -> dict:
        return {
            "policies": {
                "circuitBreaker": {
                    "errorSignatureRepeat": {"enabled": False}
                }
            }
        }


class TestRecordAndCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.state: dict = {"phases": {"5": {}}}
        self.spec = _SpecOverride.policy_enabled(max_repeats=2)

    def test_first_record_does_not_trip(self):
        trip, occ, digest = record(self.state, "5", "build error A", spec=self.spec)
        self.assertFalse(trip)
        self.assertEqual(occ, 1)
        self.assertTrue(digest)

    def test_second_record_with_same_signature_trips(self):
        record(self.state, "5", "build error A", spec=self.spec)
        trip, occ, _ = record(self.state, "5", "build error A", spec=self.spec)
        self.assertTrue(trip)
        self.assertEqual(occ, 2)
        breaker = self.state["phases"]["5"].get("circuitBreaker") or {}
        self.assertTrue(breaker.get("tripped"))
        self.assertEqual(breaker.get("reason"), "error_signature_repeat")

    def test_different_signature_resets_counter_for_other_signature(self):
        record(self.state, "5", "build error A", spec=self.spec)
        trip, occ, _ = record(self.state, "5", "build error B", spec=self.spec)
        self.assertFalse(trip)
        self.assertEqual(occ, 1)

    def test_check_does_not_mutate_state(self):
        record(self.state, "5", "build error A", spec=self.spec)
        snapshot = dict(self.state["phases"]["5"])
        check(self.state, "5", "build error A", spec=self.spec)
        self.assertEqual(self.state["phases"]["5"], snapshot)

    def test_check_predicts_trip_one_record_before(self):
        record(self.state, "5", "build error A", spec=self.spec)
        # After one record, the next record would trip — check should signal that
        trip_preview, _, _ = check(self.state, "5", "build error A", spec=self.spec)
        self.assertTrue(trip_preview)

    def test_disabled_policy_never_trips(self):
        spec_off = _SpecOverride.policy_disabled()
        record(self.state, "5", "build error A", spec=spec_off)
        trip, _, _ = record(self.state, "5", "build error A", spec=spec_off)
        self.assertFalse(trip)


if __name__ == "__main__":
    unittest.main()
