"""Structured diagnostics on the xcodebuild result dict.

The error signature strips file paths on purpose (circuit breaker wants
"same error" regardless of where); `diagnostics` keeps file/line/column so
the gate message and build-fix loop can point at the exact location.
"""
from __future__ import annotations

import unittest
from unittest import mock
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

import xcodebuild_runner as xr  # noqa: E402
from gate_checks import scaffold  # noqa: E402

STDERR = """\
/Users/x/App/Sources/Foo.swift:12:5: error: cannot find 'bar' in scope
/Users/x/App/Sources/Foo.swift:12:5: error: cannot find 'bar' in scope
/Users/x/App/Sources/Baz.swift:3:1: warning: unused variable 'q'
** BUILD FAILED **
"""


class TestDiagnostics(unittest.TestCase):
    def test_parse_dedupes_and_keeps_location(self):
        diags = xr._parse_diagnostics(STDERR)
        self.assertEqual([(d["file"].rsplit("/", 1)[1], d["line"], d["column"], d["severity"]) for d in diags],
                         [("Foo.swift", 12, 5, "error"), ("Baz.swift", 3, 1, "warning")])
        self.assertEqual(diags[0]["message"], "cannot find 'bar' in scope")

    def test_build_result_carries_diagnostics_only_on_failure(self):
        kw = dict(phase="3", project=Path("/p/App.xcodeproj"), stdout="", stderr=STDERR,
                  duration=1.0, log_path=Path("/tmp/x.log"))
        failed = xr._build_result(rc=65, **kw)
        self.assertEqual(len(failed["diagnostics"]), 2)
        # Signature still path-free, so the circuit breaker behaviour is unchanged.
        self.assertNotIn("/Users/x/App", failed["errorSignature"])
        passed = xr._build_result(rc=0, **kw)
        self.assertEqual(passed["diagnostics"], [])

    def test_gate_message_names_file_and_line(self):
        result = xr._build_result(phase="3", project=None, rc=65, stdout="", stderr=STDERR,
                                  duration=1.0, log_path=Path("/tmp/x.log"))
        with mock.patch.object(xr, "scaffold_build", return_value=result):
            [check] = scaffold.check_scaffold_build_succeeded(Path("/p"), "App", {})
        self.assertFalse(check["passed"])
        self.assertIn("Foo.swift:12: cannot find 'bar' in scope", check["message"])

if __name__ == "__main__":
    unittest.main()
