#!/bin/bash
# Thin entrypoint for the runtime-backed pipeline engine.
# Usage:
#   bash pipeline.sh schema
#   bash pipeline.sh init-build --build-id build-20260401-demo --app-name Demo --display-name "Demo"
#   bash pipeline.sh start-phase --phase 1 --detail "Architecture + Contracts"
#   bash pipeline.sh advance-phase --phase 1            # run gate, mark complete on pass
#   bash pipeline.sh advance-phase --phase 2 --status fallback --detail "Stitch unavailable"
#   bash pipeline.sh fail-phase --phase 5 --error "xcodebuild failed" --increment-retry
#   bash pipeline.sh run-gate --gate "4->5"             # run gate, record evidence (no phase mutation)
#   bash pipeline.sh record-environment --xcodegen true --stitch false
#   bash pipeline.sh set-flag --key backend_required --value true
#   bash pipeline.sh complete-phase --phase 1           # legacy; prefer advance-phase
set -euo pipefail

MODE="${1:-}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

USAGE="Usage: pipeline.sh <schema|init-build|record-environment|set-flag|start-phase|advance-phase|complete-phase|fail-phase|run-gate> [options]"

if [[ -z "$MODE" ]]; then
  echo "$USAGE" >&2
  exit 1
fi

shift

case "$MODE" in
  schema)             exec python3 "$RUNTIME" validate-schema    --project-dir "$PROJECT_DIR" "$@" ;;
  init-build)         exec python3 "$RUNTIME" init-state         --project-dir "$PROJECT_DIR" "$@" ;;
  record-environment) exec python3 "$RUNTIME" record-environment --project-dir "$PROJECT_DIR" "$@" ;;
  set-flag)           exec python3 "$RUNTIME" set-flag           --project-dir "$PROJECT_DIR" "$@" ;;
  start-phase)        exec python3 "$RUNTIME" start-phase        --project-dir "$PROJECT_DIR" "$@" ;;
  advance-phase)      exec python3 "$RUNTIME" advance-phase      --project-dir "$PROJECT_DIR" "$@" ;;
  complete-phase)     exec python3 "$RUNTIME" complete-phase     --project-dir "$PROJECT_DIR" "$@" ;;
  fail-phase)         exec python3 "$RUNTIME" fail-phase         --project-dir "$PROJECT_DIR" "$@" ;;
  run-gate)           exec python3 "$RUNTIME" run-gate           --project-dir "$PROJECT_DIR" "$@" ;;
  *)
    echo "$USAGE" >&2
    exit 1
    ;;
esac
