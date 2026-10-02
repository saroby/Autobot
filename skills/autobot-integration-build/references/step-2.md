## Step 2: Platform Requirements

architecture.md에 정의된 플랫폼 요구사항을 프로젝트에 반영한다. **빌드 전에 수행.**

### Privacy Manifest

`<AppName>/PrivacyInfo.xcprivacy`를 `.autobot/architecture.md`의 `Privacy API Categories`와 비교하여 누락 항목 추가.

### Entitlements

architecture.md의 `Entitlements` 섹션을 `<AppName>/<AppName>.entitlements`에 반영:

| Capability | Entitlement Key |
|-----------|----------------|
| iCloud | `com.apple.developer.icloud-container-identifiers`, `com.apple.developer.icloud-services` |
| Push | `aps-environment` |
| HealthKit | `com.apple.developer.healthkit` |

### Info.plist 권한

architecture.md의 `Required Permissions`를 빌드 설정에 반영:
- xcodegen: `project.yml`의 `INFOPLIST_KEY_*` 설정
- pbxproj: build settings에 직접 추가
- 예: `INFOPLIST_KEY_NSCameraUsageDescription = "카메라 설명"`

> **Export Compliance contract**: `INFOPLIST_KEY_ITSAppUsesNonExemptEncryption` 는 scaffold 의 두 generator 가 이미 `NO` 로 emit 한다 (CONVENTIONS.md "iOS project content contract"). 권한을 추가할 때 이 키를 제거하지 말 것 — 누락되면 archive 단계에서 차단된다.

### SPM Dependencies

architecture.md의 `Dependencies` 섹션이 `N/A`가 아닐 때:

1. xcodegen: `project.yml`에 `packages:` + 타겟 `dependencies:` 추가 후 `xcodegen generate`
2. pbxproj: `xcodebuild -resolvePackageDependencies`
3. 빌드 전 패키지 해결:
   ```bash
   xcodebuild -project *.xcodeproj -scheme <scheme> -resolvePackageDependencies 2>&1 | tail -10
   ```
