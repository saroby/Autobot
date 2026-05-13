#!/bin/bash
# Apply or verify the generated 1024x1024 app icon asset.
# Usage:
#   bash app-icon.sh apply  --app-name <AppName> --source .autobot/app-icon-1024.png [--project-dir .]
#   bash app-icon.sh verify --app-name <AppName> [--project-dir .]
set -euo pipefail

MODE=""
APP_NAME=""
SOURCE=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    apply|verify)
      MODE="$1"
      shift
      ;;
    --app-name)
      APP_NAME="$2"
      shift 2
      ;;
    --source)
      SOURCE="$2"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MODE" || -z "$APP_NAME" ]]; then
  echo "Usage: app-icon.sh <apply|verify> --app-name <AppName> [--source <png>] [--project-dir <dir>]" >&2
  exit 1
fi

ICON_DIR="${PROJECT_DIR}/${APP_NAME}/Assets.xcassets/AppIcon.appiconset"
ICON_FILE="${ICON_DIR}/AppIcon-1024.png"
CONTENTS_FILE="${ICON_DIR}/Contents.json"

write_contents() {
  cat > "$CONTENTS_FILE" << 'JSON_EOF'
{
  "images": [
    {
      "filename": "AppIcon-1024.png",
      "idiom": "universal",
      "platform": "ios",
      "size": "1024x1024"
    }
  ],
  "info": { "version": 1, "author": "xcode" }
}
JSON_EOF
}

case "$MODE" in
  apply)
    if [[ -z "$SOURCE" || ! -f "$SOURCE" ]]; then
      echo "ERROR: icon source not found: ${SOURCE:-<missing>}" >&2
      exit 2
    fi

    mkdir -p "$ICON_DIR"
    if command -v sips >/dev/null 2>&1; then
      sips -s format png -z 1024 1024 "$SOURCE" --out "$ICON_FILE" >/dev/null
    else
      cp "$SOURCE" "$ICON_FILE"
    fi
    write_contents
    echo "applied app icon: $ICON_FILE"
    ;;

  verify)
    if [[ ! -f "$CONTENTS_FILE" ]]; then
      echo "ERROR: AppIcon Contents.json missing: $CONTENTS_FILE" >&2
      exit 2
    fi
    if ! grep -q '"filename"[[:space:]]*:[[:space:]]*"AppIcon-1024.png"' "$CONTENTS_FILE"; then
      echo "ERROR: AppIcon Contents.json does not reference AppIcon-1024.png" >&2
      exit 3
    fi
    if [[ ! -s "$ICON_FILE" ]]; then
      echo "ERROR: AppIcon image missing or empty: $ICON_FILE" >&2
      exit 4
    fi
    echo "verified app icon: $ICON_FILE"
    ;;

  *)
    echo "ERROR: Unknown mode: $MODE" >&2
    exit 1
    ;;
esac
