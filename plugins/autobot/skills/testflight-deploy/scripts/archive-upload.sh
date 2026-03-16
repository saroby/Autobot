#!/bin/bash
# Archive iOS app and upload to TestFlight
# Usage: archive-upload.sh --project-path /path/to/project --scheme AppName
set -euo pipefail

PROJECT_PATH=""
SCHEME=""
TEAM_ID=""
BUNDLE_ID=""
DISPLAY_NAME=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --project-path) PROJECT_PATH="$2"; shift 2;;
    --scheme) SCHEME="$2"; shift 2;;
    --team-id) TEAM_ID="$2"; shift 2;;
    --bundle-id) BUNDLE_ID="$2"; shift 2;;
    --display-name) DISPLAY_NAME="$2"; shift 2;;
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

# Find .xcodeproj (safely — no raw glob)
XCODEPROJ=$(ls -d *.xcodeproj 2>/dev/null | head -1)
if [ -z "$XCODEPROJ" ]; then
  echo "Error: No .xcodeproj found in $(pwd)"
  exit 1
fi

# Auto-detect team ID
if [ -z "$TEAM_ID" ]; then
  TEAM_ID=$(grep -m1 "DEVELOPMENT_TEAM" "$XCODEPROJ/project.pbxproj" 2>/dev/null | \
    grep -oE '[A-Z0-9]{10}' | head -1 || echo "")
fi

# Auto-detect bundle ID from project if not provided
if [ -z "$BUNDLE_ID" ]; then
  BUNDLE_ID=$(grep -m1 "PRODUCT_BUNDLE_IDENTIFIER" "$XCODEPROJ/project.pbxproj" 2>/dev/null | \
    sed 's/.*= *"\{0,1\}\([^";]*\)"\{0,1\}.*/\1/' | head -1 || echo "")
fi

# Use scheme as display name fallback
if [ -z "$DISPLAY_NAME" ]; then
  DISPLAY_NAME="$SCHEME"
fi

# ── Step 0: Register App on App Store Connect ──
echo "=== Step 0: Register App on App Store Connect ==="

if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ] && [ -n "$BUNDLE_ID" ]; then
  # Check fastlane availability
  if ! command -v fastlane &>/dev/null; then
    echo "fastlane not found. Installing via Homebrew..."
    brew install fastlane || {
      echo "WARNING: fastlane install failed. Skipping app registration."
      echo "Register manually: https://appstoreconnect.apple.com → My Apps → +"
      echo "  Bundle ID: $BUNDLE_ID"
      echo "  App Name: $DISPLAY_NAME"
    }
  fi

  if command -v fastlane &>/dev/null; then
    # Create API key JSON for fastlane
    API_KEY_JSON="${BUILD_DIR}/fastlane_api_key.json"
    cat > "$API_KEY_JSON" << KEYEOF
{
  "key_id": "$ASC_API_KEY_ID",
  "issuer_id": "$ASC_API_ISSUER_ID",
  "key_filepath": "$ASC_API_KEY_PATH"
}
KEYEOF

    # Register app (idempotent — skips if already exists)
    echo "Registering app: $BUNDLE_ID ($DISPLAY_NAME)"
    fastlane produce create \
      --app_identifier "$BUNDLE_ID" \
      --app_name "$DISPLAY_NAME" \
      --language "ko" \
      --app_version "1.0.0" \
      --sku "$BUNDLE_ID" \
      ${TEAM_ID:+--team_id "$TEAM_ID"} \
      --api_key_path "$API_KEY_JSON" \
      2>&1 || echo "App may already exist on ASC, continuing..."

    rm -f "$API_KEY_JSON"
    echo "App registration step complete."
  fi
else
  echo "Skipping app registration: ASC credentials or bundle ID not available."
  echo "Ensure the app is registered on App Store Connect before upload."
fi

# Create ExportOptions.plist (destination: upload → export와 업로드를 한 단계로 수행)
cat > "$EXPORT_OPTIONS" << 'PLIST_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>app-store-connect</string>
    <key>destination</key>
    <string>upload</string>
    <key>signingStyle</key>
    <string>automatic</string>
    <key>uploadSymbols</key>
    <true/>
    <key>manageAppVersionAndBuildNumber</key>
    <true/>
    <key>testFlightInternalTestingOnly</key>
    <true/>
</dict>
</plist>
PLIST_EOF

echo "=== Step 1: Archive ==="

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

echo "=== Step 2: Export + Upload to App Store Connect ==="
# xcodebuild -exportArchive with destination:upload handles export AND upload in one step.
# xcrun altool is deprecated — this is the official replacement.

EXPORT_CMD=(
  xcodebuild -exportArchive
  -archivePath "$ARCHIVE_PATH"
  -exportOptionsPlist "$EXPORT_OPTIONS"
  -exportPath "$EXPORT_PATH"
  -allowProvisioningUpdates
)

if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ]; then
  echo "Authenticating with App Store Connect API Key..."
  EXPORT_CMD+=(
    -authenticationKeyPath "$ASC_API_KEY_PATH"
    -authenticationKeyID "$ASC_API_KEY_ID"
    -authenticationKeyIssuerID "$ASC_API_ISSUER_ID"
  )
else
  echo "No API Key found. Attempting upload with Xcode-stored credentials..."
  echo "(Ensure your Apple ID is signed in at Xcode → Settings → Accounts)"
fi

"${EXPORT_CMD[@]}" 2>&1
EXPORT_EXIT=$?

if [ $EXPORT_EXIT -ne 0 ]; then
  # Export+upload failed — check if IPA was at least created
  IPA_FILE=$(ls "$EXPORT_PATH"/*.ipa 2>/dev/null | head -1)
  if [ -n "$IPA_FILE" ]; then
    echo "Warning: IPA exported but upload failed."
    echo "IPA is available at: $IPA_FILE"
    echo "Upload manually via:"
    echo "  1. Apple Transporter app (Mac App Store, free)"
    echo "  2. Xcode → Window → Organizer → Distribute App"
  else
    echo "Error: Export failed."
  fi
  exit 1
fi

echo "=== Upload Complete ==="
echo "Build exported and uploaded to App Store Connect."
echo "Check TestFlight status at: https://appstoreconnect.apple.com"
