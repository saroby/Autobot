#!/bin/bash
# Validate and mutate build-state.json using the pipeline spec-backed runtime.
# Usage:
#   bash validate-state.sh schema
#   bash validate-state.sh transition --phase 4 --to in_progress
#   bash validate-state.sh init-state --build-id build-20260401-demo --app-name Demo --display-name "Demo"
#   bash validate-state.sh set-phase-status --phase 4 --to completed
#   bash validate-state.sh record-environment --xcodegen true --stitch false
#   bash validate-state.sh record-gate-result --gate '4->5' --status passed --check views_exist=true
#   bash validate-state.sh run-gate --gate '4->5' --app-name MyApp [--format json]
#   bash validate-state.sh verify-docs
#   bash validate-state.sh render-docs
#   bash validate-state.sh transition --phase 5 --to in_progress --allow-terminal-restart
set -euo pipefail

MODE=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
EXTRA_ARGS=()
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

if [[ $# -eq 0 ]]; then
  echo "Usage: validate-state.sh <schema|transition|init-state|set-phase-status|record-environment|record-gate-result|run-gate|verify-docs|render-docs> [options]" >&2
  exit 1
fi

MODE="$1"
shift
EXTRA_ARGS=("$@")

case "$MODE" in
  schema)
    exec python3 "$RUNTIME" validate-schema --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  transition)
    exec python3 "$RUNTIME" validate-transition --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  init-state)
    exec python3 "$RUNTIME" init-state --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  set-phase-status)
    exec python3 "$RUNTIME" set-phase-status --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  record-environment)
    exec python3 "$RUNTIME" record-environment --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  record-gate-result)
    exec python3 "$RUNTIME" record-gate-result --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  run-gate)
    exec python3 "${SCRIPT_DIR}/gate_runner.py" run-gate --project-dir "$PROJECT_DIR" "${EXTRA_ARGS[@]}"
    ;;
  list-checks)
    exec python3 "${SCRIPT_DIR}/gate_runner.py" list-checks "${EXTRA_ARGS[@]}"
    ;;
  verify-docs)
    exec python3 "${SCRIPT_DIR}/verify_spec_docs.py" "${EXTRA_ARGS[@]}"
    ;;
  render-docs)
    exec python3 "${SCRIPT_DIR}/render_pipeline_docs.py" --write
    ;;
  *)
    echo "Usage: validate-state.sh <schema|transition|init-state|set-phase-status|record-environment|record-gate-result|run-gate|verify-docs|render-docs> [options]" >&2
    exit 1
    ;;
esac
