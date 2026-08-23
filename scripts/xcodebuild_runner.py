#!/usr/bin/env python3
"""Thin wrapper around `xcodebuild` for Autobot gates.

Two callable surfaces:

  scaffold_build(project_root, app_name) -> dict
    Run `xcodebuild build CODE_SIGNING_ALLOWED=NO` for the simulator using the
    project Phase 3 just produced. Returns a structured result that gate runners
    and run-summary generators can consume without parsing logs themselves.

  integration_build(project_root, app_name, *, result_bundle, attempt=1) -> dict
    Same shape as scaffold_build but for Phase 5. Writes an `.xcresult` bundle
    next to the build log so the artifact bundle (Loop 16) stays canonical.

Both surfaces are no-ops (status="skipped") when:
  - `xcodebuild` is not on PATH (CI / Linux machines running unit tests)
  - the .xcodeproj does not exist yet
  - `AUTOBOT_DISABLE_XCODEBUILD=1` is set in the environment

The return shape is intentionally JSON-serialisable so it can be stashed in
build-state.json or the run-summary report.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from artifact_provenance import (
    ArtifactVerificationError,
    MANIFEST_NAME,
    find_app_in_derived_data,
    write_app_manifest,
)
from state_store import state_file_for, try_load_state

DEFAULT_DESTINATION = "generic/platform=iOS Simulator"
DEFAULT_TIMEOUT = 600  # 10 minutes — scaffold builds are tiny but cold caches are slow.


def _build_id(project_root: Path) -> str:
    state = try_load_state(state_file_for(project_root)) or {}
    return state.get("buildId") or "unknown-build"


def _artifact_dir(project_root: Path, *, phase: int, attempt: int | None) -> Path:
    base = project_root / "artifacts" / _build_id(project_root) / f"phase-{phase}"
    if attempt is not None:
        base = base / f"attempt-{attempt}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _canonical_log(project_root: Path, *, phase: int, attempt: int | None, filename: str) -> Path:
    return _artifact_dir(project_root, phase=phase, attempt=attempt) / filename


def _canonical_attempt_dir(project_root: Path, *, phase: int, attempt: int) -> Path:
    return _artifact_dir(project_root, phase=phase, attempt=attempt)


def _xcodebuild_available() -> bool:
    if os.environ.get("AUTOBOT_DISABLE_XCODEBUILD") == "1":
        return False
    return shutil.which("xcodebuild") is not None


def _resolve_project(project_root: Path, app_name: str) -> Path | None:
    candidates = [
        project_root / f"{app_name}.xcodeproj",
        project_root / app_name / f"{app_name}.xcodeproj",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


_DIAGNOSTIC_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|warning|note):\s+(.+)$", re.MULTILINE)


def _parse_diagnostics(text: str, limit: int = 50) -> list[dict]:
    """Structured `file:line:col: severity: message` entries from xcodebuild output.

    The error signature below deliberately strips paths so the circuit breaker
    sees "the same error"; this keeps them so the build-fix loop can be pointed
    at the exact file and line without re-reading the log.
    """
    out, seen = [], set()
    for m in _DIAGNOSTIC_RE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue  # xcodebuild repeats diagnostics per target/arch
        seen.add(key)
        out.append({
            "file": m.group(1), "line": int(m.group(2)), "column": int(m.group(3)),
            "severity": m.group(4), "message": m.group(5).strip(),
        })
        if len(out) >= limit:
            break
    return out


def _normalize_error_signature(stderr: str) -> str:
    """Strip volatile noise (paths, line numbers, timestamps, hex addresses)
    so the same underlying error always hashes to the same signature.

    Used by the build-fix loop's `circuit_breaker.errorSignatureRepeat` check
    so a fix attempt that produces a different error keeps the loop alive but
    a fix attempt that yields the *same* error trips the breaker.
    """
    lines = []
    for raw in stderr.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Keep compiler error category, drop file paths and line:column.
        line = re.sub(r"^/[^:]+:\d+:\d+:\s*", "", line)
        line = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", line)
        line = re.sub(r"\b\d{4}-\d{2}-\d{2}T[\d:.+\-]+Z?", "TS", line)
        if re.match(r"^(note|warning):", line):
            continue
        lines.append(line)
    return "\n".join(lines[:25])  # cap so unrelated trailing noise can't move the hash


def _run_xcodebuild(
    *,
    project: Path,
    scheme: str,
    extra_args: list[str],
    log_path: Path,
    timeout: int,
    destination: str = DEFAULT_DESTINATION,
) -> tuple[int, str, str, float]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "xcodebuild",
        "-project", str(project),
        "-scheme", scheme,
        "-destination", destination,
        "-quiet",
        "CODE_SIGNING_ALLOWED=NO",
        "ONLY_ACTIVE_ARCH=YES",
        *extra_args,
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = time.monotonic() - started
        log_path.write_text(
            f"$ {' '.join(cmd)}\n\n=== STDOUT ===\n{proc.stdout}\n=== STDERR ===\n{proc.stderr}\n",
            encoding="utf-8",
        )
        return proc.returncode, proc.stdout, proc.stderr, duration
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        log_path.write_text(
            f"$ {' '.join(cmd)}\n\nTIMEOUT after {timeout}s\n",
            encoding="utf-8",
        )
        return 124, exc.stdout or "", f"timeout after {timeout}s", duration


def _build_result(
    *,
    phase: str,
    project: Path | None,
    rc: int,
    stdout: str,
    stderr: str,
    duration: float,
    log_path: Path,
    result_bundle: Path | None = None,
) -> dict:
    succeeded = rc == 0
    signature = _normalize_error_signature(stderr or stdout) if not succeeded else ""
    summary: dict = {
        "phase": phase,
        "status": "passed" if succeeded else "failed",
        "exitCode": rc,
        "durationSeconds": round(duration, 2),
        "logPath": str(log_path),
        "errorSignature": signature,
        "errorSignatureHash": _signature_hash(signature) if signature else "",
        "diagnostics": _parse_diagnostics(stderr + "\n" + stdout) if not succeeded else [],
        "project": str(project) if project else None,
    }
    if result_bundle is not None:
        summary["resultBundlePath"] = str(result_bundle)
    return summary


def _signature_hash(signature: str) -> str:
    import hashlib
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _skipped(phase: str, reason: str) -> dict:
    return {
        "phase": phase,
        "status": "skipped",
        "skipReason": reason,
        "exitCode": None,
        "durationSeconds": 0.0,
    }


def scaffold_build(project_root: Path, app_name: str) -> dict:
    """Phase 3 — verify the freshly-scaffolded project actually compiles."""
    if not _xcodebuild_available():
        return _skipped("3", "xcodebuild_unavailable")
    project = _resolve_project(project_root, app_name)
    if project is None:
        return _skipped("3", "xcodeproj_missing")

    log_path = _canonical_log(project_root, phase=3, attempt=None, filename="scaffold-build.log")
    rc, stdout, stderr, duration = _run_xcodebuild(
        project=project,
        scheme=app_name,
        extra_args=["build"],
        log_path=log_path,
        timeout=DEFAULT_TIMEOUT,
    )
    return _build_result(
        phase="3",
        project=project,
        rc=rc,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        log_path=log_path,
    )


def integration_build(
    project_root: Path,
    app_name: str,
    *,
    attempt: int = 1,
    test: bool = False,
    destination: str | None = None,
) -> dict:
    """Phase 5 — full integration build with `.xcresult` bundle captured.

    The `test` action REQUIRES a concrete simulator destination — `xcodebuild`
    refuses to test against the generic `platform=iOS Simulator` ("Tests must be
    run on a concrete device"). Callers running tests must pass
    `destination="id=<udid>"` (or "platform=iOS Simulator,name=...,OS=..."); the
    `build` action is fine with the generic default.
    """
    if not _xcodebuild_available():
        return _skipped("5", "xcodebuild_unavailable")
    project = _resolve_project(project_root, app_name)
    if project is None:
        return _skipped("5", "xcodeproj_missing")
    if test and not destination:
        return _skipped("5", "no_concrete_destination_for_test")

    attempt_root = _canonical_attempt_dir(project_root, phase=5, attempt=attempt)
    log_path = attempt_root / "xcodebuild.log"
    result_bundle = attempt_root / "Build.xcresult"
    build_cache = attempt_root.parent / "_DerivedData"
    derived_data = attempt_root / "DerivedData"
    manifest_path = attempt_root / MANIFEST_NAME
    # xcodebuild refuses to overwrite an existing -resultBundlePath; clear any
    # stale output from a prior run. Keep one build-scoped DerivedData cache for
    # incremental compilation, but remove the target app product before every
    # command and copy the newly produced bundle into attempt-local proof.
    shutil.rmtree(result_bundle, ignore_errors=True)
    shutil.rmtree(derived_data, ignore_errors=True)
    for stale_app in (build_cache / "Build" / "Products").glob(
        f"*-iphonesimulator/{app_name}.app"
    ):
        shutil.rmtree(stale_app, ignore_errors=True)
    manifest_path.unlink(missing_ok=True)
    extra: list[str] = [
        "-derivedDataPath", str(build_cache),
        "-resultBundlePath", str(result_bundle),
        "test" if test else "build",
    ]
    rc, stdout, stderr, duration = _run_xcodebuild(
        project=project,
        scheme=app_name,
        extra_args=extra,
        log_path=log_path,
        timeout=DEFAULT_TIMEOUT,
        destination=destination or DEFAULT_DESTINATION,
    )
    result = _build_result(
        phase="5",
        project=project,
        rc=rc,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        log_path=log_path,
        result_bundle=result_bundle,
    )
    result["derivedDataPath"] = str(derived_data)
    result["buildCachePath"] = str(build_cache)
    result["buildId"] = _build_id(project_root)
    if result["status"] != "passed":
        return result

    try:
        built_app = find_app_in_derived_data(build_cache, app_name)
        relative_app = built_app.relative_to(build_cache.resolve())
        app_path = derived_data / relative_app
        app_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(built_app, app_path, symlinks=True)
        manifest = write_app_manifest(
            app_path,
            manifest_path,
            build_id=result["buildId"],
            app_name=app_name,
            attempt=attempt,
            derived_data_path=derived_data,
        )
    except (ArtifactVerificationError, OSError) as exc:
        result["status"] = "failed"
        message = str(exc)
        result["artifactError"] = (
            "app_artifact_missing" if "app_artifact_missing" in message else message
        )
        return result

    result.update({
        "appPath": manifest["appPath"],
        "artifactManifestPath": str(manifest_path),
        "artifactDigest": manifest["artifactDigest"],
        "bundleId": manifest["bundleId"],
        "version": manifest["version"],
        "build": manifest["build"],
    })
    return result


# CLI surface so shell scripts (and gate runners that prefer subprocess) can
# call this without importing.
def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sc = sub.add_parser("scaffold-build")
    p_sc.add_argument("--project-dir", required=True)
    p_sc.add_argument("--app-name", required=True)
    p_in = sub.add_parser("integration-build")
    p_in.add_argument("--project-dir", required=True)
    p_in.add_argument("--app-name", required=True)
    p_in.add_argument("--attempt", type=int, default=1)
    p_in.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.cmd == "scaffold-build":
        result = scaffold_build(Path(args.project_dir).resolve(), args.app_name)
    else:
        result = integration_build(
            Path(args.project_dir).resolve(),
            args.app_name,
            attempt=args.attempt,
            test=args.test,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "passed":
        return 0
    if result["status"] == "skipped":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
