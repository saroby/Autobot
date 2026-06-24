from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from conftest import import_runtime_modules

import_runtime_modules()

from spec_bundle import assemble_parts, diff_bundle, split_bundle, write_bundle  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "spec" / "pipeline.json"


class TestSpecBundle(unittest.TestCase):
    def test_split_bundle_round_trips_current_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            parts = Path(tmp) / "parts"
            split_bundle(PIPELINE, parts)
            assembled = assemble_parts(parts)
            with PIPELINE.open(encoding="utf-8") as handle:
                bundled = json.load(handle)
            self.assertEqual(assembled, bundled)

    def test_diff_bundle_reports_section_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bundle = tmpdir / "pipeline.json"
            parts = tmpdir / "parts"
            split_bundle(PIPELINE, parts)

            with PIPELINE.open(encoding="utf-8") as handle:
                bundled = json.load(handle)
            bundled["schemaVersion"] = -1
            with bundle.open("w", encoding="utf-8") as handle:
                json.dump(bundled, handle)

            self.assertEqual(diff_bundle(bundle, parts), ["spec section drift: schemaVersion"])

    def test_write_bundle_assembles_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            bundle = tmpdir / "pipeline.json"
            parts = tmpdir / "parts"
            split_bundle(PIPELINE, parts)
            write_bundle(bundle, parts)
            self.assertEqual(diff_bundle(bundle, parts), [])


if __name__ == "__main__":
    unittest.main()
