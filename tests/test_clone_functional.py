from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clone_functional.py"
SPEC = importlib.util.spec_from_file_location("clone_functional_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
clone_functional = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clone_functional)


class _Output(io.StringIO):
    def reconfigure(self, **_kwargs) -> None:
        pass


def _run_gate(tmp_path, *, mapped, observed, replay_state, landed_state=None):
    (tmp_path / "views.json").write_text(
        json.dumps({"initial_state": "home", "views": {state: {} for state in mapped}}),
        encoding="utf-8",
    )
    stdout = _Output()
    stderr = _Output()
    with (
        mock.patch.object(clone_functional.flow_codegen, "load_flow", return_value=[]),
        mock.patch.object(
            clone_functional.flow_codegen,
            "all_transitions",
            return_value=(observed, []),
        ),
        mock.patch.object(clone_functional, "replay", return_value=replay_state),
        mock.patch.object(clone_functional, "tap", return_value="measured"),
        mock.patch.object(clone_functional, "current_state", return_value=landed_state),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        result = clone_functional.main(
            ["clone_functional.py", str(tmp_path), "fake-simulator-udid"]
        )
    return result, stdout.getvalue(), stderr.getvalue()


class TestFunctionalGate(unittest.TestCase):
    def run_gate(self, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            return _run_gate(Path(temp), **kwargs)

    def test_unreachable_mapped_screen_fails_the_gate(self):
        result, stdout, stderr = self.run_gate(
            mapped=["home", "orphan"], observed=[], replay_state="home")

        self.assertEqual(result, 1)
        self.assertIn("ERROR: 1 mapped screen(s) have no observed path from home", stderr)
        self.assertIn("1 unreachable mapped screen(s)", stderr)
        self.assertNotIn("OK:", stdout)

    def test_observed_transition_from_unreachable_source_fails_the_gate(self):
        result, stdout, stderr = self.run_gate(
            mapped=["home"], observed=[("orphan", "Open details", "details")],
            replay_state="home")

        self.assertEqual(result, 1)
        self.assertIn("ERROR: 1 observed transition(s) start from an unreachable screen", stderr)
        self.assertIn("1 skipped transition(s)", stderr)
        self.assertNotIn("OK:", stdout)

    def test_fully_reachable_flow_still_passes(self):
        result, stdout, stderr = self.run_gate(
            mapped=["home", "details"],
            observed=[("home", "Open details", "details")],
            replay_state="home", landed_state="details")

        self.assertEqual(result, 0)
        self.assertIn("OK: the reproduction navigates exactly like the observed flow", stdout)
        self.assertNotIn("ERROR:", stderr)


if __name__ == "__main__":
    unittest.main()
