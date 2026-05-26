#!/usr/bin/env python3
"""Normalize compiler/build error output into a stable signature, track its
occurrence count per phase, and decide whether the circuit breaker should trip.

The policy is `policies.circuitBreaker.errorSignatureRepeat` in spec/pipeline.json:

    maxRepeats: 2          # same signature 2 times → trip
    scope: phase           # count within the active phase, not across the build
    normalize:
      stripPaths: true
      stripLineNumbers: true
      stripTimestamps: true
      stripHexAddresses: true
      preserveErrorCode: true
      preserveErrorCategory: true

The point: a fix attempt that produces a *different* error keeps the
build-fix loop alive (forward progress), but a fix attempt that produces the
*same* error is making the model spin its wheels — and that is the single
strongest signal that we should snapshot-restore and hand off.

Public API
----------
normalize(text) -> (signature, hash)
record(state, phase, signature) -> (trip, occurrences, hash)
check(state, phase, signature) -> (trip, occurrences, hash)

CLI mirrors the same shape via subcommands so quality-engineer / build-fix
scripts can call this without importing Python.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from spec_loader import load_spec
from state_store import load_state, mutate_state_with_validation, state_file_from_args


__all__ = ["normalize", "record", "check"]


_PATH_RE = re.compile(r"^/[^\s:]+:")
_LINECOL_RE = re.compile(r":\d+:\d+:\s*")
_LEADING_LINECOL_RE = re.compile(r"^\d+:\d+:\s*")  # what's left after path strip
_HEX_RE = re.compile(r"0x[0-9a-fA-F]{4,}")
_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.+\-]+Z?")
_DERIVED_RE = re.compile(r"/DerivedData/[A-Za-z0-9_]+(?:-[A-Za-z0-9]+)*/")
_NOISE_PREFIXES = ("note:", "warning:", "ld:")


def normalize(text: str, *, options: dict | None = None) -> tuple[str, str]:
    """Return (canonical_signature, sha256_short_hash) for a raw error blob.

    Options come from spec.policies.circuitBreaker.errorSignatureRepeat.normalize
    when called via record/check; defaults below match that schema.
    """
    opts = {
        "stripPaths": True,
        "stripLineNumbers": True,
        "stripTimestamps": True,
        "stripHexAddresses": True,
        "preserveErrorCode": True,
        "preserveErrorCategory": True,
    }
    if options:
        opts.update(options)

    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if any(lower.startswith(prefix) for prefix in _NOISE_PREFIXES):
            continue
        if opts.get("stripPaths"):
            line = _PATH_RE.sub("", line)
            line = _DERIVED_RE.sub("/DerivedData/_/", line)
        if opts.get("stripLineNumbers"):
            line = _LINECOL_RE.sub(":", line)
            # After path strip, lines often start with bare "42:5: error: ..." —
            # collapse that prefix too so two errors at different lines share a hash.
            line = _LEADING_LINECOL_RE.sub("", line)
        if opts.get("stripTimestamps"):
            line = _TS_RE.sub("TS", line)
        if opts.get("stripHexAddresses"):
            line = _HEX_RE.sub("0xADDR", line)
        out.append(line)
        if len(out) >= 25:  # cap so unrelated trailing noise can't move the hash
            break

    canonical = "\n".join(out)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return canonical, digest


def _policy(spec: dict | None = None) -> dict:
    spec = spec or load_spec()
    return ((spec.get("policies") or {}).get("circuitBreaker") or {}).get("errorSignatureRepeat") or {}


def _phase_block(state: dict, phase: str) -> dict:
    phases = state.setdefault("phases", {})
    block = phases.setdefault(str(phase), {})
    return block


def check(state: dict, phase: str, signature: str, *, spec: dict | None = None) -> tuple[bool, int, str]:
    canonical, digest = normalize(signature)
    policy = _policy(spec)
    if not policy.get("enabled", False):
        return False, 0, digest
    block = _phase_block(state, phase)
    history = block.get("errorSignatureHistory") or []
    occurrences = sum(1 for entry in history if isinstance(entry, dict) and entry.get("hash") == digest)
    trip = occurrences >= int(policy.get("maxRepeats", 2)) - 1
    # `check` is "would the *next* occurrence trip?" — so we compare against
    # (maxRepeats - 1). `record` does the actual increment-then-evaluate.
    return trip, occurrences, digest


def record(state: dict, phase: str, signature: str, *, spec: dict | None = None) -> tuple[bool, int, str]:
    """Append the signature to phases.<N>.errorSignatureHistory and return
    (trip, occurrences_after_this_one, hash)."""
    canonical, digest = normalize(signature)
    block = _phase_block(state, phase)
    history = block.setdefault("errorSignatureHistory", [])
    history.append({"hash": digest, "preview": canonical[:200]})
    occurrences = sum(1 for entry in history if isinstance(entry, dict) and entry.get("hash") == digest)
    policy = _policy(spec)
    if not policy.get("enabled", False):
        return False, occurrences, digest
    trip = occurrences >= int(policy.get("maxRepeats", 2))
    if trip:
        block["circuitBreaker"] = {
            "tripped": True,
            "reason": "error_signature_repeat",
            "signature": digest,
            "repeats": occurrences,
        }
    return trip, occurrences, digest


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_result(trip: bool, occurrences: int, digest: str, *, recorded: bool) -> None:
    payload = {
        "tripped": trip,
        "occurrences": occurrences,
        "hash": digest,
        "recorded": recorded,
    }
    print(json.dumps(payload, ensure_ascii=False))


def _read_input(args) -> str:
    if args.signature is not None:
        return args.signature
    if args.stderr_file:
        return Path(args.stderr_file).read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("check", "record", "normalize"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir", default=".")
        p.add_argument("--phase", default="5")
        group = p.add_mutually_exclusive_group()
        group.add_argument("--signature")
        group.add_argument("--stderr-file")
    args = parser.parse_args()

    if args.cmd == "normalize":
        canonical, digest = normalize(_read_input(args))
        print(json.dumps({"signature": canonical, "hash": digest}, ensure_ascii=False))
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    state_args = argparse.Namespace(project_dir=args.project_dir, state_file=None)
    state_path = state_file_from_args(state_args)
    state = load_state(state_path)

    if args.cmd == "check":
        trip, occ, digest = check(state, args.phase, _read_input(args))
        _print_result(trip, occ, digest, recorded=False)
        return 2 if trip else 0

    # record — write back through the validated mutator so schema stays clean.
    spec = load_spec()
    raw_signature = _read_input(args)
    captured: dict = {}

    def _mutator(current: dict) -> None:
        trip, occ, digest = record(current, args.phase, raw_signature, spec=spec)
        captured["trip"] = trip
        captured["occ"] = occ
        captured["digest"] = digest

    mutate_state_with_validation(state_path, spec, _mutator)
    _print_result(captured["trip"], captured["occ"], captured["digest"], recorded=True)
    return 2 if captured["trip"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
