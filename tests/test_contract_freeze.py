"""Tests for scripts/contract_freeze.py — frozen-by-default contracts on
/autobot:resume into Phase 1.

The mechanism protects already-written downstream code (Views/Services) from a
nondeterministic architect re-run silently renaming the type contract.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from conftest import SCRIPTS_DIR, _scoped_env, import_runtime_modules

import_runtime_modules()

from contract_freeze import apply, decide  # noqa: E402
from spec_loader import load_spec  # noqa: E402

APP = "DemoApp"


def _make_snapshot(proj: Path, models: dict[str, str]) -> None:
    """Create a Models snapshot + checksum, as snapshot-contracts.sh save would."""
    contracts = proj / ".autobot" / "contracts"
    snap = contracts / "phase-1-models"
    snap.mkdir(parents=True)
    for name, body in models.items():
        (snap / f"{name}.swift").write_text(body)
    (contracts / "models.sha256").write_text("deadbeef\n")


def _make_models(proj: Path, models: dict[str, str]) -> None:
    d = proj / APP / "Models"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in models.items():
        (d / f"{name}.swift").write_text(body)


def _make_downstream(proj: Path, rel: str = "DemoApp/Views", name: str = "HomeView") -> None:
    d = proj / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.swift").write_text(f"struct {name} {{}}")


def _state() -> dict:
    return {"appName": APP, "idea": "demo", "phases": {}}


class TestDecide(unittest.TestCase):
    def setUp(self):
        self.spec = load_spec()

    def test_frozen_when_snapshot_and_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_snapshot(proj, {"Workout": 'struct Workout { var title = "" }'})
            _make_downstream(proj)
            r = decide(proj, self.spec, _state(), "1")
            self.assertTrue(r["frozen"])
            self.assertEqual(r["action"], "restore")

    def test_regenerate_flag_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_snapshot(proj, {"Workout": "struct Workout {}"})
            _make_downstream(proj)
            r = decide(proj, self.spec, _state(), "1", regenerate=True)
            self.assertFalse(r["frozen"])
            self.assertEqual(r["action"], "regenerate")

    def test_no_downstream_not_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_snapshot(proj, {"Workout": "struct Workout {}"})
            r = decide(proj, self.spec, _state(), "1")
            self.assertFalse(r["frozen"])
            self.assertFalse(r["downstreamPresent"])
            self.assertEqual(r["action"], "regenerate")

    def test_no_snapshot_not_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_downstream(proj)
            r = decide(proj, self.spec, _state(), "1")
            self.assertFalse(r["frozen"])
            self.assertFalse(r["snapshotPresent"])

    def test_backend_dir_is_not_swift_downstream(self):
        # backend/ is a Phase-4 write dir but holds no .swift — must not trip freeze.
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_snapshot(proj, {"Workout": "struct Workout {}"})
            (proj / "backend").mkdir()
            (proj / "backend" / "main.py").write_text("print('x')")
            r = decide(proj, self.spec, _state(), "1")
            self.assertFalse(r["frozen"])


class TestApply(unittest.TestCase):
    def setUp(self):
        self.spec = load_spec()

    def test_apply_restores_models_from_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            # snapshot holds the OLD contract (title); Models holds a DRIFTED one (name).
            _make_snapshot(proj, {"Workout": 'struct Workout { var title = "" }'})
            _make_models(proj, {"Workout": 'struct Workout { var name = "" }'})
            _make_downstream(proj)
            r = apply(proj, self.spec, _state(), "1")
            self.assertTrue(r["frozen"])
            self.assertTrue(r["restored"])
            restored = (proj / APP / "Models" / "Workout.swift").read_text()
            self.assertIn("title", restored)
            self.assertNotIn("name", restored)
            # A validated contracts_frozen event was appended.
            log = (proj / ".autobot" / "build-log.jsonl").read_text()
            self.assertIn("contracts_frozen", log)

    def test_apply_leaves_models_untouched_when_regenerate(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            _make_snapshot(proj, {"Workout": 'struct Workout { var title = "" }'})
            _make_models(proj, {"Workout": 'struct Workout { var name = "" }'})
            _make_downstream(proj)
            r = apply(proj, self.spec, _state(), "1", regenerate=True)
            self.assertFalse(r["frozen"])
            # Architect is expected to overwrite later; apply must not pre-empt it.
            self.assertIn("name", (proj / APP / "Models" / "Workout.swift").read_text())


class TestPipelinePassthrough(unittest.TestCase):
    def test_pipeline_sh_freeze_contracts_decide(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            (proj / ".autobot").mkdir()
            (proj / ".autobot" / "build-state.json").write_text(
                json.dumps({"buildId": "b", "appName": APP, "displayName": "Demo", "phases": {}})
            )
            _make_snapshot(proj, {"Workout": "struct Workout {}"})
            _make_downstream(proj)
            proc = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "pipeline.sh"), "freeze-contracts", "decide", "--phase", "1"],
                cwd=proj,
                capture_output=True,
                text=True,
                env=_scoped_env(proj),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertTrue(out["frozen"])


if __name__ == "__main__":
    unittest.main()
