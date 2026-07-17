"""Gate 6→7 deploy-status writer↔reader contract.

The ONLY writer of .autobot/deploy-status.json is the Python heredoc in
agents/deployer.md Step 5 (aggregate schema: {timestamp, register, archive,
upload, invite, status}). check_deployment_attempt_recorded historically
looked for top-level archive_path/upload_success — keys that schema never
produces — so the gate soft-failed on every successful deploy and no test
executed either side. This round-trip extracts the snippet from deployer.md,
runs it against fake per-skill status files, and feeds the aggregate it wrote
into the gate check.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR, import_runtime_modules

import_runtime_modules()

from gate_checks.deploy import check_deployment_attempt_recorded  # noqa: E402

DEPLOYER = (PLUGIN_DIR / "agents/deployer.md").read_text(encoding="utf-8")

AGGREGATE_HEREDOC = re.compile(
    r"python3 - <<'PY'\s*\n(.*?)\nPY\s*$",
    re.DOTALL | re.MULTILINE,
)


def _extract_snippet() -> str:
    match = AGGREGATE_HEREDOC.search(DEPLOYER)
    if match is None:
        raise AssertionError("deployer.md: Step 5 aggregation heredoc not found")
    return match.group(1)


class _TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".autobot").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_status(self, name: str, payload: dict) -> None:
        (self.proj / ".autobot" / f"{name}-status.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def _run_snippet(self) -> None:
        result = subprocess.run(
            [sys.executable, "-"], input=_extract_snippet(),
            capture_output=True, text=True, cwd=self.proj,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def _gate(self) -> dict:
        results = {r["check"]: r
                   for r in check_deployment_attempt_recorded(self.proj, "Demo", {})}
        return results


class TestDeployStatusRoundTrip(_TempProject):
    """deployer.md Step 5 output must satisfy the Gate 6→7 check as-is."""

    def test_uploaded_aggregate_passes_gate(self):
        self._write_status("register", {"result": "registered", "bundle_id": "com.x.demo"})
        self._write_status("archive", {"result": "archived", "archive_path": "build/Demo.xcarchive"})
        self._write_status("upload", {"upload_success": True, "ipa_path": "build/Demo.ipa"})
        self._write_status("invite", {"emails_invited": 1})
        self._run_snippet()

        data = json.loads((self.proj / ".autobot" / "deploy-status.json").read_text())
        self.assertEqual(data["status"], "uploaded")

        r = self._gate()
        self.assertTrue(r["deploy_status_file"]["passed"])
        self.assertTrue(r["deploy_has_result"]["passed"], r["deploy_has_result"]["message"])

    def test_archived_only_aggregate_passes_gate(self):
        # Upload failed/skipped but the archive succeeded → still a recorded attempt.
        self._write_status("archive", {"result": "archived", "archive_path": "build/Demo.xcarchive"})
        self._run_snippet()

        data = json.loads((self.proj / ".autobot" / "deploy-status.json").read_text())
        self.assertEqual(data["status"], "archived")
        self.assertTrue(self._gate()["deploy_has_result"]["passed"])

    def test_failed_aggregate_fails_result_subcheck(self):
        self._write_status("upload", {"upload_success": False})
        self._run_snippet()

        data = json.loads((self.proj / ".autobot" / "deploy-status.json").read_text())
        self.assertEqual(data["status"], "failed")
        r = self._gate()
        self.assertTrue(r["deploy_status_file"]["passed"])
        self.assertFalse(r["deploy_has_result"]["passed"])


class TestDeployStatusLegacyAndErrors(_TempProject):
    def test_legacy_flat_schema_still_accepted(self):
        (self.proj / ".autobot" / "deploy-status.json").write_text(
            json.dumps({"archive_path": "build/Demo.xcarchive", "upload_success": True})
        )
        self.assertTrue(self._gate()["deploy_has_result"]["passed"])

    def test_garbled_json_fails(self):
        (self.proj / ".autobot" / "deploy-status.json").write_text("{not json")
        self.assertFalse(self._gate()["deploy_has_result"]["passed"])

    def test_missing_file_reports_only_existence_subcheck(self):
        r = self._gate()
        self.assertFalse(r["deploy_status_file"]["passed"])
        self.assertNotIn("deploy_has_result", r)


if __name__ == "__main__":
    unittest.main()
