"""Smoke coverage for every entry in gate_checks.registry.GATE_CHECKS.

Weakness audit finding: 24-26 of the 53+ procedural gate checks had zero test
references — an exception or a signature/shape break in any of them would go
undetected until a live pipeline run hit that exact gate. This is not a
semantic/verdict-matrix test (that is a separate workstream); it only proves
the contract every caller (gate_runner._evaluate_descriptor) relies on:
each check is callable as fn(project_dir, app_name, state), never raises on a
minimal/empty project, and returns a list of dicts shaped like
gate_checks._helpers._ok() output (`check` + `passed` keys — NOT `name`; the
audit report's prose said "name" but the actual `_ok()` helper emits `check`,
and current code is the source of truth here).

Iterates GATE_CHECKS directly so any check added in the future is covered
automatically without editing this file.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from gate_checks.registry import GATE_CHECKS  # noqa: E402

APP = "Demo"

# Minimal state a check might reasonably look at (buildId/bundleId/appName are
# read by several checks for identity comparisons; phases is the shape every
# check that touches build-state expects, even when empty).
MINIMAL_STATE = {
    "buildId": "smoke-build-1",
    "bundleId": "com.example.demo",
    "appName": APP,
    "phases": {},
}


class GateChecksSmokeTest(unittest.TestCase):
    """One test per registered check — failures point straight at the name."""


def _make_test(name, fn):
    def test(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            try:
                result = fn(project, APP, MINIMAL_STATE)
            except Exception as exc:  # noqa: BLE001 - the thing under test
                self.fail(f"{name} raised {type(exc).__name__}: {exc}")
        self.assertIsInstance(result, list, f"{name} did not return a list")
        for entry in result:
            self.assertIsInstance(entry, dict, f"{name} sub-result is not a dict: {entry!r}")
            self.assertIn("check", entry, f"{name} sub-result missing 'check' key: {entry!r}")
            self.assertIn("passed", entry, f"{name} sub-result missing 'passed' key: {entry!r}")
    return test


for _name, _fn in GATE_CHECKS.items():
    setattr(GateChecksSmokeTest, f"test_{_name}_is_callable_and_shaped", _make_test(_name, _fn))


if __name__ == "__main__":
    unittest.main()
