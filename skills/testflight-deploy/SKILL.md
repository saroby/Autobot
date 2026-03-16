---
name: autobot-testflight-deploy
description: This skill should be used when deploying an iOS app to TestFlight, setting up code signing, archiving builds, uploading to App Store Connect, creating beta tester groups, or when the "/autobot:build" deployment phase is reached. Covers the complete archive → export → upload → tester setup pipeline.
version: 0.1.0
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

# 3. App Store Connect credentials (one of):
# - ASC_API_KEY_ID + ASC_API_ISSUER_ID + ASC_API_KEY_PATH (API Key)
# - APPLE_ID + APP_SPECIFIC_PASSWORD (Apple ID)
echo "ASC_API_KEY_ID: ${ASC_API_KEY_ID:-not set}"
echo "APPLE_ID: ${APPLE_ID:-not set}"
```

## Deployment Pipeline

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
