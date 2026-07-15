#!/usr/bin/env python3
"""Deterministic identity and verification for build and release artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from state_store import load_json


SCHEMA_VERSION = 1
MANIFEST_NAME = "artifact-provenance.json"
MACH_O_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
}


class ArtifactVerificationError(ValueError):
    pass


def _require_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ArtifactVerificationError(f"missing {field}")
    return text


def _is_macho_bytes(head: bytes) -> bool:
    return head[:4] in MACH_O_MAGICS


def _stream_digest(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _tree_digests(root: Path, nested_root: Path | None = None) -> tuple[str, str | None]:
    """Hash a tree and, when requested, a nested tree in one filesystem pass."""
    root = root.resolve()
    nested_root = nested_root.resolve() if nested_root is not None else None
    if not root.is_dir():
        raise ArtifactVerificationError(f"artifact directory missing: {root}")
    if nested_root is not None:
        try:
            nested_root.relative_to(root)
        except ValueError as exc:
            raise ArtifactVerificationError("nested artifact is outside archive") from exc
        if not nested_root.is_dir():
            raise ArtifactVerificationError(f"artifact directory missing: {nested_root}")

    digests = [(root, hashlib.sha256())]
    if nested_root is not None:
        digests.append((nested_root, hashlib.sha256()))
    for entry in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            kind = b"L"
            content_digest = hashlib.sha256(os.readlink(entry).encode("utf-8")).digest()
        elif stat.S_ISDIR(mode):
            kind = b"D"
            content_digest = hashlib.sha256(b"").digest()
        elif stat.S_ISREG(mode):
            kind = b"F"
            content_digest = _stream_digest(entry)
        else:
            raise ArtifactVerificationError(f"unsupported artifact entry: {entry}")
        for digest_root, digest in digests:
            # Path.rglob("*") does not include its own root. Preserve that
            # exact contract for a nested digest computed during the outer
            # traversal; otherwise a synthetic "." directory changes it.
            if entry == digest_root:
                continue
            try:
                rel = entry.relative_to(digest_root).as_posix().encode("utf-8")
            except ValueError:
                continue
            digest.update(kind + b"\0" + rel + b"\0")
            digest.update(f"{stat.S_IMODE(mode):04o}".encode("ascii") + b"\0")
            digest.update(content_digest)
    return digests[0][1].hexdigest(), (digests[1][1].hexdigest() if nested_root else None)


def deterministic_tree_digest(root: Path) -> str:
    """Hash names, types, executable modes, symlink targets, and file bytes.

    Timestamps and absolute paths are excluded, so the digest is stable for an
    unchanged bundle while still detecting any content or layout mutation.
    """
    return _tree_digests(root)[0]


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_app_bundle(
    app_path: Path,
    *,
    expected_name: str | None = None,
    verify_signature: bool = False,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    app_path = app_path.resolve()
    if not app_path.is_dir() or app_path.suffix != ".app":
        raise ArtifactVerificationError(f"app bundle missing: {app_path}")
    plist_path = app_path / "Info.plist"
    if not plist_path.is_file():
        raise ArtifactVerificationError(f"Info.plist missing: {plist_path}")
    try:
        with plist_path.open("rb") as stream:
            plist = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ArtifactVerificationError(f"invalid Info.plist: {exc}") from exc

    bundle_id = _require_text(plist.get("CFBundleIdentifier"), "CFBundleIdentifier")
    version = _require_text(plist.get("CFBundleShortVersionString"), "CFBundleShortVersionString")
    build = _require_text(plist.get("CFBundleVersion"), "CFBundleVersion")
    executable_name = _require_text(plist.get("CFBundleExecutable"), "CFBundleExecutable")
    if expected_name and app_path.stem != expected_name:
        raise ArtifactVerificationError(
            f"app name mismatch: expected {expected_name}, got {app_path.stem}"
        )
    executable = app_path / executable_name
    if not executable.is_file():
        raise ArtifactVerificationError(f"bundle executable missing: {executable}")
    try:
        with executable.open("rb") as stream:
            head = stream.read(4)
    except OSError as exc:
        raise ArtifactVerificationError(f"cannot read bundle executable: {exc}") from exc
    if not _is_macho_bytes(head):
        raise ArtifactVerificationError(f"bundle executable is not Mach-O: {executable}")

    codesign_status = "not_requested"
    if verify_signature:
        if shutil.which("codesign") is None:
            raise ArtifactVerificationError("codesign unavailable for release artifact verification")
        proc = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app_path)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()[:240]
            raise ArtifactVerificationError(f"codesign verification failed: {detail}")
        codesign_status = "verified"

    return {
        "appPath": str(app_path),
        "appName": app_path.stem,
        "bundleId": bundle_id,
        "version": version,
        "build": build,
        "executable": executable_name,
        "artifactDigest": artifact_digest or deterministic_tree_digest(app_path),
        "digestAlgorithm": "sha256-tree-v1",
        "codesignStatus": codesign_status,
    }


def find_app_in_derived_data(derived_data_path: Path, app_name: str) -> Path:
    products = derived_data_path / "Build" / "Products"
    preferred = products / "Debug-iphonesimulator" / f"{app_name}.app"
    if preferred.is_dir():
        return preferred.resolve()
    candidates = sorted(products.glob(f"*-iphonesimulator/{app_name}.app"))
    candidates = [candidate for candidate in candidates if candidate.is_dir()]
    if len(candidates) != 1:
        raise ArtifactVerificationError(
            f"app_artifact_missing: expected exactly one {app_name}.app under {products}, "
            f"found {len(candidates)}"
        )
    return candidates[0].resolve()


def write_app_manifest(
    app_path: Path,
    manifest_path: Path,
    *,
    build_id: str,
    app_name: str,
    attempt: int,
    derived_data_path: Path,
) -> dict[str, Any]:
    app_path = app_path.resolve()
    derived_data_path = derived_data_path.resolve()
    try:
        app_path.relative_to(derived_data_path)
    except ValueError as exc:
        raise ArtifactVerificationError("app path is outside attempt-local DerivedData") from exc
    identity = inspect_app_bundle(app_path, expected_name=app_name)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "buildId": build_id,
        "phase": 5,
        "attempt": attempt,
        "derivedDataPath": str(derived_data_path),
        **identity,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_name(f"{manifest_path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, manifest_path)
    return manifest


def load_verified_app_manifest(
    manifest_path: Path,
    *,
    expected_build_id: str,
    expected_app_name: str,
) -> dict[str, Any]:
    try:
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"invalid provenance manifest: {exc}") from exc
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ArtifactVerificationError("unsupported provenance manifest schema")
    if manifest.get("buildId") != expected_build_id:
        raise ArtifactVerificationError("provenance buildId does not match current build")
    if manifest.get("appName") != expected_app_name:
        raise ArtifactVerificationError("provenance appName does not match requested app")
    expected_derived_data = (manifest_path.parent / "DerivedData").resolve()
    if manifest.get("phase") != 5:
        raise ArtifactVerificationError("provenance phase is not Phase 5")
    try:
        expected_attempt = int(manifest_path.parent.name.removeprefix("attempt-"))
    except ValueError as exc:
        raise ArtifactVerificationError("provenance manifest is outside an attempt directory") from exc
    if manifest.get("attempt") != expected_attempt:
        raise ArtifactVerificationError("provenance attempt does not match manifest directory")
    app_path = Path(_require_text(manifest.get("appPath"), "appPath")).resolve()
    derived_data = Path(_require_text(manifest.get("derivedDataPath"), "derivedDataPath")).resolve()
    if derived_data != expected_derived_data:
        raise ArtifactVerificationError("provenance DerivedData does not belong to this attempt")
    try:
        app_path.relative_to(derived_data)
    except ValueError as exc:
        raise ArtifactVerificationError("manifest app path is outside DerivedData") from exc
    current = inspect_app_bundle(app_path, expected_name=expected_app_name)
    if current["artifactDigest"] != manifest.get("artifactDigest"):
        raise ArtifactVerificationError("artifact digest does not match provenance manifest")
    for field in ("bundleId", "version", "build", "executable"):
        if current[field] != manifest.get(field):
            raise ArtifactVerificationError(f"artifact {field} does not match provenance manifest")
    return {**manifest, "appPath": str(app_path)}


def inspect_archive(archive_path: Path, *, verify_signature: bool = True) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    apps_dir = archive_path / "Products" / "Applications"
    apps = sorted(path for path in apps_dir.glob("*.app") if path.is_dir())
    if len(apps) != 1:
        raise ArtifactVerificationError(
            f"archive must contain exactly one embedded app; found {len(apps)}"
        )
    archive_digest, app_digest = _tree_digests(archive_path, apps[0])
    identity = inspect_app_bundle(
        apps[0], verify_signature=verify_signature, artifact_digest=app_digest
    )
    return {
        "artifactType": "xcarchive",
        "archivePath": str(archive_path),
        "archiveDigest": archive_digest,
        **identity,
    }


def inspect_ipa(ipa_path: Path) -> dict[str, Any]:
    ipa_path = ipa_path.resolve()
    if not ipa_path.is_file():
        raise ArtifactVerificationError(f"IPA missing: {ipa_path}")
    try:
        with zipfile.ZipFile(ipa_path) as archive:
            plist_names = sorted(
                name for name in archive.namelist()
                if name.startswith("Payload/")
                and name.count("/") == 2
                and name.endswith(".app/Info.plist")
            )
            if len(plist_names) != 1:
                raise ArtifactVerificationError(
                    f"IPA must contain exactly one Payload app; found {len(plist_names)}"
                )
            plist_name = plist_names[0]
            try:
                plist = plistlib.loads(archive.read(plist_name))
            except (KeyError, plistlib.InvalidFileException) as exc:
                raise ArtifactVerificationError(f"invalid IPA Info.plist: {exc}") from exc
            bundle_id = _require_text(plist.get("CFBundleIdentifier"), "CFBundleIdentifier")
            version = _require_text(plist.get("CFBundleShortVersionString"), "CFBundleShortVersionString")
            build = _require_text(plist.get("CFBundleVersion"), "CFBundleVersion")
            executable_name = _require_text(plist.get("CFBundleExecutable"), "CFBundleExecutable")
            app_root = plist_name.removesuffix("Info.plist")
            executable_path = app_root + executable_name
            try:
                with archive.open(executable_path) as executable:
                    head = executable.read(4)
            except KeyError as exc:
                raise ArtifactVerificationError(
                    f"IPA bundle executable missing: {executable_path}"
                ) from exc
            if not _is_macho_bytes(head):
                raise ArtifactVerificationError(
                    f"IPA bundle executable is not Mach-O: {executable_path}"
                )
    except zipfile.BadZipFile as exc:
        raise ArtifactVerificationError(f"invalid IPA zip: {exc}") from exc

    return {
        "artifactType": "ipa",
        "ipaPath": str(ipa_path),
        "appName": Path(app_root.rstrip("/")).stem,
        "bundleId": bundle_id,
        "version": version,
        "build": build,
        "executable": executable_name,
        "artifactDigest": file_digest(ipa_path),
        "digestAlgorithm": "sha256-file-v1",
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    archive = sub.add_parser("inspect-archive")
    archive.add_argument("--archive-path", required=True)
    archive.add_argument("--skip-codesign", action="store_true")
    ipa = sub.add_parser("inspect-ipa")
    ipa.add_argument("--ipa-path", required=True)
    args = parser.parse_args()
    try:
        if args.command == "inspect-archive":
            result = inspect_archive(Path(args.archive_path), verify_signature=not args.skip_codesign)
        else:
            result = inspect_ipa(Path(args.ipa_path))
    except ArtifactVerificationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
