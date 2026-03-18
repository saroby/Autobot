---
name: autobot-ios-scaffold
description: Use when creating a new Xcode project from scratch, setting up iOS 26+ project structure, configuring targets and schemes, or when the "/autobot:build" command needs to scaffold a project.
---

# iOS Project Scaffolding

Create iOS 26+ Xcode projects programmatically for Autobot builds.

## Preferred Method: XcodeGen

If `xcodegen` is installed, use it for reliable project generation:

```bash
# Check availability
which xcodegen

# If available, create project.yml and generate
xcodegen generate
```

Refer to `references/project-templates.md` for the project.yml template.

## Fallback Method: Built-in pbxproj Generator

xcodegen이 없으면 `generate-pbxproj.py`가 유효한 `.xcodeproj/project.pbxproj`를 직접 생성한다.
`create-xcode-project.sh`가 자동으로 fallback을 수행하므로 별도 조치 불필요.

- **Folder Reference** (`PBXFileSystemSynchronizedRootGroup`) 사용 — 파일시스템과 Xcode 자동 동기화
- 개별 파일 등록 불필요 — 새 파일 추가 시 pbxproj 재생성 불필요
- pbxproj 머지 충돌 대폭 감소
- App 타겟 + Test 타겟 + xcscheme 생성
- Debug/Release 빌드 설정 포함
- `objectVersion = 77` (Xcode 26.3+ 필수)

## Project Creation

`scripts/create-xcode-project.sh`를 사용 (xcodegen/fallback을 자동 선택):

```bash
# Autobot 빌드에서 사용 (Phase 0에서 이미 프로젝트 디렉토리를 생성한 경우):
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "AppName" \
  --bundle-id "com.saroby.appname" \
  --project-dir "." \
  --deployment-target "26.0"

# 독립 실행 (새 프로젝트 디렉토리를 자동 생성):
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "AppName" \
  --bundle-id "com.saroby.appname" \
  --deployment-target "26.0"
```

`--project-dir .`를 전달하면 현재 디렉토리를 프로젝트 루트로 사용하고, `AppName/` 서브디렉토리를 소스 그룹으로 생성한다. 생략하면 `AppName/` 디렉토리를 새로 만들어 그 안에 `AppName/AppName/` 소스 구조를 생성한다.

## Project Configuration Essentials

### Info.plist Keys
- `CFBundleDisplayName`: App display name
- `UILaunchScreen`: Empty dict (for SwiftUI apps)
- `UISupportedInterfaceOrientations`: Portrait + Landscape

### Build Settings
- `SWIFT_VERSION`: 6.0
- `IPHONEOS_DEPLOYMENT_TARGET`: 26.0
- `SWIFT_STRICT_CONCURRENCY`: complete
- `ENABLE_USER_SCRIPT_SANDBOXING`: YES
- `CODE_SIGN_ENTITLEMENTS`: `AppName/AppName.entitlements`
- (조건부) `INFOPLIST_KEY_API_BASE_URL`: `$(API_BASE_URL)` — xcconfig에서 주입
- (조건부) Debug 빌드: `Debug.xcconfig` 적용
- (조건부) Release 빌드: `Release.xcconfig` 적용

### Asset Catalog
- AppIcon (1024x1024 single icon for iOS 26+)
- AccentColor (brand color)

### Required Files (자동 생성)
- `.gitignore` — Xcode/SPM 빌드 아티팩트 제외
- `PrivacyInfo.xcprivacy` — App Store 필수 (2024+). 기본 FileTimestamp 포함, architect가 추가 카테고리 지정
- `AppName.entitlements` — 빈 틀. architect가 iCloud/Push 등 capability 지정 시 Phase 5에서 채움
- Info.plist 권한 — `GENERATE_INFOPLIST_FILE=YES` 사용, `INFOPLIST_KEY_*` 빌드 설정으로 주입
- (조건부) `Debug.xcconfig` — `backend_required == true`일 때 생성. `API_BASE_URL = http:/$()/localhost:8080`
- (조건부) `Release.xcconfig` — `backend_required == true`일 때 생성. `API_BASE_URL = https:/$()/$(PRODUCTION_HOST)`
- (조건부) `.gitignore`에 `backend/.env` 라인 추가 — `backend_required == true`일 때

### Backend-Aware Scaffold (backend_required == true)

architecture.md에 `Backend Requirements: Required: true`가 있으면 추가로:

1. `Debug.xcconfig`, `Release.xcconfig` 생성
2. `.gitignore`에 `backend/.env` 추가
3. 빌드 설정에 xcconfig 참조 + `API_BASE_URL` Info.plist 키 추가

이 작업은 Phase 3에서 scaffold 시 수행한다. backend-engineer가 root `.gitignore`를 수정할 필요가 없도록 미리 준비한다.

## Additional Resources

- **`references/project-templates.md`** — XcodeGen project.yml templates
- **`scripts/create-xcode-project.sh`** — 프로젝트 생성 (xcodegen 우선, fallback으로 pbxproj 직접 생성)
- **`scripts/generate-pbxproj.py`** — xcodegen 없이 .xcodeproj 생성하는 Python 스크립트
