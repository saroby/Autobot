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

if [[ ! -d "$MODELS_DIR" && "$MODE" != "restore" && "$MODE" != "restore-phase" ]]; then
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
    # Phase-level snapshot: save all output directories for a given phase
    PHASE_SNAP_DIR="${CONTRACTS_DIR}/phase-${PHASE}-snapshot"
    rm -rf "$PHASE_SNAP_DIR"
    mkdir -p "$PHASE_SNAP_DIR"

    # Define which directories to snapshot per phase
    SOURCES_DIR="${PROJECT_DIR}/${APP_NAME}"
    case "$PHASE" in
      1)
        # Models/ only (already handled by 'save', but included for completeness)
        [[ -d "${SOURCES_DIR}/Models" ]] && cp -R "${SOURCES_DIR}/Models" "$PHASE_SNAP_DIR/"
        ;;
      2)
        # UX design artifacts
        [[ -f "${PROJECT_DIR}/.autobot/design-spec.md" ]] && cp "${PROJECT_DIR}/.autobot/design-spec.md" "$PHASE_SNAP_DIR/"
        [[ -d "${PROJECT_DIR}/.autobot/designs" ]] && cp -R "${PROJECT_DIR}/.autobot/designs" "$PHASE_SNAP_DIR/"
        ;;
      3)
        # Scaffold artifacts (lightweight — config files only, not the full .xcodeproj)
        [[ -f "${SOURCES_DIR}/PrivacyInfo.xcprivacy" ]] && cp "${SOURCES_DIR}/PrivacyInfo.xcprivacy" "$PHASE_SNAP_DIR/"
        [[ -f "${SOURCES_DIR}/${APP_NAME}.entitlements" ]] && cp "${SOURCES_DIR}/${APP_NAME}.entitlements" "$PHASE_SNAP_DIR/"
        [[ -f "${PROJECT_DIR}/.gitignore" ]] && cp "${PROJECT_DIR}/.gitignore" "$PHASE_SNAP_DIR/"
        [[ -f "${PROJECT_DIR}/project.yml" ]] && cp "${PROJECT_DIR}/project.yml" "$PHASE_SNAP_DIR/"
        ;;
      4)
        # Phase 4 parallel coding output — the most valuable snapshot
        for dir in Views ViewModels Services Utilities App; do
          [[ -d "${SOURCES_DIR}/${dir}" ]] && cp -R "${SOURCES_DIR}/${dir}" "$PHASE_SNAP_DIR/"
        done
        # Asset catalog color sets (Theme)
        if [[ -d "${SOURCES_DIR}/Assets.xcassets" ]]; then
          mkdir -p "$PHASE_SNAP_DIR/Assets.xcassets"
          find "${SOURCES_DIR}/Assets.xcassets" -name "*.colorset" -type d -exec cp -R {} "$PHASE_SNAP_DIR/Assets.xcassets/" \; 2>/dev/null || true
        fi
        # Backend (if exists)
        [[ -d "${PROJECT_DIR}/backend" ]] && cp -R "${PROJECT_DIR}/backend" "$PHASE_SNAP_DIR/"
        ;;
      *)
        echo "Phase ${PHASE} does not support snapshots" >&2
        exit 1
        ;;
    esac

    echo "saved phase-${PHASE} → ${PHASE_SNAP_DIR}"
    ;;

  restore-phase)
    PHASE_SNAP_DIR="${CONTRACTS_DIR}/phase-${PHASE}-snapshot"
    if [[ ! -d "$PHASE_SNAP_DIR" ]]; then
      echo "snapshot_missing: ${PHASE_SNAP_DIR}" >&2
      exit 2
    fi

    SOURCES_DIR="${PROJECT_DIR}/${APP_NAME}"
    case "$PHASE" in
      1)
        [[ -d "$PHASE_SNAP_DIR/Models" ]] && { rm -rf "${SOURCES_DIR}/Models"; cp -R "$PHASE_SNAP_DIR/Models" "${SOURCES_DIR}/"; }
        ;;
      2)
        [[ -f "$PHASE_SNAP_DIR/design-spec.md" ]] && cp "$PHASE_SNAP_DIR/design-spec.md" "${PROJECT_DIR}/.autobot/"
        [[ -d "$PHASE_SNAP_DIR/designs" ]] && { rm -rf "${PROJECT_DIR}/.autobot/designs"; cp -R "$PHASE_SNAP_DIR/designs" "${PROJECT_DIR}/.autobot/"; }
        ;;
      3)
        [[ -f "$PHASE_SNAP_DIR/PrivacyInfo.xcprivacy" ]] && cp "$PHASE_SNAP_DIR/PrivacyInfo.xcprivacy" "${SOURCES_DIR}/"
        [[ -f "$PHASE_SNAP_DIR/${APP_NAME}.entitlements" ]] && cp "$PHASE_SNAP_DIR/${APP_NAME}.entitlements" "${SOURCES_DIR}/"
        [[ -f "$PHASE_SNAP_DIR/.gitignore" ]] && cp "$PHASE_SNAP_DIR/.gitignore" "${PROJECT_DIR}/"
        [[ -f "$PHASE_SNAP_DIR/project.yml" ]] && cp "$PHASE_SNAP_DIR/project.yml" "${PROJECT_DIR}/"
        ;;
      4)
        for dir in Views ViewModels Services Utilities App; do
          [[ -d "$PHASE_SNAP_DIR/${dir}" ]] && { rm -rf "${SOURCES_DIR}/${dir}"; cp -R "$PHASE_SNAP_DIR/${dir}" "${SOURCES_DIR}/"; }
        done
        if [[ -d "$PHASE_SNAP_DIR/Assets.xcassets" ]]; then
          # Restore only color sets, preserve other assets
          find "$PHASE_SNAP_DIR/Assets.xcassets" -name "*.colorset" -type d -exec cp -R {} "${SOURCES_DIR}/Assets.xcassets/" \; 2>/dev/null || true
        fi
        [[ -d "$PHASE_SNAP_DIR/backend" ]] && { rm -rf "${PROJECT_DIR}/backend"; cp -R "$PHASE_SNAP_DIR/backend" "${PROJECT_DIR}/"; }
        ;;
      *)
        echo "Phase ${PHASE} does not support restore" >&2
        exit 1
        ;;
    esac

    echo "restored phase-${PHASE} → ${SOURCES_DIR}"
    ;;
esac
