# Xcode Project Templates

## XcodeGen project.yml Template (Folder Reference)

```yaml
name: ${APP_NAME}
options:
  bundleIdPrefix: com.axi
  deploymentTarget:
    iOS: "26.0"
  xcodeVersion: "26.3"
  useBaseInternationalization: true

settings:
  base:
    SWIFT_VERSION: "6.0"
    SWIFT_STRICT_CONCURRENCY: complete
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: 1
    DEVELOPMENT_TEAM: ""
    CODE_SIGN_STYLE: Automatic

packages:
  ${DESIGN_SYSTEM_MODULE}:
    path: Packages/${DESIGN_SYSTEM_MODULE}

targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: ${APP_NAME}
    dependencies:
      - package: ${DESIGN_SYSTEM_MODULE}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.axi.${APP_NAME_LOWER}
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES
        INFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPad: "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone: "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        CODE_SIGN_ENTITLEMENTS: ${APP_NAME}/${APP_NAME}.entitlements

  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
    dependencies:
      - target: ${APP_NAME}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.axi.${APP_NAME_LOWER}.tests
        TEST_HOST: "$(BUILT_PRODUCTS_DIR)/${APP_NAME}.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/${APP_NAME}"
        BUNDLE_LOADER: "$(TEST_HOST)"
```

> **Group sources (default, no `type: folder`).** xcodegen 2.45.4 + Xcode 26.5 의
> `type: folder` (PBXFileSystemSynchronizedRootGroup) 형식은 Solos / Murmur 빌드에서
> `<App>.app/<App>` 바이너리가 디렉토리로 빌드되는 회귀를 일으켰다. 그룹 모드는
> 신규 파일 추가 시 `xcodegen generate` 재실행이 필요하지만 — Autobot 오케스트레이터가
> 각 phase 경계에서 어차피 재생성하므로 자동 동기화의 이점은 미미하고, 빌드 신뢰성이 더 중요.

## Minimal App Entry Point

```swift
import SwiftUI
import SwiftData

@main
struct ${APP_NAME}App: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .modelContainer(for: [/* Models here */])
    }
}
```

## Design System Local Package

Phase 3 scaffold 가 자동으로 생성하는 in-tree 로컬 패키지. 모듈 이름은 architect 가 `architecture.json.designSystemModule` 로 결정한다 (관례: `<AppName>DS`).

````
Packages/
└── ${DESIGN_SYSTEM_MODULE}/
    ├── Package.swift
    └── Sources/
        └── ${DESIGN_SYSTEM_MODULE}/
            ├── Tokens/
            │   ├── Color.swift          # design-system agent 가 채움
            │   ├── Typography.swift     # design-system agent 가 채움
            │   ├── Spacing.swift        # design-system agent 가 채움
            │   └── Radius.swift         # design-system agent 가 채움
            └── Components/
                # design-system agent 가 채움 (PrimaryButton, Card, SectionHeader, EmptyStateView 등)
````

### Package.swift template

```swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "${DESIGN_SYSTEM_MODULE}",
    platforms: [.iOS(.v26)],
    products: [
        .library(name: "${DESIGN_SYSTEM_MODULE}", targets: ["${DESIGN_SYSTEM_MODULE}"]),
    ],
    targets: [
        .target(name: "${DESIGN_SYSTEM_MODULE}", path: "Sources/${DESIGN_SYSTEM_MODULE}"),
    ]
)
```

소비측에서는 `import ${DESIGN_SYSTEM_MODULE}` 만 하면 토큰과 컴포넌트를 모두 쓸 수 있다.

## Asset Catalog Structure

```
Assets.xcassets/
├── Contents.json
├── AccentColor.colorset/
│   └── Contents.json
└── AppIcon.appiconset/
    └── Contents.json
```

### Contents.json (root)
```json
{
  "info": { "version": 1, "author": "xcode" }
}
```

### AccentColor Contents.json
```json
{
  "colors": [
    {
      "idiom": "universal",
      "color": {
        "color-space": "srgb",
        "components": { "red": "0.200", "green": "0.400", "blue": "1.000", "alpha": "1.000" }
      }
    }
  ],
  "info": { "version": 1, "author": "xcode" }
}
```

### AppIcon Contents.json (iOS 26+ single size)
```json
{
  "images": [
    {
      "idiom": "universal",
      "platform": "ios",
      "size": "1024x1024"
    }
  ],
  "info": { "version": 1, "author": "xcode" }
}
```
