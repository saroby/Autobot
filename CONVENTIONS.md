# Autobot Internal Conventions

Rules that the runtime and shell scripts follow consistently. New code added
to `scripts/` must obey these so that callers (humans, CI,
shell wrappers) can rely on a stable surface.

## Output prefix policy

Every line a runtime command emits to stdout/stderr starts with one of these
prefixes. `grep` on prefixes is the supported way to classify output.

| Prefix       | Meaning                                                                 | Exit code (typical) |
|--------------|-------------------------------------------------------------------------|---------------------|
| `OK:`        | Successful operation, normal completion                                 | 0                   |
| `WARN:`      | Non-fatal advisory; the operation still completes                       | 0                   |
| `INFO:`      | Diagnostic info that callers may safely ignore                          | 0                   |
| `PASS:`      | A check passed (gate / verifier / facade)                               | 0                   |
| `FAIL:`      | A check failed but the process still terminates cleanly                 | 1 or 2              |
| `REJECTED:`  | A request was refused by policy (transition, breaker, dependency)       | 1                   |
| `ERROR:`     | Validation or precondition failure surfaced to the user                 | 1                   |
| `FATAL:`     | Unrecoverable; the process is exiting via SystemExit                    | 1+                  |
| `VIOLATION:` | Sandbox detected an ownership violation (one line per offending path)   | 1                   |
| `SUMMARY:`   | Multi-line operation summary footer (sandbox)                           | n/a                 |

Subordinate sub-checks use one of `✓` (pass), `✗` (fail), `⊘` (skipped) —
those are *visual* markers and not intended for grepping.

### When to use which

- `OK:` is for the *normal end* of a successful command. It's not used for
  intermediate progress.
- `WARN:` is for advisories that should appear in operator logs but do not
  change the exit code (e.g., schema warnings about missing recommended
  fields).
- `REJECTED:` is for *policy* refusals (transition table, retry exhaustion,
  circuit breaker). These are user-fixable and the runtime explains how.
- `ERROR:` and `FATAL:` differ only in severity: `ERROR:` lets the operator
  retry; `FATAL:` indicates the runtime cannot proceed (corrupt spec,
  missing state file, schema violation that would corrupt state).

## Atomicity rules

- **Single writer for `build-state.json`**: every mutation goes through
  `state_store.mutate_state_with_validation`. No script bypasses it.
- **Pre-validate before mutate**: any command that runs a side-effect
  (gate execution, subprocess) must validate the resulting transition
  *before* writing state. If the post-side-effect state would violate a
  transition or schema, the side effect's evidence must not land in state.
  See `phase_advance.advance_phase` for the canonical pattern.
- **Atomic file writes**: `state_store.write_json` writes to `<name>.tmp` and
  renames. Snapshot files in `sandbox_runner` and `snapshot_runner` follow
  the same pattern. Never overwrite an output file in place.

## Module dependency rules

```
spec_loader   ← state_store   ← transitions
                ↑              ← event_log
                ↑                  ↑
                gate_persistence ──┘
                ↑
                phase_advance, cli
                ↑
                runtime (facade)
```

- `spec_loader` depends only on stdlib.
- `state_store` may depend on `spec_loader`. **Must not** import `event_log`
  — that would create a cycle when a future feature wants to log inside a
  mutation. Pass a callback through the caller instead.
- `event_log` may depend on `spec_loader` + `state_store`.
- `transitions` may depend on `state_store` (and via that, `spec_loader`).
- `gate_persistence` may depend on `state_store` + `event_log` + `gate_runner`
  (`gate_runner` is stdlib-only).
- `phase_advance` and `cli` may depend on everything above.
- `runtime` is a facade; it imports nothing else *into* the codebase, only
  re-exports.

## Spec is SSOT

The following live in `spec/pipeline.json` and **only** there:

- Phase definitions (`phases.<id>`)
- Gate descriptors (`gates.<id>.checks`)
- Status transition rules (`transitions.default`, `transitions.overrides`)
- Retry policy (`phases.<id>.maxRetry`)
- Circuit breaker (`policies.circuitBreaker`)
- Allowed flags (`policies.allowedFlags`)
- Log event taxonomy (`logEvents` + per-event `detailSchema`)
- File ownership (`fileOwnership.agents.<>.writes`)
- always-run phase marker (`phases.<id>.alwaysRun`)

Never hard-code these in scripts. If you need a new value, extend the spec
and read it from there. Procedural gate hooks and runtime helpers must
derive paths from spec rather than re-stating them.

## Adding a new public symbol

1. Define the symbol in its source module.
2. Add the name to that module's `__all__`.
3. `runtime.py` re-exports it automatically (driven by `__all__`).
4. `verify_spec_docs.check_facade_exports()` automatically asserts the
   facade ↔ source identity contract.

No third place to update — the facade's contract is implicit.

## Adding a new log event

1. Declare it in `spec.logEvents.<event>`:
   - `required`: list of metadata keys that must be present (`phase`,
     `agent`, or `detail`).
   - `optional`: keys that may be present.
   - `detailSchema` (optional): a tiny JSON-Schema-like descriptor for the
     `detail` payload. See `event_log._check_detail_schema` for the
     supported subset (type/required/properties).
2. `runtime.py append-log` now accepts the event. Calls with unknown
   events or missing required fields fail-loud at the wrapper layer.
3. Add a regression test under `tests/test_log_validation.py` if the event
   is decision-relevant (gate input or retro audit).
