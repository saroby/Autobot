#!/bin/bash
# Save, verify, or restore build artifact snapshots.
#
# Models-level (Phase 1 type contract):
#   snapshot-contracts.sh save    --app-name <AppName>
#   snapshot-contracts.sh verify  --app-name <AppName>
#   snapshot-contracts.sh restore --app-name <AppName>
#
# Phase-level (full Phase output snapshot):
#   snapshot-contracts.sh save-phase    --phase 4 --app-name <AppName>
#   snapshot-contracts.sh restore-phase --phase 4 --app-name <AppName>
set -euo pipefail

MODE=""
APP_NAME=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
PHASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    save|verify|restore|save-phase|restore-phase)
      MODE="$1"
      shift
      ;;
    --app-name)
      APP_NAME="$2"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --phase)
      PHASE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" || -z "$APP_NAME" ]]; then
  echo "Usage: snapshot-contracts.sh <save|verify|restore|save-phase|restore-phase> --app-name <AppName> [--project-dir <dir>] [--phase <N>]" >&2
  exit 1
fi

if [[ "$MODE" == "save-phase" || "$MODE" == "restore-phase" ]] && [[ -z "$PHASE" ]]; then
  echo "Phase-level commands require --phase <N>" >&2
  exit 1
fi

MODELS_DIR="${PROJECT_DIR}/${APP_NAME}/Models"
CONTRACTS_DIR="${PROJECT_DIR}/.autobot/contracts"
SNAPSHOT_DIR="${CONTRACTS_DIR}/phase-1-models"
CHECKSUM_FILE="${CONTRACTS_DIR}/models.sha256"

# Models-level commands rely on Models/ existing; Phase-level commands defer
# everything to snapshot_runner.py which derives directories from spec.
if [[ "$MODE" == "save" || "$MODE" == "verify" ]] && [[ ! -d "$MODELS_DIR" ]]; then
  echo "Models directory not found: ${MODELS_DIR}" >&2
  exit 1
fi

checksum_dir() {
  local target="$1"
  if [[ ! -d "$target" ]]; then
    return 1
  fi

  find "$target" -type f -name "*.swift" -print0 \
    | sort -z \
    | xargs -0 shasum -a 256 \
    | shasum -a 256 \
    | awk '{print $1}'
}

case "$MODE" in
  save)
    mkdir -p "$CONTRACTS_DIR"
    rm -rf "$SNAPSHOT_DIR"
    mkdir -p "$SNAPSHOT_DIR"
    cp -R "${MODELS_DIR}/." "$SNAPSHOT_DIR/"
    checksum_dir "$MODELS_DIR" > "$CHECKSUM_FILE"
    echo "saved ${SNAPSHOT_DIR}"
    ;;
  verify)
    if [[ ! -d "$SNAPSHOT_DIR" || ! -f "$CHECKSUM_FILE" ]]; then
      echo "snapshot_missing" >&2
      exit 2
    fi
    CURRENT_SUM="$(checksum_dir "$MODELS_DIR")"
    SAVED_SUM="$(cat "$CHECKSUM_FILE")"
    if [[ "$CURRENT_SUM" != "$SAVED_SUM" ]]; then
      echo "mismatch" >&2
      exit 3
    fi
    echo "verified ${CURRENT_SUM}"
    ;;
  restore)
    if [[ ! -d "$SNAPSHOT_DIR" || ! -f "$CHECKSUM_FILE" ]]; then
      echo "snapshot_missing" >&2
      exit 2
    fi
    rm -rf "$MODELS_DIR"
    mkdir -p "$MODELS_DIR"
    cp -R "${SNAPSHOT_DIR}/." "$MODELS_DIR/"
    echo "restored ${MODELS_DIR}"
    ;;

  save-phase)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    exec python3 "${SCRIPT_DIR}/snapshot_runner.py" save-phase \
      --phase "$PHASE" --app-name "$APP_NAME" --project-dir "$PROJECT_DIR"
    ;;

  restore-phase)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    exec python3 "${SCRIPT_DIR}/snapshot_runner.py" restore-phase \
      --phase "$PHASE" --app-name "$APP_NAME" --project-dir "$PROJECT_DIR"
    ;;
esac
