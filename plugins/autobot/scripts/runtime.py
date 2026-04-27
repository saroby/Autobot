#!/usr/bin/env python3
"""Autobot pipeline runtime — facade.

Implementation lives in focused modules:
  - spec_loader.py      : pipeline.json load + structural validation
  - state_store.py      : build-state.json I/O + schema-validated mutation
  - event_log.py        : build-log.jsonl event validation + append
  - transitions.py      : phase status transitions, retries, circuit breaker
  - gate_persistence.py : gate-run persistence + always-run scheduling
  - phase_advance.py    : advance-phase atomic composition
  - cli.py              : argparse + every command handler + main()

This file exists for two reasons:
  1. Backwards-compatible imports — sandbox_runner.py / snapshot_runner.py and
     external tooling can keep doing ``from runtime import X``.
  2. CLI entrypoint — the shell wrappers (pipeline.sh, build-log.sh,
     validate-state.sh) all invoke ``python3 runtime.py <subcommand>``.

The re-export surface is driven by each source module's ``__all__`` instead of
a hard-coded list, so adding a new public symbol in one place propagates here
automatically. ``verify_spec_docs.py:check_facade_exports`` then asserts the
two views agree.
"""

from __future__ import annotations

import sys

import event_log as _event_log
import gate_persistence as _gate_persistence
import spec_loader as _spec_loader
import state_store as _state_store
import transitions as _transitions
from cli import main


_FACADE_MODULES = (_spec_loader, _state_store, _event_log, _transitions, _gate_persistence)


def _populate_facade() -> list[str]:
    exported: list[str] = []
    for module in _FACADE_MODULES:
        for name in getattr(module, "__all__", ()):
            globals()[name] = getattr(module, name)
            exported.append(name)
    return exported


__all__ = _populate_facade() + ["main"]


if __name__ == "__main__":
    sys.exit(main())
