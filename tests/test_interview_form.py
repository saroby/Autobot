"""interview_form.py 회귀 — 렌더 + POST 왕복은 스크립트의 --selftest 가 소유한다."""

from __future__ import annotations

import subprocess
import sys
import unittest

from conftest import SCRIPTS_DIR


class InterviewFormTest(unittest.TestCase):
    def test_selftest_passes(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "interview_form.py"), "--selftest"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("selftest ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
