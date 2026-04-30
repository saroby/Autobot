---
name: autobot-testflight-deploy
description: Use when deploying an iOS app to TestFlight, setting up code signing, archiving builds, uploading to App Store Connect, creating beta tester groups, or when the "/autobot:make" deployment phase is reached. Also use when troubleshooting archive failures, signing certificate issues, upload errors, or ASC authentication problems.
---

# TestFlight Deployment

iOS 앱을 아카이브하고 TestFlight에 배포하는 전체 파이프라인. `scripts/archive-upload.sh`가 Step 0~4를 자동화하며, 이 스킬은 워크플로우와 에러 대응 전략을 정의한다.

## Prerequisites Check

```bash
# 1. Xcode Command Line Tools
xcode-select -p

# 2. Signing identities (최소 1개 필요)
security find-identity -v -p codesigning

# 3. fastlane (앱 등록용 — 없으면 자동 설치 시도)
which fastlane || echo "fastlane not found — will install via brew"

# 4. App Store Connect credentials
echo "ASC_API_KEY_ID: ${ASC_API_KEY_ID:-not set}"
```

## Authentication Decision Tree

```
ASC_API_KEY_ID + ASC_API_ISSUER_ID + ASC_API_KEY_PATH 모두 설정됨?
├── Yes → API Key 인증 (권장, CI/CD 호환)
│   → xcodebuild -exportArchive에 -authenticationKey* 파라미터 추가
│   → fastlane produce에 --api_key_path 전달
└── No → Xcode 저장 계정 사용 (Fallback)
    ├── Xcode Settings → Accounts에 Apple ID 로그인됨?
    │   ├── Yes → 인증 파라미터 없이 xcodebuild 실행 (Xcode가 자동 처리)
    │   └── No → 자동 업로드 불가
    │       → 아카이브까지만 수행하고 수동 업로드 안내
    └── 수동 업로드: Xcode Organizer 또는 Apple Transporter 앱
```

## Deployment Pipeline

### Step 0: Register App on ASC

새로 만든 앱은 App Store Connect에 등록되어 있지 않다. 아카이브 전에 반드시 등록한다.

```bash
# fastlane produce (멱등 — 이미 존재하면 스킵)
PRODUCE_OUTPUT=$(fastlane produce create \
  --app_identifier "$BUNDLE_ID" \
  --app_name "$DISPLAY_NAME" \
  --language "ko" \
  --app_version "1.0.0" \
  --sku "$BUNDLE_ID" \
  --team_id "$DEVELOPMENT_TEAM" \
  --api_key_path fastlane_api_key.json \
  2>&1)
PRODUCE_EXIT=$?

if [ $PRODUCE_EXIT -ne 0 ]; then
  if echo "$PRODUCE_OUTPUT" | grep -qi "already.*exist\|already.*being used"; then
    echo "✓ App already registered on ASC, continuing..."
  else
    echo "✗ App registration failed:"
    echo "$PRODUCE_OUTPUT" | tail -5
    # 등록 실패를 기록하되 archive는 시도 (수동 등록 가능)
  fi
fi
```

> `|| echo`로 모든 에러를 무시하면 권한 부족이나 네트워크 실패도 조용히 넘어간다.
> 에러 메시지를 구분하여 "already exists"만 안전하게 건너뛴다.

### Step 1: Detect Team ID

```bash
# From Xcode project (자동 감지)
grep -m1 "DEVELOPMENT_TEAM" *.xcodeproj/project.pbxproj | grep -oE '[A-Z0-9]{10}'
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

### Step 3: Export + Upload (통합)

`ExportOptions.plist`에 `destination: upload`을 설정하면 IPA 생성과 업로드가 **한 단계**로 수행된다. `xcrun altool`은 deprecated — 이것이 공식 대체 방법이다.

```bash
# API Key 인증 시:
xcodebuild -exportArchive \
  -archivePath "build/AppName.xcarchive" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath "build/export" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$ASC_API_KEY_PATH" \
  -authenticationKeyID "$ASC_API_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_API_ISSUER_ID"

# Xcode 저장 계정 시 (-authentication* 파라미터 생략):
xcodebuild -exportArchive \
  -archivePath "build/AppName.xcarchive" \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath "build/export" \
  -allowProvisioningUpdates
```

ExportOptions.plist 핵심 설정:

| Key | Value | 이유 |
|-----|-------|------|
| `method` | `app-store-connect` | TestFlight 배포용 |
| `destination` | `upload` | export + upload 통합 |
| `signingStyle` | `automatic` | 수동 프로비저닝 방지 |
| `manageAppVersionAndBuildNumber` | `true` | 빌드 번호 충돌 자동 해결 |
| `testFlightInternalTestingOnly` | `true` | 내부 테스트 전용 (외부 배포 방지) |

### Step 4: Tester Group

ASC API를 사용하여 '내부' 테스터 그룹을 생성하고 사용자를 초대한다.

**흐름:**
1. ASC API Key로 **JWT 토큰 생성** (ES256, 20분 유효)
2. `POST /v1/betaGroups` — **Beta Group '내부' 생성** (`isInternalGroup: true`, `hasAccessToAllBuilds: true`)
3. `POST /v1/betaTesters` — **테스터 초대** (이메일 기반, 그룹에 자동 연결)

각 API 호출의 상세 파라미터와 JWT 생성 스크립트는 `references/signing-guide.md`의 "TestFlight Group Setup via API" 섹션 참조.

> **내부 테스터**: Apple Developer 계정의 App Store Connect 사용자. 최대 100명.
> 별도 심사 없이 빌드 처리 완료 즉시 테스트 가능.

## Post-Upload: ASC Processing

업로드 성공 ≠ TestFlight에서 바로 보임. Apple 서버가 바이너리를 처리하는 데 **5분~1시간** 걸린다.

- **upload_success: true** → 바이너리가 ASC에 전달됨. 처리 대기 중.
- TestFlight에서 안 보이면: App Store Connect → TestFlight → 빌드 탭에서 "Processing" 상태 확인
- 처리 완료 시 등록된 이메일로 알림이 온다
- deploy-status.json에 처리 상태를 기록:

```json
{
  "status": "uploaded",
  "upload_success": true,
  "note": "Build uploaded successfully. ASC processing may take 5-60 minutes before appearing in TestFlight."
}
```

> Phase 7(Retrospective)은 업로드 성공 시점에 진행한다. ASC 처리 완료를 기다리지 않는다.

## Error Handling

### 아카이브 실패

| 에러 | 원인 | 해결 |
|------|------|------|
| "No signing certificate found" | 코드 서명 인증서 없음 | Xcode → Settings → Accounts → Manage Certificates |
| "Provisioning profile doesn't match" | 프로파일 불일치 | `CODE_SIGN_STYLE=Automatic -allowProvisioningUpdates` 확인 |
| "BUILD FAILED" during archive | 코드 컴파일 에러 | Phase 5(quality-engineer)로 돌아가서 수정 |

### 업로드 실패

| 에러 | 원인 | 해결 |
|------|------|------|
| "Authentication failed" | ASC 인증 정보 오류 | `.env`의 ASC_API_KEY_ID, ISSUER_ID, KEY_PATH 확인 |
| "The bundle identifier is not available" | ASC에 앱 미등록 | Step 0 재실행 또는 번들 ID 변경 |
| "The App Name is already being used" | 앱 이름 충돌 | `--app_name`을 고유한 이름으로 변경 |
| 네트워크 타임아웃 | ASC 서버 문제 | `/autobot:resume 6`으로 재시도 |

### Fallback 전략 (자동 업로드 완전 실패 시)

1. 아카이브 경로를 사용자에게 보고 (`build/AppName.xcarchive`)
2. 수동 업로드 안내:
   - **Xcode Organizer**: Window → Organizer → 아카이브 선택 → Distribute App
   - **Apple Transporter**: Mac App Store에서 무료 설치 → IPA 드래그 앤 드롭
3. 실패 사유를 `.autobot/deploy-status.json`에 기록

## Automated Script

`scripts/archive-upload.sh`가 Step 0~3을 자동화한다:

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/testflight-deploy/scripts/archive-upload.sh" \
  --project-path "/path/to/project" \
  --scheme "AppName" \
  --bundle-id "com.axi.appname" \
  --display-name "앱 이름"
```

스크립트는 ASC 인증 정보 유무에 따라 API Key/Xcode 계정을 자동 선택하고, fastlane 미설치 시 자동 설치를 시도한다.

## Deploy Status Output

배포 완료 시 `.autobot/deploy-status.json`에 기록:

```json
{
  "status": "success",
  "archive_path": "build/AppName.xcarchive",
  "upload_success": true,
  "method": "api_key",
  "timestamp": "2026-03-18T12:00:00Z"
}
```

## Additional Resources

- **`references/signing-guide.md`** — 인증 방법별 상세 설정, ExportOptions.plist 전문, JWT 토큰 생성, 테스터 그룹 API
- **`scripts/archive-upload.sh`** — Step 0~3 자동화 스크립트 (인증 자동 감지, fastlane 자동 설치)
