#!/bin/bash
# Thin entrypoint for the runtime-backed pipeline engine.
# Usage:
#   bash pipeline.sh schema
#   bash pipeline.sh init-build --build-id build-20260401-demo --app-name Demo --display-name "Demo"
#   bash pipeline.sh start-phase --phase 1 --detail "Architecture + Contracts"
#   bash pipeline.sh complete-phase --phase 1
#   bash pipeline.sh fail-phase --phase 5 --error "xcodebuild failed" --increment-retry
#   bash pipeline.sh run-gate --gate "4->5"
#   bash pipeline.sh record-environment --xcodegen true --stitch false
set -euo pipefail

MODE="${1:-}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

if [[ -z "$MODE" ]]; then
  echo "Usage: pipeline.sh <schema|init-build|record-environment|start-phase|complete-phase|fail-phase|run-gate> [options]" >&2
  exit 1
fi

shift

case "$MODE" in
  schema)
    exec python3 "$RUNTIME" validate-schema --project-dir "$PROJECT_DIR" "$@"
    ;;
  init-build)
    exec python3 "$RUNTIME" init-state --project-dir "$PROJECT_DIR" "$@"
    ;;
  record-environment)
    exec python3 "$RUNTIME" record-environment --project-dir "$PROJECT_DIR" "$@"
    ;;
  start-phase)
    exec python3 "$RUNTIME" start-phase --project-dir "$PROJECT_DIR" "$@"
    ;;
  complete-phase)
    exec python3 "$RUNTIME" complete-phase --project-dir "$PROJECT_DIR" "$@"
    ;;
  fail-phase)
    exec python3 "$RUNTIME" fail-phase --project-dir "$PROJECT_DIR" "$@"
    ;;
  run-gate)
    exec python3 "$RUNTIME" run-gate --project-dir "$PROJECT_DIR" "$@"
    ;;
  *)
    echo "Usage: pipeline.sh <schema|init-build|record-environment|start-phase|complete-phase|fail-phase|run-gate> [options]" >&2
    exit 1
    ;;
esac
