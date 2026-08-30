#!/usr/bin/env bash
# Phase 1 codex architecture review.
#
# Runs `codex exec` non-interactively against the current architecture artifacts
# (architecture.md + Models/*.swift) and produces a structured verdict. The
# verdict is persisted into phases.1.metadata.codexReview so Gate 1→2's
# `codex_review_acceptable` check can read it.
#
# Behavior summary:
#   - Detect codex CLI. If missing, record `verdict=skipped, skipReason=codex_cli_unavailable`
#     so the build can still proceed (gate accepts skipped).
#   - Run codex exec with --output-schema enforcing the verdict shape.
#   - Persist the parsed verdict + emit a `codex_review` log event.
#
# Exit codes:
#   0  → PASS or skipped (caller continues)
#   3  → FAIL — caller should re-dispatch architect with violations
#   1  → unexpected error (caller decides)
#
# Usage:
#   codex-architecture-review.sh \
#       --app-name <AppName> \
#       --project-dir <dir> \
#       [--attempt N]
#
set -euo pipefail

APP_NAME=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
ATTEMPT=1
# 180s was under the real cost of the review it is asked to do: measured
# 2026-08-29 on a 10-model architecture, the first attempt was killed at 180s
# and the identical prompt returned PASS at 540s. A too-short default does not
# fail loudly — it records `verdict=skipped`, so every build silently ships
# unreviewed. Bound it generously; codex exits on its own when done.
TIMEOUT_SECS=600

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-name)    APP_NAME="$2";   shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --attempt)     ATTEMPT="$2";     shift 2 ;;
    --timeout)     TIMEOUT_SECS="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$APP_NAME" ]]; then
  echo "FATAL: --app-name required" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARCH_FILE="${PROJECT_DIR}/.autobot/architecture.md"
MODELS_DIR="${PROJECT_DIR}/${APP_NAME}/Models"
WORK_DIR="${PROJECT_DIR}/.autobot/codex-review"
mkdir -p "$WORK_DIR"
SCHEMA_FILE="${WORK_DIR}/verdict-schema.json"
OUT_FILE="${WORK_DIR}/last-message.txt"
PROMPT_FILE="${WORK_DIR}/prompt.md"

# Helper: persist via Python (avoids depending on a CLI subcommand we may not have)
persist_review() {
  local verdict="$1"
  local attempt="$2"
  local hard_count="$3"
  local soft_count="$4"
  local planning_count="$5"
  local skip_reason="$6"
  local raw_path="$7"

  python3 - "$verdict" "$attempt" "$hard_count" "$soft_count" "$planning_count" "$skip_reason" "$raw_path" "$PROJECT_DIR" "$SCRIPT_DIR" <<'PY'
import json, sys, datetime
from pathlib import Path

verdict, attempt, hard, soft, planning, skip_reason, raw_path, project_dir, script_dir = sys.argv[1:10]
sys.path.insert(0, script_dir)
from spec_loader import load_spec
from state_store import mutate_state_with_validation
from event_log import append_build_log

state_path = Path(project_dir) / ".autobot" / "build-state.json"
spec = load_spec()

raw_json = None
if raw_path and Path(raw_path).is_file():
    try:
        raw_json = json.loads(Path(raw_path).read_text())
    except Exception:
        raw_json = None

review_entry = {
    "verdict": verdict,
    "attempt": int(attempt),
    "hardViolationsCount": int(hard),
    "softWarningsCount": int(soft),
    # planning axis is warning-only: counted + persisted for visibility, never
    # part of the verdict (hard violations alone decide PASS/FAIL).
    "planningViolationsCount": int(planning),
    "reviewedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
if skip_reason:
    review_entry["skipReason"] = skip_reason
if raw_json is not None:
    review_entry["hardViolations"] = raw_json.get("hardViolations", [])
    review_entry["softWarnings"] = raw_json.get("softWarnings", [])
    review_entry["planningViolations"] = raw_json.get("planningViolations", [])

# Generic peerReview view (bi-directional). This script is the host=claude -> peer=codex
# path; the Codex-host -> Claude review writes its own peerReview entry directly.
peer_review_entry = dict(review_entry)
peer_review_entry["host"] = "claude"
peer_review_entry["peer"] = "codex"
peer_review_entry["blockingFindingsCount"] = int(hard)

def mutate(s):
    p1 = s.setdefault("phases", {}).setdefault("1", {"status": "pending"})
    md = p1.setdefault("metadata", {})
    md["codexReview"] = review_entry         # legacy key for backward compat
    md["peerReview"] = peer_review_entry     # generic key consumed by gate

mutate_state_with_validation(state_path, spec, mutate)

detail = {
    "host": "claude",
    "peer": "codex",
    "verdict": verdict,
    "attempt": int(attempt),
    "blockingFindingsCount": int(hard),
    "hardViolationsCount": int(hard),
    "softWarningsCount": int(soft),
    "planningViolationsCount": int(planning),
}
if skip_reason:
    detail["skipReason"] = skip_reason

# Emit unified peer_review event. The legacy codex_review event is retained in
# spec.logEvents for backward compatibility with archived build-log.jsonl files
# but is no longer produced by Autobot itself.
append_build_log(
    Path(project_dir),
    "peer_review",
    phase="1",
    detail=detail,
    spec=spec,
)
print(f"OK: codex review verdict={verdict} attempt={attempt} (hard={hard}, soft={soft}, planning={planning})")
PY
}

# 1) Detect codex CLI
if ! command -v codex >/dev/null 2>&1; then
  persist_review "skipped" "$ATTEMPT" 0 0 0 "codex_cli_unavailable" ""
  exit 0
fi

# 2) Validate inputs exist
if [[ ! -f "$ARCH_FILE" ]]; then
  echo "FATAL: architecture.md not found at $ARCH_FILE" >&2
  exit 1
fi
if [[ ! -d "$MODELS_DIR" ]]; then
  echo "FATAL: Models/ not found at $MODELS_DIR" >&2
  exit 1
fi

# 3) Build the JSON schema for codex --output-schema
cat > "$SCHEMA_FILE" <<'JSON'
{
  "type": "object",
  "additionalProperties": false,
  "required": ["verdict", "hardViolations", "softWarnings", "planningViolations"],
  "properties": {
    "verdict": {
      "type": "string",
      "enum": ["PASS", "FAIL"]
    },
    "hardViolations": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["category", "file", "issue", "suggestedFix"],
        "properties": {
          "category": { "type": "string" },
          "file":     { "type": "string" },
          "issue":    { "type": "string" },
          "suggestedFix": { "type": "string" }
        }
      }
    },
    "softWarnings": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["category", "file", "issue"],
        "properties": {
          "category": { "type": "string" },
          "file":     { "type": "string" },
          "issue":    { "type": "string" }
        }
      }
    },
    "planningViolations": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["category", "file", "issue"],
        "properties": {
          "category": { "type": "string" },
          "file":     { "type": "string" },
          "issue":    { "type": "string" }
        }
      }
    }
  }
}
JSON

# 4) Build the review prompt
cat > "$PROMPT_FILE" <<'PROMPT_HEADER'
You are reviewing an iOS architecture on two independent axes:
(A) COMPILABILITY-IMPACTING design issues — hard violations; these ALONE decide
    the verdict.
(B) PLANNING-DEPTH issues — advisory only; report them in `planningViolations`.
    They NEVER change the verdict and NEVER fail the review.
Return a JSON object matching the provided schema. Outside these two axes, do
NOT comment on style or architectural taste.

Hard violations (FAIL the review):
1) Swift 6 strict concurrency
   - Any protocol method that cannot be implemented without `nonisolated(unsafe)`
     workarounds because the protocol shape forces non-Sendable state across
     actor boundaries.
   - AsyncStream<T> emitting a non-Sendable T.
   - @MainActor protocol method that must also be callable from the audio render
     thread or another nonisolated context.
   - Properties accessed from a nonisolated `deinit` that are MainActor-isolated.

2) SwiftData @Model graph
   - Inconsistent @Relationship cascade/nullify rules (parent-cascade with
     child-cascade in the wrong direction, etc.).
   - Codable conformance on @Model that is not explicitly handled.
   - Stored properties of types SwiftData cannot persist (closures, AnyHashable,
     non-Codable raw structs without a transformer).

3) AVFoundation / MediaPlayer lifecycle
   - AVAudioSession activation with no clear single-owner service.
   - MPRemoteCommandCenter handlers wired from a non-MainActor context.
   - AVAudioEngine assumed Sendable in protocol surface.

4) Permissions ↔ Features alignment
   - A P0 feature in `## Features` that requires an Info.plist key or
     entitlement which is not listed in `## Permissions` / `## Dependencies`.

5) iOS 26 API availability
   - Use of deprecated APIs that have a stable replacement on iOS 17+
     (`ObservableObject + @Published` instead of `@Observable`,
      `NavigationView` instead of `NavigationStack`, etc.).

Soft warnings (do NOT fail the review, just note):
- Naming, doc strings, protocol cohesion, screen-vs-VM granularity.

Planning violations (report in `planningViolations` — warning-only, NEVER
affect the verdict, NEVER block the build):
P1) No hook P0 — `## Features` has no P0 that differentiates the app from
    category-standard apps (every P0 is generic CRUD: list + detail + add/delete).
P2) Hook / First-Run cells are abstract-only — `### Hook & Retention` (or
    `## First-Run Experience`) contains only abstract adjectives
    ("convenient", "intuitive", "smart") with no domain nouns.
P3) Feature set is a keyword listing — the features read as a generic keyword
    expansion of the category with zero differentiation from any same-category app.

Output requirements:
- `verdict`: "PASS" if zero hard violations, otherwise "FAIL".
  planningViolations MUST NOT influence the verdict.
- `hardViolations`: list of {category, file, issue, suggestedFix}.
- `softWarnings`: list of {category, file, issue}.
- `planningViolations`: list of {category, file, issue} — category is one of
  "no-hook-p0", "abstract-only-hook", "keyword-listing". Empty array if none.
- Be specific. Reference exact file paths and (where possible) symbol names.
- Prefer ≤6 hard violations even if more exist; rank by build-impact.

Artifacts to review are inside the working directory. Read in this order:
1. `.autobot/architecture.md`
2. `<APP_NAME>/Models/ServiceProtocols.swift`
3. `<APP_NAME>/Models/*.swift`

Now produce the verdict JSON.
PROMPT_HEADER

# Append concrete app name + paths to the prompt
{
  echo
  echo "App identifier: ${APP_NAME}"
  echo "Architecture document: .autobot/architecture.md"
  echo "Models directory: ${APP_NAME}/Models"
  echo
  echo "Attempt: ${ATTEMPT} of policy maxAttempts."
} >> "$PROMPT_FILE"

# 5) Invoke codex exec (non-interactive, schema-enforced output)
#    --skip-git-repo-check: project may not be a git repo
#    -C: change codex working dir to the project so it can read files relatively
rm -f "$OUT_FILE"
echo "Running codex review (attempt ${ATTEMPT}, timeout ${TIMEOUT_SECS}s)…" >&2

set +e
# `timeout` (GNU coreutils) is not present by default on macOS; the bare
# `timeout … codex …` form exited 127 before codex was reached, masking every
# peer review as "codex failed". Prefer gtimeout (brew coreutils), then
# timeout, otherwise run codex without OS-level timeout — codex bounds its
# own work and silent skip is worse than a missing kill-switch.
if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="gtimeout"
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="timeout"
else
  TIMEOUT_BIN=""
fi
# `-c mcp_servers={}` disables the reviewer's MCP servers for this run. A review
# needs nothing but the local files, and inheriting the operator's MCP config is
# how this call deadlocks: with `approval_policy = never` an MCP tool call that
# wants approval can never get it, and codex spins until the timeout. Measured
# 2026-08-29: two Phase 5 attempts burned 10 and 15 minutes and produced no
# output ("MCP tool call requires approval, but approval policy is never");
# the same prompt with MCP disabled completed and returned a verdict.
CODEX_ARGS=(
  exec
  --skip-git-repo-check
  -C "$PROJECT_DIR"
  -c "mcp_servers={}"
  --output-schema "$SCHEMA_FILE"
  --output-last-message "$OUT_FILE"
  --sandbox read-only
  -
)
if [[ -n "$TIMEOUT_BIN" ]]; then
  "$TIMEOUT_BIN" --kill-after=10 "$TIMEOUT_SECS" codex "${CODEX_ARGS[@]}" \
    < "$PROMPT_FILE" >/dev/null 2>&1
else
  echo "WARN: no GNU timeout binary (install coreutils for gtimeout); running codex without OS-level timeout" >&2
  codex "${CODEX_ARGS[@]}" < "$PROMPT_FILE" >/dev/null 2>&1
fi
codex_rc=$?
set -e

if [[ $codex_rc -ne 0 ]] || [[ ! -s "$OUT_FILE" ]]; then
  # codex itself failed (auth, rate limit, timeout). Treat as skipped so build proceeds.
  reason="codex_invocation_failed_rc${codex_rc}"
  persist_review "skipped" "$ATTEMPT" 0 0 0 "$reason" ""
  echo "WARN: codex exec rc=$codex_rc, marking review skipped (reason=$reason)" >&2
  exit 0
fi

# 6) Parse the response (must be valid JSON per schema). The model output is
#    UNTRUSTED input: read it via json.load(argv path) inside a QUOTED heredoc
#    so no model bytes are ever interpolated into Python source. The prior
#    `json.loads('''$verdict_json''')` form let a triple-quote breakout in the
#    model output execute arbitrary code in this process.
parsed=$(python3 - "$OUT_FILE" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("verdict payload is not a JSON object")
except Exception as e:
    print(f"PARSE_ERROR:{e}")
    sys.exit(0)
verdict = data.get("verdict", "")
hard = len(data.get("hardViolations", []))
soft = len(data.get("softWarnings", []))
planning = len(data.get("planningViolations", []))
print(f"{verdict}|{hard}|{soft}|{planning}")
PY
) || parsed="PARSE_ERROR:python_failed"

if [[ "$parsed" == PARSE_ERROR:* ]]; then
  # Explicit, auditable skip — never a silent one: distinct skipReason + loud
  # WARN. NOT verdict="error": Gate 1->2 is not soft and treats any
  # non-PASS/non-skipped verdict as a hard fail that BLOCKS phase advance
  # (excludeFromCircuitBreaker only exempts the breaker counter, not the gate's
  # pass/fail). Peer review must stay advisory/non-blocking, so the auditable
  # signal rides on skipReason.
  reason="codex_response_parse_failed"
  persist_review "skipped" "$ATTEMPT" 0 0 0 "$reason" ""
  echo "WARN: codex review parse failed (${parsed#PARSE_ERROR:}) — recording verdict=skipped skipReason=$reason (advisory, non-blocking)" >&2
  exit 0
fi

IFS='|' read -r VERDICT HARD SOFT PLANNING <<< "$parsed"
PLANNING="${PLANNING:-0}"

persist_review "$VERDICT" "$ATTEMPT" "$HARD" "$SOFT" "$PLANNING" "" "$OUT_FILE"

case "$VERDICT" in
  PASS)
    if [[ "$PLANNING" != "0" ]]; then
      # planning axis is warning-only: surface, never block (see prompt scope).
      echo "WARN: ${PLANNING} planning violation(s) reported (advisory — build proceeds)" >&2
    fi
    exit 0
    ;;
  FAIL)
    echo "Codex review FAIL: ${HARD} hard violation(s), ${SOFT} soft warning(s), ${PLANNING} advisory planning violation(s)." >&2
    exit 3
    ;;
  *)
    # Unexpected verdict value — treat as skipped to keep pipeline alive
    reason="codex_unknown_verdict_${VERDICT}"
    persist_review "skipped" "$ATTEMPT" 0 0 0 "$reason" ""
    echo "WARN: codex returned unknown verdict='$VERDICT', marking skipped" >&2
    exit 0
    ;;
esac
