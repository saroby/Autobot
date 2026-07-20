"""Regression tests for skills/autobot-check-name/scripts/check-name.sh.

Never touches the network — the script's AUTOBOT_CHECKNAME_FIXTURE_DIR hook
feeds canned iTunes Search responses per country. Requires python3 + bash
(both hard deps of the test suite).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_DIR / "skills" / "autobot-check-name" / "scripts" / "check-name.sh"


def _resp(*names):
    """Build a minimal iTunes Search response with the given trackNames."""
    return json.dumps(
        {
            "resultCount": len(names),
            "results": [
                {"trackName": n, "trackId": 100 + i, "sellerName": f"Dev {i}"}
                for i, n in enumerate(names)
            ],
        }
    )


def run(args, fixtures=None, status_file=None):
    """Run check-name.sh. `fixtures` maps country code -> list of trackNames
    (a country omitted from the dict has no fixture file => available)."""
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="autobot-checkname-test.") as fx:
        if fixtures:
            for cc, names in fixtures.items():
                (Path(fx) / f"{cc}.json").write_text(_resp(*names))
        env["AUTOBOT_CHECKNAME_FIXTURE_DIR"] = fx
        if status_file:
            env["AUTOBOT_CHECKNAME_STATUS_FILE"] = str(status_file)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
        )


class InputValidationTests(unittest.TestCase):
    def test_missing_name_exits_1(self):
        r = run(["--country", "kr"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("--name is required", r.stderr)

    def test_name_too_long_exits_1(self):
        r = run(["--name", "x" * 101])
        self.assertEqual(r.returncode, 1)
        self.assertIn("out of range", r.stderr)

    def test_invalid_country_exits_1(self):
        r = run(["--name", "Ok", "--country", "korea"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("alpha-2", r.stderr)

    def test_missing_flag_value(self):
        r = run(["--name"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a value", r.stderr)

    def test_flag_followed_by_flag(self):
        r = run(["--name", "--country", "kr"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("requires a value", r.stderr)

    def test_unknown_option(self):
        r = run(["--name", "Ok", "--bogus"])
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown option", r.stderr)


class MatchingTests(unittest.TestCase):
    def test_exact_match_is_taken_exit_2(self):
        r = run(["--name", "Bear Notes", "--country", "kr"],
                fixtures={"kr": ["Bear Notes"]})
        self.assertEqual(r.returncode, 2, msg=r.stdout + r.stderr)
        self.assertIn("FAIL: kr", r.stdout)
        self.assertIn("TAKEN", r.stdout)

    def test_case_and_whitespace_normalized_match(self):
        # "bear   notes" (lower, extra spaces) collides with "Bear Notes".
        r = run(["--name", "Bear Notes", "--country", "kr"],
                fixtures={"kr": ["bear   notes"]})
        self.assertEqual(r.returncode, 2, msg=r.stdout + r.stderr)

    def test_punctuation_difference_not_exact(self):
        # "Bear: Notes" != "Bear Notes" (punctuation preserved) => not taken.
        r = run(["--name", "Bear Notes", "--country", "kr"],
                fixtures={"kr": ["Bear: Notes"]})
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("PASS: kr", r.stdout)

    def test_available_when_no_hits(self):
        r = run(["--name", "Zxqwlem Unique", "--country", "kr"],
                fixtures={"kr": ["Something Else"]})
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("PASS: kr", r.stdout)

    def test_similar_advisory_does_not_fail(self):
        # "Bear Notes Pro" contains all query tokens -> similar, not taken.
        r = run(["--name", "Bear Notes", "--country", "kr"],
                fixtures={"kr": ["Bear Notes Pro"]})
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("similar", r.stdout)

    def test_exact_flag_suppresses_similar(self):
        r = run(["--name", "Bear Notes", "--country", "kr", "--exact"],
                fixtures={"kr": ["Bear Notes Pro"]})
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertNotIn("similar", r.stdout)


class MultiCountryTests(unittest.TestCase):
    def test_taken_in_one_country_fails_overall(self):
        r = run(["--name", "Bear Notes", "--country", "kr,us,jp"],
                fixtures={"us": ["Bear Notes"]})  # kr/jp absent => available
        self.assertEqual(r.returncode, 2, msg=r.stdout + r.stderr)
        self.assertIn("FAIL: us", r.stdout)
        self.assertIn("PASS: kr", r.stdout)
        self.assertIn("PASS: jp", r.stdout)

    def test_country_codes_normalized_and_deduped(self):
        r = run(["--name", "Ok", "--country", "KR, kr ,us"])
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        # kr appears once, not twice
        self.assertEqual(r.stdout.count("PASS: kr"), 1)
        self.assertIn("PASS: us", r.stdout)


class StatusFileTests(unittest.TestCase):
    def test_status_json_written_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "sub" / "status.json"  # nested dir must be created
            r = run(["--name", "Bear Notes", "--country", "kr,us"],
                    fixtures={"kr": ["Bear Notes"]}, status_file=status)
            self.assertEqual(r.returncode, 2, msg=r.stdout + r.stderr)
            self.assertTrue(status.is_file())
            data = json.loads(status.read_text())
            self.assertEqual(data["overall"], "taken")
            self.assertEqual(data["countries"]["kr"]["status"], "taken")
            self.assertEqual(data["countries"]["us"]["status"], "available")
            # no orphan temp files left behind
            leftovers = [p for p in status.parent.iterdir() if ".tmp." in p.name]
            self.assertEqual(leftovers, [])

    def test_hostile_trackname_does_not_corrupt_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            hostile = 'evil","admin":true,"x'
            # Query equals the hostile name so it registers as an exact match.
            r = run(["--name", hostile, "--country", "kr"],
                    fixtures={"kr": [hostile]}, status_file=status)
            self.assertEqual(r.returncode, 2, msg=r.stdout + r.stderr)
            data = json.loads(status.read_text())
            self.assertEqual(data["countries"]["kr"]["match"], hostile)
            self.assertNotIn("admin", data)


if __name__ == "__main__":
    unittest.main()
