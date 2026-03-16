# Xcode Project Templates

## XcodeGen project.yml Template

```yaml
name: ${APP_NAME}
options:
  bundleIdPrefix: com.saroby
  deploymentTarget:
    iOS: "26.0"
  xcodeVersion: "16.0"
  generateEmptyDirectories: true

settings:
  base:
    SWIFT_VERSION: "6.0"
    SWIFT_STRICT_CONCURRENCY: complete
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: 1
    DEVELOPMENT_TEAM: ""
    CODE_SIGN_STYLE: Automatic

targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: ${APP_NAME}
        excludes:
          - "**/*.xcassets/Contents.json"
    settings:
      base:
        INFOPLIST_FILE: ${APP_NAME}/Info.plist
        PRODUCT_BUNDLE_IDENTIFIER: com.saroby.${APP_NAME_LOWER}
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES
        INFOPLIST_KEY_UIApplicationSupportsIndirectInputEvents: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPad: "UIInterfaceOrientationPortrait UIInterfaceOrientationPortraitUpsideDown UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone: "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight"
        CODE_SIGN_ENTITLEMENTS: ${APP_NAME}/${APP_NAME}.entitlements
    resources:
      - path: ${APP_NAME}/Assets.xcassets
      - path: ${APP_NAME}/PrivacyInfo.xcprivacy

  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
    dependencies:
      - target: ${APP_NAME}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.saroby.${APP_NAME_LOWER}.tests
        TEST_HOST: "$(BUILT_PRODUCTS_DIR)/${APP_NAME}.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/${APP_NAME}"
        BUNDLE_LOADER: "$(TEST_HOST)"
```

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
