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


def _make_export_xcodebuild(path: Path, *, create_ipa: bool) -> None:
    if not create_ipa:
        _make_executable(path)
        return
    body = f'''#!{sys.executable}
import plistlib, sys, zipfile
from pathlib import Path
args = sys.argv[1:]
export = Path(args[args.index("-exportPath") + 1])
export.mkdir(parents=True, exist_ok=True)
plist = {repr(_identity_plist())}
with zipfile.ZipFile(export / "Demo.ipa", "w") as archive:
    archive.writestr("Payload/Demo.app/Info.plist", plistlib.dumps(plist))
    archive.writestr("Payload/Demo.app/Demo", bytes.fromhex("cffaedfe") + b"\\0" * 28)
'''
    _make_executable(path, body)


def _make_archive_xcodebuild(path: Path) -> None:
    body = f'''#!{sys.executable}
import plistlib, sys
from pathlib import Path
args = sys.argv[1:]
archive = Path(args[args.index("-archivePath") + 1])
app = archive / "Products" / "Applications" / "Demo.app"
app.mkdir(parents=True, exist_ok=True)
plist = {repr(_identity_plist())}
(app / "Info.plist").write_bytes(plistlib.dumps(plist))
(app / "Demo").write_bytes(bytes.fromhex("cffaedfe") + b"\\0" * 28)
'''
    _make_executable(path, body)


class TestArchiveFailClosed(unittest.TestCase):
    def test_missing_build_state_refuses_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "Demo.xcodeproj").mkdir()
            bin_dir = project / "bin"
            bin_dir.mkdir()
            _make_executable(bin_dir / "xcodebuild")
            status_path = project / "archive-status.json"
            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}:{env['PATH']}",
                "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR),
                "AUTOBOT_ARCHIVE_STATUS_FILE": str(status_path),
            })
            script = PLUGIN_DIR / "skills/autobot-archive-build/scripts/archive.sh"
            result = subprocess.run(
                ["bash", str(script), "--project-path", str(project), "--scheme", "Demo"],
                cwd=project, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn("build-state.json", result.stderr)
            status = json.loads(status_path.read_text())
            self.assertEqual(status["reason"], "missing_build_state")

    def test_success_status_records_packaged_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "Demo.xcodeproj").mkdir()
            (project / ".autobot").mkdir()
            (project / ".autobot" / "build-state.json").write_text(json.dumps({
                "buildId": "build-1",
                "bundleId": "com.example.demo",
                "phases": {"5": {"inputHash": "input-hash-1"}},
            }))
            bin_dir = project / "bin"
            bin_dir.mkdir()
            _make_archive_xcodebuild(bin_dir / "xcodebuild")
            _make_executable(bin_dir / "codesign")

            plugin = project / "plugin"
            (plugin / "scripts").mkdir(parents=True)
            _make_executable(plugin / "scripts" / "pipeline.sh")
            (plugin / "scripts" / "artifact_provenance.py").symlink_to(
                PLUGIN_DIR / "scripts" / "artifact_provenance.py"
            )

            status_path = project / "archive-status.json"
            env = os.environ.copy()
            env.update({
                "PATH": f"{bin_dir}:{env['PATH']}",
                "CLAUDE_PLUGIN_ROOT": str(plugin),
                "AUTOBOT_ARCHIVE_STATUS_FILE": str(status_path),
            })
            script = PLUGIN_DIR / "skills/autobot-archive-build/scripts/archive.sh"
            result = subprocess.run(
                ["bash", str(script), "--project-path", str(project), "--scheme", "Demo"],
                cwd=project, env=env, capture_output=True, text=True,
            )
            status = json.loads(status_path.read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(status["bundle_id"], "com.example.demo")
        self.assertEqual(status["version"], "1.2")
        self.assertEqual(status["build"], "34")
        self.assertEqual(len(status["artifact_digest"]), 64)
        self.assertEqual(len(status["archive_digest"]), 64)
        self.assertEqual(status["schemaVersion"], 1)
        self.assertEqual(status["buildId"], "build-1")
        self.assertEqual(status["bundleId"], "com.example.demo")
        self.assertEqual(status["buildNumber"], "34")
        self.assertEqual(status["inputManifestHash"], "input-hash-1")
        self.assertEqual(status["artifactSha256"], status["artifact_digest"])
        self.assertEqual(status["archiveSha256"], status["archive_digest"])


class TestUploadArtifactProof(unittest.TestCase):
    def test_upload_requires_explicit_build_and_archive_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = _make_archive(root)
            script = PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"
            missing_state = subprocess.run(
                ["bash", str(script), "--archive-path", str(archive)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(missing_state.returncode, 1)
            self.assertIn("--build-state", missing_state.stderr)

            (root / "build-state.json").write_text(json.dumps({
                "buildId": "build-upload-1",
                "bundleId": "com.example.demo",
            }))
            missing_archive_status = subprocess.run(
                ["bash", str(script), "--archive-path", str(archive),
                 "--build-state", str(root / "build-state.json")],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(missing_archive_status.returncode, 1)
            self.assertIn("--archive-status", missing_archive_status.stderr)

    def test_export_rejects_archive_bundle_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = _make_archive(root)
            state = root / "build-state.json"
            state.write_text(json.dumps({
                "buildId": "build-upload-1",
                "bundleId": "com.example.other",
            }))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            _make_executable(bin_dir / "codesign")
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            script = PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"
            result = subprocess.run(
                ["bash", str(script), "--archive-path", str(archive),
                 "--build-state", str(state), "--no-upload"],
                cwd=root, env=env, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("bundleId", result.stderr)

    def test_upload_rejects_archive_status_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = _make_archive(root)
            state = root / "build-state.json"
            state.write_text(json.dumps({
                "buildId": "build-upload-1",
                "bundleId": "com.example.demo",
            }))
            archive_status = root / "archive-status.json"
            archive_status.write_text(json.dumps({
                "buildId": "build-upload-1",
                "archiveSha256": "wrong-digest",
            }))
            bin_dir = root / "bin"
            bin_dir.mkdir()
            _make_executable(bin_dir / "codesign")
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            script = PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"
            result = subprocess.run(
                ["bash", str(script), "--archive-path", str(archive),
                 "--build-state", str(state),
                 "--archive-status", str(archive_status), "--dry-run"],
                cwd=root, env=env, capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("archive digest", result.stderr)

    def _run(self, root: Path, *, create_ipa: bool) -> tuple[subprocess.CompletedProcess, dict]:
        archive = _make_archive(root)
        (root / ".autobot").mkdir()
        (root / ".autobot" / "build-state.json").write_text(json.dumps({
            "buildId": "build-upload-1",
            "bundleId": "com.example.demo",
            "phases": {"5": {"inputHash": "input-hash-upload"}},
        }))
        export = root / "export"
        if not create_ipa:
            # A prior run's IPA must not be accepted as proof for this export.
            export.mkdir()
            (export / "Stale.ipa").write_bytes(b"stale")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _make_export_xcodebuild(bin_dir / "xcodebuild", create_ipa=create_ipa)
        _make_executable(bin_dir / "codesign")
        status_path = root / "upload-status.json"
        env = os.environ.copy()
        for key in ("APP_STORE_CONNECT_API_KEY_KEY_ID", "APP_STORE_CONNECT_API_KEY_ISSUER_ID", "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"):
            env.pop(key, None)
        env.update({
            "PATH": f"{bin_dir}:{env['PATH']}",
            "AUTOBOT_UPLOAD_STATUS_FILE": str(status_path),
        })
        script = PLUGIN_DIR / "skills/autobot-upload-build/scripts/upload.sh"
        result = subprocess.run(
            ["bash", str(script), "--archive-path", str(archive),
             "--export-path", str(export), "--build-state",
             str(root / ".autobot" / "build-state.json"), "--no-upload"],
            cwd=root, env=env, capture_output=True, text=True,
        )
        status = json.loads(status_path.read_text())
        return result, status

    def test_xcodebuild_zero_without_ipa_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, status = self._run(Path(tmp), create_ipa=False)
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertEqual(status["reason"], "ipa_artifact_missing")

    def test_status_records_archive_and_ipa_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, status = self._run(Path(tmp), create_ipa=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(status["archive_bundle_id"], "com.example.demo")
        self.assertEqual(status["ipa_bundle_id"], "com.example.demo")
        self.assertEqual(status["ipa_version"], "1.2")
        self.assertEqual(status["ipa_build"], "34")
        self.assertEqual(len(status["archive_digest"]), 64)
        self.assertEqual(len(status["ipa_digest"]), 64)
        self.assertEqual(status["schemaVersion"], 1)
        self.assertEqual(status["buildId"], "build-upload-1")
        self.assertEqual(status["bundleId"], "com.example.demo")
        self.assertEqual(status["version"], "1.2")
        self.assertEqual(status["buildNumber"], "34")
        self.assertEqual(status["inputManifestHash"], "input-hash-upload")
        self.assertEqual(status["archiveSha256"], status["archive_digest"])
        self.assertEqual(status["ipaSha256"], status["ipa_digest"])
        self.assertEqual(status["artifactSha256"], status["ipa_digest"])


if __name__ == "__main__":
    unittest.main()
