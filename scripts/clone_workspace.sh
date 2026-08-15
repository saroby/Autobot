#!/usr/bin/env bash
# clone_workspace.sh — prepare the Xcode workspace used by /autobot:clone.
#
# The workspace is deliberately separate from the captured source artifacts.
# Creating/opening it gives Xcode a project to load while CoreDevice is being
# re-established, without installing or launching an app before observation.
set -euo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_SCAFFOLD="${_HERE}/../skills/autobot-ios-scaffold/scripts/create-xcode-project.sh"

PROJECT_DIR="${CLONE_WORKSPACE_DIR:-.autobot/clone/project}"
APP_NAME="${CLONE_WORKSPACE_NAME:-CloneWorkspace}"
BUNDLE_ID="${CLONE_WORKSPACE_BUNDLE_ID:-com.axi.cloneworkspace}"
DEPLOYMENT_TARGET="${CLONE_WORKSPACE_DEPLOYMENT_TARGET:-26.0}"

usage() {
  echo "Usage: clone_workspace.sh prepare [--project-dir DIR] [--name NAME] [--bundle-id ID] [--deployment-target VERSION]" >&2
}

if [[ "${1:-}" != "prepare" ]]; then
  usage
  exit 2
fi
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      PROJECT_DIR="$2"; shift 2 ;;
    --name)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      APP_NAME="$2"; shift 2 ;;
    --bundle-id)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      BUNDLE_ID="$2"; shift 2 ;;
    --deployment-target)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      DEPLOYMENT_TARGET="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage; exit 2 ;;
  esac
done

if [[ ! -f "$_SCAFFOLD" ]]; then
  echo "ERROR: Xcode scaffold script is missing: $_SCAFFOLD" >&2
  exit 1
fi

# The default name is already a valid scaffold identifier. The expected path
# also makes repeated preparation a no-op once the project exists.
if [[ ! -d "${PROJECT_DIR}/${APP_NAME}.xcodeproj" ]]; then
  bash "$_SCAFFOLD" \
    --name "$APP_NAME" \
    --bundle-id "$BUNDLE_ID" \
    --project-dir "$PROJECT_DIR" \
    --deployment-target "$DEPLOYMENT_TARGET"
fi

project="${PROJECT_DIR}/${APP_NAME}.xcodeproj"
if [[ ! -d "$project" ]]; then
  echo "ERROR: clone Xcode project was not created: $project" >&2
  exit 1
fi

echo "OK: clone Xcode workspace $project"
