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
TIMEOUT_SECS=180

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

record_review() {
  # Persist phases.1.metadata.codexReview via runtime CLI.
  # Args: 1=JSON object string for codexReview
  local payload="$1"
  bash "${SCRIPT_DIR}/pipeline.sh" set-phase-status \
      --phase 1 --to in_progress --metadata "codexReview=${payload}" \
      2>/dev/null || \
  python3 - "$payload" <<'PY'
import json, sys
sys.path.insert(0, "$(dirname "$0")")
PY
}

# Helper: persist via Python (avoids depending on a CLI subcommand we may not have)
persist_review() {
  local verdict="$1"
  local attempt="$2"
  local hard_count="$3"
  local soft_count="$4"
  local skip_reason="$5"
  local raw_path="$6"

  python3 - "$verdict" "$attempt" "$hard_count" "$soft_count" "$skip_reason" "$raw_path" "$PROJECT_DIR" "$SCRIPT_DIR" <<'PY'
import json, sys, datetime
from pathlib import Path

verdict, attempt, hard, soft, skip_reason, raw_path, project_dir, script_dir = sys.argv[1:9]
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
    "reviewedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
if skip_reason:
    review_entry["skipReason"] = skip_reason
if raw_json is not None:
    review_entry["hardViolations"] = raw_json.get("hardViolations", [])
    review_entry["softWarnings"] = raw_json.get("softWarnings", [])

def mutate(s):
    p1 = s.setdefault("phases", {}).setdefault("1", {"status": "pending"})
    md = p1.setdefault("metadata", {})
    md["codexReview"] = review_entry

mutate_state_with_validation(state_path, spec, mutate)

detail = {
    "verdict": verdict,
    "attempt": int(attempt),
    "hardViolationsCount": int(hard),
    "softWarningsCount": int(soft),
}
if skip_reason:
    detail["skipReason"] = skip_reason

append_build_log(
    Path(project_dir),
    "codex_review",
    phase="1",
    detail=detail,
    spec=spec,
)
print(f"OK: codex review verdict={verdict} attempt={attempt} (hard={hard}, soft={soft})")
PY
}

# 1) Detect codex CLI
if ! command -v codex >/dev/null 2>&1; then
  persist_review "skipped" "$ATTEMPT" 0 0 "codex_cli_unavailable" ""
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
  "required": ["verdict", "hardViolations", "softWarnings"],
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
    }
  }
}
JSON

# 4) Build the review prompt
cat > "$PROMPT_FILE" <<'PROMPT_HEADER'
You are reviewing an iOS architecture for COMPILABILITY-IMPACTING design issues only.
Return a JSON object matching the provided schema. Do NOT comment on style or
architectural taste.

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

Output requirements:
- `verdict`: "PASS" if zero hard violations, otherwise "FAIL".
- `hardViolations`: list of {category, file, issue, suggestedFix}.
- `softWarnings`: list of {category, file, issue}.
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
timeout --kill-after=10 "$TIMEOUT_SECS" codex exec \
  --skip-git-repo-check \
  -C "$PROJECT_DIR" \
  --output-schema "$SCHEMA_FILE" \
  --output-last-message "$OUT_FILE" \
  --sandbox read-only \
  - < "$PROMPT_FILE" >/dev/null 2>&1
codex_rc=$?
set -e

if [[ $codex_rc -ne 0 ]] || [[ ! -s "$OUT_FILE" ]]; then
  # codex itself failed (auth, rate limit, timeout). Treat as skipped so build proceeds.
  reason="codex_invocation_failed_rc${codex_rc}"
  persist_review "skipped" "$ATTEMPT" 0 0 "$reason" ""
  echo "WARN: codex exec rc=$codex_rc, marking review skipped (reason=$reason)" >&2
  exit 0
fi

# 6) Parse the response (must be valid JSON per schema)
verdict_json="$(cat "$OUT_FILE")"
parsed=$(python3 - <<PY
import json, sys
try:
    data = json.loads('''$verdict_json''')
except Exception as e:
    print(f"PARSE_ERROR:{e}")
    sys.exit(0)
verdict = data.get("verdict", "")
hard = len(data.get("hardViolations", []))
soft = len(data.get("softWarnings", []))
print(f"{verdict}|{hard}|{soft}")
PY
) || parsed="PARSE_ERROR:python_failed"

if [[ "$parsed" == PARSE_ERROR:* ]]; then
  reason="codex_response_parse_failed"
  persist_review "skipped" "$ATTEMPT" 0 0 "$reason" ""
  echo "WARN: $parsed — marking review skipped" >&2
  exit 0
fi

VERDICT="${parsed%%|*}"
rest="${parsed#*|}"
HARD="${rest%%|*}"
SOFT="${rest##*|}"

persist_review "$VERDICT" "$ATTEMPT" "$HARD" "$SOFT" "" "$OUT_FILE"

case "$VERDICT" in
  PASS)
    exit 0
    ;;
  FAIL)
    echo "Codex review FAIL: ${HARD} hard violation(s), ${SOFT} soft warning(s)." >&2
    exit 3
    ;;
  *)
    # Unexpected verdict value — treat as skipped to keep pipeline alive
    reason="codex_unknown_verdict_${VERDICT}"
    persist_review "skipped" "$ATTEMPT" 0 0 "$reason" ""
    echo "WARN: codex returned unknown verdict='$VERDICT', marking skipped" >&2
    exit 0
    ;;
esac
