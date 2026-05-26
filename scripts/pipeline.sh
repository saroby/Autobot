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
#
# Helper subcommands (delegate to focused scripts; same project-dir handling):
#   bash pipeline.sh env-snapshot         capture|load|ensure|is-stale
#   bash pipeline.sh write-run-summary    (write artifacts/<buildId>/run-summary.{json,md})
#   bash pipeline.sh grade-learnings      --build-id <id>   (update learning effect_score)
#   bash pipeline.sh input-hash           compute|should-skip --phase N [--force]
#   bash pipeline.sh context-pack         --phase N --agent <name> [--budget N] [--format text|json]
#   bash pipeline.sh error-signature      check|record|normalize --phase N [--stderr-file ...|--signature ...]
#   bash pipeline.sh design-spec          validate|synthesize|ensure ...
#   bash pipeline.sh sandbox              check|set-active|clear-active ...
set -euo pipefail

MODE="${1:-}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

USAGE="Usage: pipeline.sh <schema|init-build|record-environment|set-flag|start-phase|advance-phase|complete-phase|fail-phase|run-gate|env-snapshot|write-run-summary|grade-learnings|input-hash|context-pack|error-signature|design-spec|sandbox> [options]"

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

  # ── Helper passthroughs to focused modules ───────────────────────────────
  env-snapshot)
    SUBCMD="${1:-ensure}"; shift || true
    exec python3 "${SCRIPT_DIR}/env_snapshot.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  write-run-summary)
    exec python3 "${SCRIPT_DIR}/run_summary.py" write --project-dir "$PROJECT_DIR" "$@"
    ;;
  grade-learnings)
    exec python3 "${SCRIPT_DIR}/learning_impact.py" grade --project-dir "$PROJECT_DIR" "$@"
    ;;
  input-hash)
    SUBCMD="${1:-should-skip}"; shift || true
    exec python3 "${SCRIPT_DIR}/input_hash.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  context-pack)
    exec python3 "${SCRIPT_DIR}/context_pack.py" --project-dir "$PROJECT_DIR" "$@"
    ;;
  error-signature)
    SUBCMD="${1:-check}"; shift || true
    exec python3 "${SCRIPT_DIR}/error_signature.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  design-spec)
    SUBCMD="${1:-ensure}"; shift || true
    exec python3 "${SCRIPT_DIR}/design_spec_validator.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  sandbox)
    SUBCMD="${1:-check}"; shift || true
    exec python3 "${SCRIPT_DIR}/sandbox_guard.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  *)
    echo "$USAGE" >&2
    exit 1
    ;;
esac
