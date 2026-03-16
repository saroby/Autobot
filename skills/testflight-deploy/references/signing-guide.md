# Code Signing & Upload Guide

## Authentication Methods

### Method 1: App Store Connect API Key (Recommended)

Set these environment variables:
```bash
export ASC_API_KEY_ID="XXXXXXXXXX"        # Key ID from App Store Connect
export ASC_API_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Issuer ID
export ASC_API_KEY_PATH="~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8"
```

Upload command:
```bash
xcrun altool --upload-app \
  -f "build/export/AppName.ipa" \
  --type ios \
  --apiKey "$ASC_API_KEY_ID" \
  --apiIssuer "$ASC_API_ISSUER_ID"
```

### Method 2: Apple ID + App-Specific Password

Set these environment variables:
```bash
export APPLE_ID="your@email.com"
export APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"  # Generate at appleid.apple.com
```

Upload command:
```bash
xcrun altool --upload-app \
  -f "build/export/AppName.ipa" \
  --type ios \
  -u "$APPLE_ID" \
  -p "$APP_SPECIFIC_PASSWORD"
```

### Method 3: Xcode (Manual Fallback)

If neither method is available:
```
1. Open Xcode
2. Window → Organizer
3. Select the archive
4. Distribute App → App Store Connect → Upload
```

## ExportOptions.plist

### For TestFlight (App Store Connect)
```xml
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
```

## TestFlight Group Setup via API

### Generate JWT Token
```bash
# Requires: openssl, ASC_API_KEY_PATH, ASC_API_KEY_ID, ASC_API_ISSUER_ID
HEADER=$(echo -n '{"alg":"ES256","kid":"'$ASC_API_KEY_ID'","typ":"JWT"}' | base64 | tr -d '=' | tr '+/' '-_')
NOW=$(date +%s)
EXP=$((NOW + 1200))
PAYLOAD=$(echo -n '{"iss":"'$ASC_API_ISSUER_ID'","iat":'$NOW',"exp":'$EXP',"aud":"appstoreconnect-v1"}' | base64 | tr -d '=' | tr '+/' '-_')
SIGNATURE=$(echo -n "$HEADER.$PAYLOAD" | openssl dgst -sha256 -sign "$ASC_API_KEY_PATH" | base64 | tr -d '=' | tr '+/' '-_')
JWT_TOKEN="$HEADER.$PAYLOAD.$SIGNATURE"
```

### Create Beta Group '내부'
```bash
curl -s -X POST "https://api.appstoreconnect.apple.com/v1/betaGroups" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "type": "betaGroups",
      "attributes": {
        "name": "내부",
        "isInternalGroup": true,
        "hasAccessToAllBuilds": true
      },
      "relationships": {
        "app": {
          "data": {"type": "apps", "id": "'$APP_ID'"}
        }
      }
    }
  }'
```

### Invite Tester
```bash
curl -s -X POST "https://api.appstoreconnect.apple.com/v1/betaTesters" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "type": "betaTesters",
      "attributes": {
        "email": "'$TESTER_EMAIL'",
        "firstName": "Tester",
        "lastName": "User"
      },
      "relationships": {
        "betaGroups": {
          "data": [{"type": "betaGroups", "id": "'$GROUP_ID'"}]
        }
      }
    }
  }'
```

## Troubleshooting

### "No signing certificate found"
```bash
# List available certificates
security find-identity -v -p codesigning
# If empty, create in Xcode: Settings → Accounts → Manage Certificates
```

### "Provisioning profile doesn't match"
```bash
# Use automatic signing
xcodebuild archive ... CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates
```

### "The bundle identifier is not available"
- Change the bundle ID in the project
- Or register the App ID in App Store Connect first

### "Unable to upload: authentication failed"
- Verify ASC_API_KEY_ID and ASC_API_ISSUER_ID
- Check .p8 key file exists at ASC_API_KEY_PATH
- For Apple ID method, regenerate app-specific password
