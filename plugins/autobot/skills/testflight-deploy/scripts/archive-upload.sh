#!/bin/bash
# Archive iOS app and upload to TestFlight
# Usage: archive-upload.sh --project-path /path/to/project --scheme AppName
set -euo pipefail

PROJECT_PATH=""
SCHEME=""
TEAM_ID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --project-path) PROJECT_PATH="$2"; shift 2;;
    --scheme) SCHEME="$2"; shift 2;;
    --team-id) TEAM_ID="$2"; shift 2;;
    *) echo "Unknown option: $1"; exit 1;;
  esac
done

if [ -z "$PROJECT_PATH" ] || [ -z "$SCHEME" ]; then
  echo "Error: --project-path and --scheme are required"
  exit 1
fi

cd "$PROJECT_PATH"

BUILD_DIR="build"
ARCHIVE_PATH="${BUILD_DIR}/${SCHEME}.xcarchive"
EXPORT_PATH="${BUILD_DIR}/export"
EXPORT_OPTIONS="${BUILD_DIR}/ExportOptions.plist"

mkdir -p "$BUILD_DIR"

# Auto-detect team ID
if [ -z "$TEAM_ID" ]; then
  TEAM_ID=$(grep -m1 "DEVELOPMENT_TEAM" *.xcodeproj/project.pbxproj 2>/dev/null | \
    grep -oE '[A-Z0-9]{10}' | head -1 || echo "")
fi

# Create ExportOptions.plist
cat > "$EXPORT_OPTIONS" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store-connect</string>
    <key>signingStyle</key>
    <string>automatic</string>
    <key>uploadBitcode</key>
    <false/>
    <key>uploadSymbols</key>
    <true/>
    <key>destination</key>
    <string>upload</string>
</dict>
</plist>
PLIST_EOF

echo "=== Step 1: Archive ==="
XCODEPROJ=$(ls -d *.xcodeproj 2>/dev/null | head -1)
if [ -z "$XCODEPROJ" ]; then
  echo "Error: No .xcodeproj found"
  exit 1
fi

ARCHIVE_CMD="xcodebuild archive \
  -project \"$XCODEPROJ\" \
  -scheme \"$SCHEME\" \
  -archivePath \"$ARCHIVE_PATH\" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic"

if [ -n "$TEAM_ID" ]; then
  ARCHIVE_CMD="$ARCHIVE_CMD DEVELOPMENT_TEAM=$TEAM_ID"
fi

eval $ARCHIVE_CMD 2>&1

if [ ! -d "$ARCHIVE_PATH" ]; then
  echo "Error: Archive failed"
  exit 1
fi
echo "Archive created: $ARCHIVE_PATH"

echo "=== Step 2: Export IPA ==="
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE_PATH" \
  -exportOptionsPlist "$EXPORT_OPTIONS" \
  -exportPath "$EXPORT_PATH" \
  -allowProvisioningUpdates 2>&1

IPA_FILE=$(ls "$EXPORT_PATH"/*.ipa 2>/dev/null | head -1)
if [ -z "$IPA_FILE" ]; then
  echo "Error: IPA export failed"
  exit 1
fi
echo "IPA exported: $IPA_FILE"

echo "=== Step 3: Upload to App Store Connect ==="
if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ]; then
  echo "Uploading with API Key..."
  xcrun altool --upload-app \
    -f "$IPA_FILE" \
    --type ios \
    --apiKey "$ASC_API_KEY_ID" \
    --apiIssuer "$ASC_API_ISSUER_ID" 2>&1
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APP_SPECIFIC_PASSWORD:-}" ]; then
  echo "Uploading with Apple ID..."
  xcrun altool --upload-app \
    -f "$IPA_FILE" \
    --type ios \
    -u "$APPLE_ID" \
    -p "$APP_SPECIFIC_PASSWORD" 2>&1
else
  echo "Warning: No App Store Connect credentials found."
  echo "Set ASC_API_KEY_ID + ASC_API_ISSUER_ID, or APPLE_ID + APP_SPECIFIC_PASSWORD"
  echo "IPA is available at: $IPA_FILE"
  echo "Upload manually via Xcode Organizer or Transporter app."
  exit 0
fi

echo "=== Upload Complete ==="
echo "Build uploaded to App Store Connect. Check TestFlight in App Store Connect."
