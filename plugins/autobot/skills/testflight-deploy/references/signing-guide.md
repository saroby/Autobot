# Code Signing & Upload Guide

## Authentication Methods

### Method 1: App Store Connect API Key (Recommended)

Set these environment variables:
```bash
export ASC_API_KEY_ID="XXXXXXXXXX"        # Key ID from App Store Connect
export ASC_API_ISSUER_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # Issuer ID
export ASC_API_KEY_PATH="~/.appstoreconnect/private_keys/AuthKey_XXXXXXXXXX.p8"
```

Export + Upload (한 단계):
```bash
xcodebuild -exportArchive \
  -archivePath "build/AppName.xcarchive" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath "build/export" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$ASC_API_KEY_PATH" \
  -authenticationKeyID "$ASC_API_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_API_ISSUER_ID"
```

ExportOptions.plist에 `destination: upload`을 설정하면 IPA 생성과 업로드가 동시에 수행된다.

### Method 2: Xcode 로그인 계정 사용

Xcode Settings → Accounts에 Apple ID가 로그인되어 있으면 인증 파라미터 없이도 업로드 가능:
```bash
xcodebuild -exportArchive \
  -archivePath "build/AppName.xcarchive" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath "build/export" \
  -allowProvisioningUpdates
```

### Method 3: Apple Transporter (Manual Fallback)

자동 업로드가 실패하면:
```
1. Mac App Store에서 "Transporter" 앱 설치 (무료)
2. Transporter에 IPA 파일 드래그 앤 드롭
3. 업로드 클릭
```

또는 Xcode Organizer:
```
1. Xcode → Window → Organizer
2. 아카이브 선택 → Distribute App
3. TestFlight & App Store → Upload
```

> **참고**: `xcrun altool`은 deprecated 되었다. 위 방법들이 공식 대체 방법이다.

## ExportOptions.plist

### For TestFlight (App Store Connect)
```xml
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
```

> `destination: upload` — export와 업로드를 한 단계로 수행
> `manageAppVersionAndBuildNumber: true` — 빌드 번호 충돌 자동 해결
> `testFlightInternalTestingOnly: true` — 내부 테스트 전용 (외부 배포 방지)

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
- Verify ASC_API_KEY_ID and ASC_API_ISSUER_ID values
- Check .p8 key file exists at ASC_API_KEY_PATH: `ls -la "$ASC_API_KEY_PATH"`
- Verify key has "App Manager" or "Admin" role in App Store Connect → Integrations
- For Xcode account method, re-authenticate in Xcode Settings → Accounts
