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
_RESTORE_JOURNAL = "restore-journal.json"


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


def _orphan_pid(name: str) -> str | None:
    """Owner pid encoded in `.restore-backup.<pid>.<hex>` / `.attempt-N.<pid>.<hex>.tmp`."""
    parts = name.split(".")
    if name.startswith(".restore-backup.") and len(parts) >= 4:
        return parts[2]
    if name.startswith(".attempt-") and name.endswith(".tmp") and len(parts) >= 5:
        return parts[2]
    return None


def _sweep_orphans(root: Path) -> None:
    """Remove restore-backup/save-temp dirs whose owner process is dead."""
    for path in root.iterdir():
        pid = _orphan_pid(path.name)
        if pid is None or pid == str(os.getpid()):
            continue
        try:
            os.kill(int(pid), 0)
            continue  # owner still alive — not an orphan
        except (ProcessLookupError, ValueError):
            pass
        except OSError:
            continue  # PermissionError etc. — assume alive
        shutil.rmtree(path, ignore_errors=True)


def _apply_targets(project: Path, source_root: Path, targets: list[str]) -> None:
    """Replace each target in the working tree with the checkpoint's copy.

    Idempotent: re-running after a partial run converges on the checkpoint.
    """
    for relative in targets:
        destination = project / relative
        source = source_root / relative
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        if source.exists():
            _copy(source, destination)


def _active_build_id(project: Path) -> str | None:
    """buildId of the project's live build-state, or None when unavailable.

    Recovery runs even when no build-state exists (checkpoint-only tests, early
    aborts), so a missing/unreadable state degrades to None rather than raising
    — which disables the cross-build guard and falls back to same-build replay.
    """
    path = state_file_for(project)
    if not path.is_file():
        return None
    try:
        state = load_state(path)
    except (Exception, SystemExit):  # noqa: BLE001 — recovery must never crash
        return None
    return state.get("buildId") if isinstance(state, dict) else None


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via tmp + os.replace so a crash can't leave a half-written
    journal the recovery path would then choke on."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _recover_interrupted_restore(project: Path) -> None:
    """Converge a restore that died (SIGKILL/power loss) mid delete-copy.

    restore_checkpoint journals the in-flight attempt before its destructive
    loop; if the journal survives, the working tree may be a mix of old and
    checkpoint files. Re-applying the (integrity-checked) attempt is
    idempotent. Called on every save/latest/restore entry.
    """
    root = _root(project)
    if not root.is_dir():
        return
    journal_path = root / _RESTORE_JOURNAL
    if journal_path.is_file():
        journal = load_json(journal_path)
        journal_build_id = journal.get("buildId")
        active_build_id = _active_build_id(project)
        # Cross-build guard: a journal left by build A must never replay onto
        # build B's working tree (it would overwrite B's files with A's
        # checkpoint). Only replay when the journal's build matches the live
        # build; on a definite mismatch, quarantine the journal without
        # touching any file.
        if journal_build_id and active_build_id and journal_build_id != active_build_id:
            quarantine = journal_path.with_name(
                f"{_RESTORE_JOURNAL}.quarantined.{os.getpid()}.{uuid.uuid4().hex}"
            )
            journal_path.rename(quarantine)
            print(
                f"WARN: restore journal buildId={journal_build_id} does not match "
                f"active buildId={active_build_id}; quarantined to {quarantine.name} "
                "without touching the working tree",
                file=sys.stderr,
            )
        else:
            attempt_dir = root / f"attempt-{journal['attempt']}"
            metadata = _load_metadata(attempt_dir)  # raises loudly if tampered/corrupt
            targets = [value.rstrip("/") for value in metadata["targets"]]
            for relative in targets:
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError(f"unsafe checkpoint target: {relative}")
            _apply_targets(project, attempt_dir, targets)
            journal_path.unlink(missing_ok=True)
    # Housekeeping runs AFTER the integrity-critical journal recovery so a
    # tampered/corrupt journal surfaces before we sweep any scratch dirs.
    _sweep_orphans(root)


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
    _recover_interrupted_restore(project)
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
    _recover_interrupted_restore(project)
    candidates: list[tuple[int, Path, dict]] = []
    for path in _root(project).glob("attempt-*"):
        try:
            metadata = _load_metadata(path)
            attempt = int(metadata["attempt"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"WARN: checkpoint {path} skipped: {exc}", file=sys.stderr)
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
    _recover_interrupted_restore(project)
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
    journal_path = checkpoint_root / _RESTORE_JOURNAL
    try:
        for relative in targets:
            destination = project / relative
            if destination.exists():
                _copy(destination, backup / relative)
        # Journal marks the destructive window: if the process dies between
        # delete and copy, the next save/latest/restore re-applies this attempt
        # instead of leaving a half-restored franken-tree. Written atomically
        # (tmp + os.replace) so a crash mid-write can't leave a torn journal.
        # buildId scopes the journal to its build so a stale one from another
        # build is quarantined, not replayed (see _recover_interrupted_restore).
        _atomic_write_json(journal_path, {
            "attempt": chosen["attempt"],
            "buildId": chosen.get("buildId"),
            "startedAt": datetime.now(timezone.utc).isoformat(),
        })
        try:
            _apply_targets(project, source_root, targets)
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
            # Rollback converged the tree — the journal must not re-apply.
            journal_path.unlink(missing_ok=True)
            raise
        journal_path.unlink(missing_ok=True)
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
