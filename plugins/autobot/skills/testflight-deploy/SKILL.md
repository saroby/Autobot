---
name: autobot-testflight-deploy
description: Use when deploying an iOS app to TestFlight, setting up code signing, archiving builds, uploading to App Store Connect, creating beta tester groups, or when the "/autobot:build" deployment phase is reached.
---

# TestFlight Deployment

Complete pipeline for archiving iOS apps and deploying to TestFlight.

## Prerequisites Check

Before deployment, verify:

```bash
# 1. Xcode Command Line Tools
xcode-select -p

# 2. Signing identities
security find-identity -v -p codesigning

# 3. fastlane (앱 등록용)
which fastlane || echo "fastlane not found — will install via brew"

# 4. App Store Connect credentials (one of):
# - ASC_API_KEY_ID + ASC_API_ISSUER_ID + ASC_API_KEY_PATH (API Key)
# - APPLE_ID + APP_SPECIFIC_PASSWORD (Apple ID)
echo "ASC_API_KEY_ID: ${ASC_API_KEY_ID:-not set}"
echo "APPLE_ID: ${APPLE_ID:-not set}"
```

## Deployment Pipeline

### Step 0: Register App on App Store Connect

새로 만든 앱은 App Store Connect에 등록되어 있지 않다. 아카이브 전에 반드시 등록해야 한다.

```bash
# fastlane 설치 (없으면)
command -v fastlane &>/dev/null || brew install fastlane

# API Key JSON 생성
cat > fastlane_api_key.json << EOF
{
  "key_id": "$ASC_API_KEY_ID",
  "issuer_id": "$ASC_API_ISSUER_ID",
  "key_filepath": "$ASC_API_KEY_PATH"
}
EOF

# 앱 등록 (멱등 — 이미 존재하면 스킵)
fastlane produce create \
  --app_identifier "$BUNDLE_ID" \
  --app_name "$DISPLAY_NAME" \
  --language "ko" \
  --app_version "1.0.0" \
  --sku "$BUNDLE_ID" \
  --team_id "$DEVELOPMENT_TEAM" \
  --api_key_path fastlane_api_key.json \
  2>&1 || echo "App may already exist, continuing..."
```

> fastlane produce는 Apple Developer Portal에 App ID를 등록하고, App Store Connect에 앱을 생성한다.
> 이미 등록된 앱이면 에러 없이 계속 진행한다.

### Step 1: Detect Team ID

```bash
# From Xcode project
grep "DEVELOPMENT_TEAM" *.xcodeproj/project.pbxproj | grep -v "\"\"" | head -1

# From signing identities
security find-identity -v -p codesigning | grep "Apple Development" | head -1
```

### Step 2: Archive

```bash
xcodebuild archive \
  -project "AppName.xcodeproj" \
  -scheme "AppName" \
  -archivePath "build/AppName.xcarchive" \
  -destination 'generic/platform=iOS' \
  -allowProvisioningUpdates \
  CODE_SIGN_STYLE=Automatic
```

### Step 3: Export IPA

Create ExportOptions.plist and export:

```bash
xcodebuild -exportArchive \
  -archivePath "build/AppName.xcarchive" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath "build/export" \
  -allowProvisioningUpdates
```

### Step 4: Upload

Use the appropriate upload method based on available credentials.
Refer to `references/signing-guide.md` for detailed credential setup.

### Step 5: Tester Group

Create '내부' group and invite user via App Store Connect API.

## Fallback Strategy

If automated upload fails:
1. Report the archive path to user
2. Provide manual upload instructions via Xcode Organizer
3. Log failure reason for retrospective

## Additional Resources

- **`references/signing-guide.md`** — Code signing setup, credential management, and troubleshooting
- **`scripts/archive-upload.sh`** — Automated archive and upload script
