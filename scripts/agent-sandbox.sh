#!/bin/bash
# Thin wrapper around sandbox_runner.py — file ownership rules now live in
# spec/pipeline.json under fileOwnership.
#
# Usage:
#   bash agent-sandbox.sh before --agent ui-builder --app-name AppName
#   (run agent)
#   bash agent-sandbox.sh after  --agent ui-builder --app-name AppName --phase 4
set -euo pipefail

MODE=""
AGENT=""
APP_NAME=""
PHASE=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    before|after)  MODE="$1"; shift ;;
    --agent)       AGENT="$2";    shift 2 ;;
    --app-name)    APP_NAME="$2"; shift 2 ;;
    --phase)       PHASE="$2";    shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$MODE" || -z "$AGENT" || -z "$APP_NAME" ]]; then
  echo "Usage: agent-sandbox.sh <before|after> --agent <name> --app-name <App> [--phase <N>] [--project-dir <dir>]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="${SCRIPT_DIR}/sandbox_runner.py"

case "$MODE" in
  before)
    exec python3 "$RUNNER" snapshot --agent "$AGENT" --app-name "$APP_NAME" --project-dir "$PROJECT_DIR"
    ;;
  after)
    if [[ -z "$PHASE" ]]; then
      echo "ERROR: agent-sandbox.sh after requires --phase <N>" >&2
      exit 2
    fi
    exec python3 "$RUNNER" verify --agent "$AGENT" --app-name "$APP_NAME" --phase "$PHASE" --project-dir "$PROJECT_DIR"
    ;;
esac
