#!/usr/bin/env python3
"""Executable checkpoints for the bounded Phase-5 build-fix loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from snapshot_runner import directories_for_phase  # noqa: E402
from spec_loader import load_spec  # noqa: E402
from state_store import load_json, load_state, state_file_for  # noqa: E402

SCHEMA_VERSION = 1


def _root(project: Path) -> Path:
    return project / ".autobot" / "build-fix" / "checkpoints"


def _targets(spec: dict, app_name: str) -> list[str]:
    # Phase 5 quality-engineer owns every file the build-fix loop may patch.
    targets = directories_for_phase(spec, "5", app_name)
    for relative in targets:
        path = Path(relative.rstrip("/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe checkpoint target: {relative}")
    return targets


def _copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(
        item for item in root.rglob("*")
        if item.is_file() and item.name != "checkpoint.json"
    ):
        relative = str(path.relative_to(root)).encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _metadata_hash(metadata: dict) -> str:
    protected = {key: value for key, value in metadata.items() if key != "metadataHash"}
    encoded = json.dumps(
        protected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _policy(spec: dict) -> tuple[dict, dict]:
    policy = (spec.get("policies") or {}).get("buildFixLoop") or {}
    return policy, policy.get("checkpoint") or {}


def _validate_save_policy(spec: dict, attempt: int) -> None:
    policy, checkpoint = _policy(spec)
    if not policy.get("enabled"):
        raise ValueError("buildFixLoop policy is disabled")
    flag = "saveBeforeFirstAttempt" if attempt == 0 else "saveAfterEachAttempt"
    if not checkpoint.get(flag):
        raise ValueError(f"buildFixLoop checkpoint.{flag} is disabled")
    max_attempts = int(policy.get("maxAttempts") or 0)
    if attempt < 0 or (max_attempts and attempt > max_attempts):
        raise ValueError(f"attempt {attempt} is outside buildFixLoop maxAttempts={max_attempts}")


def save_checkpoint(
    project: Path,
    spec: dict,
    state: dict,
    *,
    attempt: int,
    error_signature: str | None = None,
    diff_hash: str | None = None,
) -> dict:
    _validate_save_policy(spec, attempt)
    app_name = str(state.get("appName") or "")
    if not app_name:
        raise ValueError("state.appName is required")

    destination = _root(project) / f"attempt-{attempt}"
    temp = destination.with_name(f".{destination.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temp.mkdir(parents=True, exist_ok=False)
    targets = _targets(spec, app_name)
    present: list[str] = []
    try:
        for relative in targets:
            normalized = relative.rstrip("/")
            source = project / normalized
            if not source.exists():
                continue
            _copy(source, temp / normalized)
            present.append(normalized)
        metadata = {
            "schemaVersion": SCHEMA_VERSION,
            "buildId": state.get("buildId"),
            "appName": app_name,
            "attempt": attempt,
            "inputHash": ((state.get("phases") or {}).get("5") or {}).get("inputHash"),
            "errorSignature": error_signature,
            "diffHash": diff_hash,
            "targets": [value.rstrip("/") for value in targets],
            "presentTargets": present,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        metadata["contentHash"] = _tree_hash(temp)
        if metadata["diffHash"] is None:
            metadata["diffHash"] = metadata["contentHash"]
        metadata["metadataHash"] = _metadata_hash(metadata)
        (temp / "checkpoint.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(temp, destination)
        return metadata
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def _load_metadata(path: Path) -> dict:
    metadata = load_json(path / "checkpoint.json")
    if metadata.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(f"unsupported checkpoint schema: {metadata.get('schemaVersion')}")
    if metadata.get("metadataHash") != _metadata_hash(metadata):
        raise ValueError("checkpoint metadata hash mismatch")
    if metadata.get("contentHash") != _tree_hash(path):
        raise ValueError("checkpoint content hash mismatch")
    return metadata


def latest_checkpoint(project: Path, *, exclude_signature: str | None = None) -> dict:
    candidates: list[tuple[int, Path, dict]] = []
    for path in _root(project).glob("attempt-*"):
        try:
            metadata = _load_metadata(path)
            attempt = int(metadata["attempt"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if exclude_signature is not None and metadata.get("errorSignature") == exclude_signature:
            continue
        candidates.append((attempt, path, metadata))
    if not candidates:
        raise FileNotFoundError("no matching build-fix checkpoint")
    _, path, metadata = max(candidates, key=lambda value: value[0])
    return {**metadata, "path": str(path)}


def restore_checkpoint(
    project: Path,
    spec: dict,
    state: dict,
    *,
    attempt: int | None = None,
    exclude_signature: str | None = None,
) -> dict:
    policy, checkpoint = _policy(spec)
    if not policy.get("enabled"):
        raise ValueError("buildFixLoop policy is disabled")
    if exclude_signature is not None and not checkpoint.get("rollbackOnSignatureRepeat"):
        raise ValueError("buildFixLoop checkpoint.rollbackOnSignatureRepeat is disabled")
    chosen = (
        {**_load_metadata(_root(project) / f"attempt-{attempt}"),
         "path": str(_root(project) / f"attempt-{attempt}")}
        if attempt is not None
        else latest_checkpoint(project, exclude_signature=exclude_signature)
    )
    if chosen.get("buildId") and state.get("buildId") != chosen.get("buildId"):
        raise ValueError("checkpoint belongs to a different buildId")
    source_root = Path(chosen["path"]).resolve()
    checkpoint_root = _root(project).resolve()
    try:
        source_root.relative_to(checkpoint_root)
    except ValueError as exc:
        raise ValueError("checkpoint path is outside the project checkpoint root") from exc
    targets = [value.rstrip("/") for value in _targets(spec, str(state.get("appName") or ""))]
    for item in source_root.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"checkpoint contains unsupported symlink: {item}")

    backup = checkpoint_root / f".restore-backup.{os.getpid()}.{uuid.uuid4().hex}"
    backup.mkdir(parents=True, exist_ok=False)
    try:
        for relative in targets:
            destination = project / relative
            if destination.exists():
                _copy(destination, backup / relative)
        try:
            for relative in targets:
                destination = project / relative
                source = source_root / relative
                if destination.is_dir():
                    shutil.rmtree(destination)
                elif destination.exists():
                    destination.unlink()
                if source.exists():
                    _copy(source, destination)
        except BaseException:
            for relative in targets:
                destination = project / relative
                saved = backup / relative
                if destination.is_dir():
                    shutil.rmtree(destination)
                elif destination.exists():
                    destination.unlink()
                if saved.exists():
                    _copy(saved, destination)
            raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    return chosen


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("save", "latest", "restore"))
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--attempt", type=int)
    parser.add_argument("--error-signature")
    parser.add_argument("--diff-hash")
    parser.add_argument("--exclude-signature")
    args = parser.parse_args()
    project = Path(args.project_dir).resolve()
    spec = load_spec()
    state = load_state(state_file_for(project))
    if args.command == "save":
        if args.attempt is None:
            parser.error("save requires --attempt")
        result = save_checkpoint(
            project, spec, state, attempt=args.attempt,
            error_signature=args.error_signature, diff_hash=args.diff_hash,
        )
    elif args.command == "latest":
        result = latest_checkpoint(project, exclude_signature=args.exclude_signature)
    else:
        result = restore_checkpoint(
            project, spec, state, attempt=args.attempt,
            exclude_signature=args.exclude_signature,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
