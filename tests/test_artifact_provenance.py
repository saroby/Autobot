from __future__ import annotations

import plistlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from conftest import import_runtime_modules

import_runtime_modules()

from artifact_provenance import (  # noqa: E402
    ArtifactVerificationError,
    deterministic_tree_digest,
    inspect_archive,
    inspect_ipa,
)


MACH_O_64_LE = struct.pack("<I", 0xFEEDFACF)


def _plist(executable: str = "Demo") -> bytes:
    import io
    out = io.BytesIO()
    plistlib.dump({
        "CFBundleIdentifier": "com.example.demo",
        "CFBundleShortVersionString": "1.2",
        "CFBundleVersion": "34",
        "CFBundleExecutable": executable,
        "ITSAppUsesNonExemptEncryption": False,
    }, out)
    return out.getvalue()


class TestArchiveInspection(unittest.TestCase):
    def test_requires_exactly_one_embedded_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Demo.xcarchive"
            (archive / "Products" / "Applications").mkdir(parents=True)
            with self.assertRaisesRegex(ArtifactVerificationError, "exactly one"):
                inspect_archive(archive, verify_signature=False)

    def test_reads_identity_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Demo.xcarchive"
            app = archive / "Products" / "Applications" / "Demo.app"
            app.mkdir(parents=True)
            (app / "Info.plist").write_bytes(_plist())
            (app / "Demo").write_bytes(MACH_O_64_LE + b"\0" * 28)
            result = inspect_archive(archive, verify_signature=False)
            self.assertEqual(result["bundleId"], "com.example.demo")
            self.assertEqual(result["version"], "1.2")
            self.assertEqual(result["build"], "34")
            self.assertEqual(len(result["artifactDigest"]), 64)
            self.assertEqual(len(result["archiveDigest"]), 64)

    def test_archive_reads_each_regular_file_once_for_both_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Demo.xcarchive"
            app = archive / "Products" / "Applications" / "Demo.app"
            app.mkdir(parents=True)
            (app / "Info.plist").write_bytes(_plist())
            (app / "Demo").write_bytes(MACH_O_64_LE + b"\0" * 28)
            original = __import__("artifact_provenance")._stream_digest
            with mock.patch("artifact_provenance._stream_digest", wraps=original) as stream_digest:
                result = inspect_archive(archive, verify_signature=False)
            self.assertEqual(stream_digest.call_count, 2)
            self.assertEqual(result["artifactDigest"], deterministic_tree_digest(app))


class TestIPAInspection(unittest.TestCase):
    def test_requires_exactly_one_payload_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipa = Path(tmp) / "Demo.ipa"
            with zipfile.ZipFile(ipa, "w") as zf:
                zf.writestr("README", "empty")
            with self.assertRaisesRegex(ArtifactVerificationError, "exactly one"):
                inspect_ipa(ipa)

    def test_rejects_non_macho_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipa = Path(tmp) / "Demo.ipa"
            with zipfile.ZipFile(ipa, "w") as zf:
                zf.writestr("Payload/Demo.app/Info.plist", _plist())
                zf.writestr("Payload/Demo.app/Demo", b"not-macho")
            with self.assertRaisesRegex(ArtifactVerificationError, "Mach-O"):
                inspect_ipa(ipa)
