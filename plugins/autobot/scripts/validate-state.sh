#!/bin/bash
# Diagnostic helper for build-state.json. Read-only / dry-run only.
# Use pipeline.sh for any operation that mutates state, runs gates, or
# advances phases.
#
# Usage:
#   bash validate-state.sh schema
#   bash validate-state.sh transition --phase 4 --to in_progress
#   bash validate-state.sh transition --phase 5 --to in_progress --allow-terminal-restart
#   bash validate-state.sh list-checks [--gate 4->5]
#   bash validate-state.sh verify-docs
#   bash validate-state.sh render-docs
set -euo pipefail

MODE=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
EXTRA_ARGS=()
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

USAGE="Usage: validate-state.sh <schema|transition|list-checks|verify-docs|render-docs> [options]"

if [[ $# -eq 0 ]]; then
  echo "$USAGE" >&2
  exit 1
fi

MODE="$1"
shift
EXTRA_ARGS=("$@")

case "$MODE" in
  schema)
    exec python3 "$RUNTIME" validate-schema --project-dir "$PROJECT_DIR" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  transition)
    exec python3 "$RUNTIME" validate-transition --project-dir "$PROJECT_DIR" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  list-checks)
    exec python3 "${SCRIPT_DIR}/gate_runner.py" list-checks ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  verify-docs)
    exec python3 "${SCRIPT_DIR}/verify_spec_docs.py" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
    ;;
  render-docs)
    exec python3 "${SCRIPT_DIR}/render_pipeline_docs.py" --write
    ;;
  init-state|set-phase-status|record-environment|record-gate-result|run-gate)
    cat >&2 <<EOF
ERROR: validate-state.sh '${MODE}' was removed.

  → Use pipeline.sh instead. validate-state.sh is now read-only/diagnostic.
    init-state           -> pipeline.sh init-build
    set-phase-status     -> pipeline.sh start-phase | advance-phase | fail-phase
    record-environment   -> pipeline.sh record-environment
    record-gate-result   -> pipeline.sh run-gate (records automatically)
    run-gate             -> pipeline.sh run-gate (single canonical path)
EOF
    exit 2
    ;;
  *)
    echo "$USAGE" >&2
    exit 1
    ;;
esac
