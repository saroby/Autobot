"""upload.sh's redundant-binary classification is attempt-aware.

Failure mode sealed here (audit 2026-07-17): a "Redundant Binary Upload"
rejection means ASC already holds this bundle version — but whether that is
success depends on whether THIS run initiated the upload:

  - FIRST attempt (ATTEMPT==0): nothing was uploaded this run, so the ASC binary
    is from a PREVIOUS run. Treating it as already_uploaded would ship an OLD
    binary to review. Now a build_number_conflict → exit 6.
  - A LATER attempt (ATTEMPT>=1, after this run's upload initiated then failed
    ambiguously with a transient error): our own upload landed. Success →
    already_uploaded / exit 0.

Harness mirrors tests/test_release_artifact_scripts.py: a fake xcodebuild on
PATH produces the IPA, then fails with the chosen ASC message.
"""

from __future__ import annotations

import json
import os
import plistlib
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from conftest import PLUGIN_DIR

MACH_O_64_LE = struct.pack("<I", 0xFEEDFACF)

REDUNDANT_MESSAGE = (
    "error: Redundant Binary Upload. The bundle version must be higher than "
    "the previously uploaded version."
)
TRANSIENT_MESSAGE = "error: The request timed out. HTTP 503 service unavailable"

UPLOAD_SH = PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"


def _identity_plist() -> dict:
    return {
        "CFBundleIdentifier": "com.example.demo",
        "CFBundleShortVersionString": "1.2",
        "CFBundleVersion": "34",
        "CFBundleExecutable": "Demo",
        "ITSAppUsesNonExemptEncryption": False,
    }


def _make_executable(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_archive(root: Path) -> Path:
    archive = root / "Demo.xcarchive"
    app = archive / "Products" / "Applications" / "Demo.app"
    app.mkdir(parents=True)
    with (app / "Info.plist").open("wb") as stream:
        plistlib.dump(_identity_plist(), stream)
    (app / "Demo").write_bytes(MACH_O_64_LE + b"\0" * 28)
    return archive


def _export_ipa_snippet() -> str:
    return f'''
import plistlib, zipfile
from pathlib import Path
export = Path(args[args.index("-exportPath") + 1])
export.mkdir(parents=True, exist_ok=True)
plist = {repr(_identity_plist())}
with zipfile.ZipFile(export / "Demo.ipa", "w") as archive:
    archive.writestr("Payload/Demo.app/Info.plist", plistlib.dumps(plist))
    archive.writestr("Payload/Demo.app/Demo", bytes.fromhex("cffaedfe") + b"\\0" * 28)
'''


def _make_redundant_xcodebuild(path: Path) -> None:
    body = f'''#!{sys.executable}
import sys
args = sys.argv[1:]
{_export_ipa_snippet()}
print({REDUNDANT_MESSAGE!r})
sys.exit(70)
'''
    _make_executable(path, body)


def _make_transient_then_redundant_xcodebuild(path: Path, counter: Path) -> None:
    body = f'''#!{sys.executable}
import sys
from pathlib import Path
args = sys.argv[1:]
{_export_ipa_snippet()}
counter = Path({str(counter)!r})
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
if n == 0:
    print({TRANSIENT_MESSAGE!r})   # first attempt: ambiguous transient failure
    sys.exit(70)
print({REDUNDANT_MESSAGE!r})       # retry: our own upload already landed
sys.exit(70)
'''
    _make_executable(path, body)


def _run_upload(root: Path, xcodebuild_factory) -> tuple[subprocess.CompletedProcess, dict]:
    archive = _make_archive(root)
    (root / ".autobot").mkdir()
    (root / ".autobot" / "build-state.json").write_text(json.dumps({
        "buildId": "build-upload-1",
        "bundleId": "com.example.demo",
        "phases": {"5": {"inputHash": "input-hash-upload"}},
    }))

    bin_dir = root / "bin"
    bin_dir.mkdir()
    xcodebuild_factory(bin_dir / "xcodebuild")
    _make_executable(bin_dir / "codesign")

    env = os.environ.copy()
    for key in ("ASC_API_KEY_ID", "ASC_API_ISSUER_ID", "ASC_API_KEY_PATH"):
        env.pop(key, None)
    env.update({
        "PATH": f"{bin_dir}:{env['PATH']}",
        "CLAUDE_PROJECT_DIR": str(root),
        "AUTOBOT_CONFIG_DIR": str(root / "empty-config"),
        # retry the transient class without a real 30s sleep
        "AUTOBOT_UPLOAD_BACKOFF_SECONDS": "0",
    })

    inspect = subprocess.run(
        [sys.executable, str(PLUGIN_DIR / "scripts" / "artifact_provenance.py"),
         "inspect-archive", "--archive-path", str(archive)],
        env=env, capture_output=True, text=True,
    )
    assert inspect.returncode == 0, inspect.stdout + inspect.stderr
    archive_digest = json.loads(inspect.stdout)["archiveDigest"]
    (root / ".autobot" / "archive-status.json").write_text(json.dumps({
        "buildId": "build-upload-1",
        "bundleId": "com.example.demo",
        "archiveSha256": archive_digest,
    }))

    status_path = root / "upload-status.json"
    env["AUTOBOT_UPLOAD_STATUS_FILE"] = str(status_path)
    result = subprocess.run(
        ["bash", str(UPLOAD_SH),
         "--archive-path", str(archive),
         "--export-path", str(root / "export"),
         "--build-state", str(root / ".autobot" / "build-state.json"),
         "--archive-status", str(root / ".autobot" / "archive-status.json")],
        cwd=root, env=env, capture_output=True, text=True,
    )
    status = json.loads(status_path.read_text())
    return result, status


class TestRedundantBinaryClassification(unittest.TestCase):
    def test_first_attempt_redundant_is_build_number_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, status = _run_upload(Path(tmp), _make_redundant_xcodebuild)
            combined = (result.stdout + result.stderr).lower()
        self.assertEqual(result.returncode, 6, result.stdout + result.stderr)
        self.assertEqual(status["result"], "build_number_conflict")
        self.assertEqual(status["upload_success"], False)
        self.assertEqual(status["reason"], "build_number_conflict")
        self.assertIn("build number", combined)

    def test_redundant_after_transient_retry_is_already_uploaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counter = root / "xcodebuild-calls"
            result, status = _run_upload(
                root, lambda p: _make_transient_then_redundant_xcodebuild(p, counter),
            )
            calls = int(counter.read_text())
        self.assertEqual(calls, 2, "expected one transient failure then one retry")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(status["result"], "already_uploaded")
        self.assertEqual(status["upload_success"], True)
        self.assertEqual(status["buildId"], "build-upload-1")


if __name__ == "__main__":
    unittest.main()
