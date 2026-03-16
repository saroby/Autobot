---
name: autobot-ios-scaffold
description: This skill should be used when creating a new Xcode project from scratch, setting up iOS 26+ project structure, configuring targets and schemes, or when the "/autobot:build" command needs to scaffold a project. Covers xcodegen, swift package init, and manual project creation.
version: 0.1.0
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

- 소스 디렉토리를 재귀 탐색하여 모든 `.swift` 파일을 프로젝트에 등록
- Asset catalog 자동 감지 및 등록
- App 타겟 + Test 타겟 + xcscheme 생성
- Debug/Release 빌드 설정 포함

## Project Creation

`scripts/create-xcode-project.sh`를 사용 (xcodegen/fallback을 자동 선택):

```bash
bash "$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh" \
  --name "AppName" \
  --bundle-id "com.saroby.appname" \
  --team-id "AUTO" \
  --deployment-target "26.0"
```

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

### Asset Catalog
- AppIcon (1024x1024 single icon for iOS 26+)
- AccentColor (brand color)

## Additional Resources

- **`references/project-templates.md`** — XcodeGen project.yml templates
- **`scripts/create-xcode-project.sh`** — 프로젝트 생성 (xcodegen 우선, fallback으로 pbxproj 직접 생성)
- **`scripts/generate-pbxproj.py`** — xcodegen 없이 .xcodeproj 생성하는 Python 스크립트
