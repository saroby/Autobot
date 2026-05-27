#!/bin/bash
# Create an Xcode project programmatically without xcodegen
# Usage: create-xcode-project.sh --name AppName --bundle-id com.example.app --deployment-target 26.0
set -euo pipefail

# Parse arguments
APP_NAME=""
BUNDLE_ID=""
TEAM_ID="${DEVELOPMENT_TEAM:-AUTO}"
DEPLOYMENT_TARGET="26.0"
PROJECT_DIR_OVERRIDE=""
BACKEND_REQUIRED="false"
DESIGN_SYSTEM_MODULE="${DESIGN_SYSTEM_MODULE:-}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --name) APP_NAME="$2"; shift 2;;
    --bundle-id) BUNDLE_ID="$2"; shift 2;;
    --team-id) TEAM_ID="$2"; shift 2;;
    --deployment-target) DEPLOYMENT_TARGET="$2"; shift 2;;
    --project-dir) PROJECT_DIR_OVERRIDE="$2"; shift 2;;
    --backend) BACKEND_REQUIRED="true"; shift;;
    --design-system-module) DESIGN_SYSTEM_MODULE="$2"; shift 2;;
    *) echo "Unknown option: $1"; exit 1;;
  esac
done

if [ -z "$APP_NAME" ]; then
  echo "Error: --name is required"
  exit 1
fi

# ── Sanitize APP_NAME to valid ASCII PascalCase identifier ──
# Remove all non-ASCII characters (Korean, emoji, etc.)
APP_NAME=$(echo "$APP_NAME" | LC_ALL=C sed 's/[^a-zA-Z0-9 _-]//g')
# Trim leading/trailing whitespace
APP_NAME=$(echo "$APP_NAME" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')
# Convert delimiter-separated words to PascalCase (capitalize first letter of each word, preserve rest)
APP_NAME=$(echo "$APP_NAME" | sed -E 's/[-_ ]+/ /g' | awk '{
  out=""
  for(i=1;i<=NF;i++) out=out toupper(substr($i,1,1)) substr($i,2)
  print out
}')
# Strip leading digits
APP_NAME=$(echo "$APP_NAME" | sed 's/^[0-9]*//')
# Enforce max length
APP_NAME="${APP_NAME:0:30}"
# Validate: must be ASCII PascalCase starting with uppercase letter
if [ -z "$APP_NAME" ] || ! echo "$APP_NAME" | grep -qE '^[A-Z][a-zA-Z0-9]+$'; then
  echo "Warning: '${APP_NAME}' is not a valid identifier. Using 'MyApp' as fallback."
  APP_NAME="MyApp"
fi

if [ -z "$DESIGN_SYSTEM_MODULE" ]; then
  DESIGN_SYSTEM_MODULE="${APP_NAME}DS"
fi
if ! [[ "$DESIGN_SYSTEM_MODULE" =~ ^[A-Z][A-Za-z0-9]+$ ]]; then
  echo "ERROR: --design-system-module must be PascalCase ASCII (got: $DESIGN_SYSTEM_MODULE)" >&2
  exit 2
fi

if [ -z "$BUNDLE_ID" ]; then
  BUNDLE_ID="com.axi.$(echo "$APP_NAME" | tr '[:upper:]' '[:lower:]')"
fi

# --project-dir가 지정되면 기존 디렉토리를 사용 (Phase 0에서 이미 생성됨)
# 지정되지 않으면 새 디렉토리를 생성 (독립 실행용)
if [ -n "$PROJECT_DIR_OVERRIDE" ]; then
  PROJECT_DIR="$PROJECT_DIR_OVERRIDE"
else
  PROJECT_DIR="${APP_NAME}"
fi
SOURCES_DIR="${PROJECT_DIR}/${APP_NAME}"
TESTS_DIR="${PROJECT_DIR}/${APP_NAME}Tests"

echo "Creating Xcode project: ${APP_NAME}"
echo "Bundle ID: ${BUNDLE_ID}"
echo "Deployment Target: iOS ${DEPLOYMENT_TARGET}"

mkdir -p "${PROJECT_DIR}"

# ── .gitignore (Xcode / Swift) ──
cat > "${PROJECT_DIR}/.gitignore" << 'GITIGNORE_EOF'
# Xcode
DerivedData/
build/
*.xcuserstate
*.xcscmblueprint
xcuserdata/
*.xccheckout
*.moved-aside
*.hmap
*.ipa
*.dSYM.zip
*.dSYM

# Swift Package Manager
.build/
.swiftpm/
Package.resolved

# CocoaPods (if used)
Pods/

# Autobot build artifacts
build/
*.xcarchive
ExportOptions.plist
fastlane_api_key.json

# Environment
.env
GITIGNORE_EOF

# ── Backend-aware scaffold (--backend 플래그가 전달된 경우) ──
if [ "$BACKEND_REQUIRED" = "true" ]; then
  # .gitignore에 backend/.env 추가
  echo "backend/.env" >> "${PROJECT_DIR}/.gitignore"

  # Debug.xcconfig (프로젝트 루트에 생성 — 소스 디렉토리에 넣으면 xcodegen folder reference에 포함됨)
  if [ ! -f "${PROJECT_DIR}/Debug.xcconfig" ]; then
    cat > "${PROJECT_DIR}/Debug.xcconfig" << 'XCCONFIG_EOF'
// Debug configuration
API_BASE_URL = http:/$()/localhost:8080
XCCONFIG_EOF
    echo "Generated: ${PROJECT_DIR}/Debug.xcconfig"
  fi

  # Release.xcconfig
  if [ ! -f "${PROJECT_DIR}/Release.xcconfig" ]; then
    cat > "${PROJECT_DIR}/Release.xcconfig" << 'XCCONFIG_EOF'
// Release configuration
API_BASE_URL = https:/$()/$(PRODUCTION_HOST)
XCCONFIG_EOF
    echo "Generated: ${PROJECT_DIR}/Release.xcconfig"
  fi
fi

# Create directory structure
mkdir -p "${SOURCES_DIR}/App"
mkdir -p "${SOURCES_DIR}/Models"
mkdir -p "${SOURCES_DIR}/Views/Screens"
mkdir -p "${SOURCES_DIR}/Views/Components"
mkdir -p "${SOURCES_DIR}/ViewModels"
mkdir -p "${SOURCES_DIR}/Services"
mkdir -p "${SOURCES_DIR}/Utilities"
mkdir -p "${SOURCES_DIR}/Assets.xcassets/AccentColor.colorset"
mkdir -p "${SOURCES_DIR}/Assets.xcassets/AppIcon.appiconset"
mkdir -p "${TESTS_DIR}"

# Create Asset Catalog
cat > "${SOURCES_DIR}/Assets.xcassets/Contents.json" << 'ASSET_EOF'
{
  "info": { "version": 1, "author": "xcode" }
}
ASSET_EOF

cat > "${SOURCES_DIR}/Assets.xcassets/AccentColor.colorset/Contents.json" << 'COLOR_EOF'
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
COLOR_EOF

cat > "${SOURCES_DIR}/Assets.xcassets/AppIcon.appiconset/Contents.json" << 'ICON_EOF'
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
ICON_EOF

# ── PrivacyInfo.xcprivacy (Required for App Store since 2024) ──
# 이미 존재하면 건너뛰기 — Phase 5 QE가 추가한 API 카테고리 보호
if [ ! -f "${SOURCES_DIR}/PrivacyInfo.xcprivacy" ]; then
cat > "${SOURCES_DIR}/PrivacyInfo.xcprivacy" << 'PRIVACY_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>NSPrivacyCollectedDataTypes</key>
	<array/>
	<key>NSPrivacyTracking</key>
	<false/>
	<key>NSPrivacyTrackingDomains</key>
	<array/>
	<key>NSPrivacyAccessedAPITypes</key>
	<array>
		<dict>
			<key>NSPrivacyAccessedAPIType</key>
			<string>NSPrivacyAccessedAPICategoryFileTimestamp</string>
			<key>NSPrivacyAccessedAPITypeReasons</key>
			<array>
				<string>C617.1</string>
			</array>
		</dict>
	</array>
</dict>
</plist>
PRIVACY_EOF
fi

# ── Entitlements (기본 틀 — architect가 기능별로 추가) ──
if [ ! -f "${SOURCES_DIR}/${APP_NAME}.entitlements" ]; then
cat > "${SOURCES_DIR}/${APP_NAME}.entitlements" << 'ENT_EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict/>
</plist>
ENT_EOF
fi

# Composition seam (AppEntry → CompositionRoot → RootView)
# Phase 4 ui-builder fills RootView body; quality-engineer wires real Services in CompositionRoot.
# These three files are the SEAM — `composition_seam_intact` gate (Gate 4→5) checks
# @main uniqueness here and ServiceStubs presence below.

if [ ! -f "${SOURCES_DIR}/App/${APP_NAME}App.swift" ]; then
cat > "${SOURCES_DIR}/App/${APP_NAME}App.swift" << SWIFT_EOF
// AppEntry — single @main for the app. Do not duplicate this annotation
// elsewhere; the composition seam check (Gate 4→5) enforces uniqueness.
import SwiftUI

@main
struct ${APP_NAME}App: App {
    var body: some Scene {
        WindowGroup {
            CompositionRoot()
        }
    }
}
SWIFT_EOF
fi

if [ ! -f "${SOURCES_DIR}/App/CompositionRoot.swift" ]; then
cat > "${SOURCES_DIR}/App/CompositionRoot.swift" << SWIFT_EOF
// CompositionRoot — assembles ModelContainer + real services for production.
// Only quality-engineer (Phase 5) edits the production wiring here.
// ui-builder (Phase 4) does NOT modify this file — fill RootView instead.
import SwiftUI
import SwiftData

struct CompositionRoot: View {
    // ui-builder may keep this as a thin wrapper over RootView.
    var body: some View {
        RootView()
            // Production ModelContainer is injected by quality-engineer in Phase 5:
            // .modelContainer(for: [/* models from Models/ */])
    }
}

#Preview {
    CompositionRoot()
}
SWIFT_EOF
fi

if [ ! -f "${SOURCES_DIR}/App/ServiceStubs.swift" ]; then
cat > "${SOURCES_DIR}/App/ServiceStubs.swift" << SWIFT_EOF
// ServiceStubs — Preview-only mock implementations of the protocols declared
// in Models/ServiceProtocols.swift. ui-builder (Phase 4) populates these so
// that #Preview blocks render without a real ModelContainer. Phase 5 keeps
// this file intact — production wiring goes into CompositionRoot.
//
// Do NOT delete this file. Gate 5→6 service_stubs_preserved check enforces it.
import Foundation

// Add per-protocol stubs as ui-builder produces ViewModels that need Previews.
SWIFT_EOF
fi

if [ ! -f "${SOURCES_DIR}/Views/Screens/RootView.swift" ]; then
cat > "${SOURCES_DIR}/Views/Screens/RootView.swift" << SWIFT_EOF
// RootView — the first screen the user sees. ui-builder fills the body
// following .autobot/architecture.md (## Screens / ## Navigation Structure).
// The .accessibilityIdentifier("autobot.root") below is REQUIRED:
// Gate 4→5 (intent_anchors_in_ui) and Phase 5 runtime_smoke both look for it.
import SwiftUI

struct RootView: View {
    var body: some View {
        NavigationStack {
            Text("${APP_NAME}")
                .font(.largeTitle)
                .navigationTitle("Home")
                .accessibilityIdentifier("autobot.primaryTitle")
        }
        .accessibilityIdentifier("autobot.root")
    }
}

#Preview {
    RootView()
}
SWIFT_EOF
fi

# Backwards compat — keep ContentView.swift creation but as a thin alias when
# legacy code or older agents reference it.
if [ ! -f "${SOURCES_DIR}/Views/Screens/ContentView.swift" ]; then
cat > "${SOURCES_DIR}/Views/Screens/ContentView.swift" << SWIFT_EOF
// Legacy alias — RootView is the canonical entrypoint. Kept so older
// references compile; ui-builder may remove this once unused.
import SwiftUI

typealias ContentView = RootView
SWIFT_EOF
fi

# Create Test file (이미 존재하면 건너뛰기)
if [ ! -f "${TESTS_DIR}/${APP_NAME}Tests.swift" ]; then
cat > "${TESTS_DIR}/${APP_NAME}Tests.swift" << SWIFT_EOF
import Testing
@testable import ${APP_NAME}

@Suite("${APP_NAME} Tests")
struct ${APP_NAME}Tests {
    @Test func appLaunches() {
        // Basic test placeholder
        #expect(true)
    }
}
SWIFT_EOF
fi

# ── Local Swift Package (Design System) ─────────────────────────────────────
PKG_DIR="${PROJECT_DIR}/Packages/${DESIGN_SYSTEM_MODULE}"
PKG_SRC="${PKG_DIR}/Sources/${DESIGN_SYSTEM_MODULE}"
mkdir -p "${PKG_SRC}/Tokens" "${PKG_SRC}/Components"

cat > "${PKG_DIR}/Package.swift" << PKG_EOF
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
PKG_EOF

# design-system 에이전트가 채울 때까지 컴파일 가능한 빈 스텁을 둔다.
# (이 파일은 design-system 에이전트가 덮어쓰며, gate 는 비어있지 않음을 검증한다.)
cat > "${PKG_SRC}/Tokens/Color.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import SwiftUI
public enum DSColors { public static let placeholder = Color.accentColor }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Typography.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import SwiftUI
public enum DSTypography { public static let body = Font.body }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Spacing.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import Foundation
public enum DSSpacing { public static let m: CGFloat = 16 }
STUB_EOF
cat > "${PKG_SRC}/Tokens/Radius.swift" << STUB_EOF
// Placeholder — design-system agent overwrites this.
import Foundation
public enum DSRadius { public static let m: CGFloat = 12 }
STUB_EOF

# Check if xcodegen is available for project generation
if command -v xcodegen &>/dev/null; then
  # Derive bundleIdPrefix safely with a fallback if BUNDLE_ID doesn't end with the lowercase app name
  APP_NAME_LOWER=$(echo "$APP_NAME" | tr '[:upper:]' '[:lower:]')
  BUNDLE_PREFIX="${BUNDLE_ID%.${APP_NAME_LOWER}}"
  if [ "$BUNDLE_PREFIX" = "$BUNDLE_ID" ] || [ -z "$BUNDLE_PREFIX" ]; then
    BUNDLE_PREFIX="com.axi"
  fi

  # Create project.yml for xcodegen (Folder Reference mode)
  cat > "${PROJECT_DIR}/project.yml" << YAML_EOF
name: ${APP_NAME}
options:
  bundleIdPrefix: ${BUNDLE_PREFIX}
  deploymentTarget:
    iOS: "${DEPLOYMENT_TARGET}"
  xcodeVersion: "26.3"
  useBaseInternationalization: true

settings:
  base:
    SWIFT_VERSION: "6.0"
    SWIFT_STRICT_CONCURRENCY: complete
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: 1
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
        type: folder
    dependencies:
      - package: ${DESIGN_SYSTEM_MODULE}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: ${BUNDLE_ID}
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_ITSAppUsesNonExemptEncryption: NO
        INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES
        CODE_SIGN_ENTITLEMENTS: ${APP_NAME}/${APP_NAME}.entitlements

  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
        type: folder
    dependencies:
      - target: ${APP_NAME}
YAML_EOF

  (cd "${PROJECT_DIR}" && xcodegen generate)
  echo "Xcode project generated with xcodegen"
else
  # Fallback: generate .xcodeproj using Python pbxproj generator
  echo "xcodegen not found. Generating .xcodeproj with built-in generator..."

  # Locate the Python generator script (relative to this script or via CLAUDE_PLUGIN_ROOT)
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  GENERATOR="${SCRIPT_DIR}/generate-pbxproj.py"

  if [ ! -f "$GENERATOR" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    GENERATOR="${CLAUDE_PLUGIN_ROOT}/skills/autobot-ios-scaffold/scripts/generate-pbxproj.py"
  fi

  if [ -f "$GENERATOR" ]; then
    python3 "$GENERATOR" \
      --name "$APP_NAME" \
      --bundle-id "$BUNDLE_ID" \
      --deployment-target "$DEPLOYMENT_TARGET" \
      --sources-dir "$SOURCES_DIR" \
      --design-system-module "$DESIGN_SYSTEM_MODULE" \
      ${TEAM_ID:+--team-id "$TEAM_ID"}
    echo "Xcode project generated with built-in generator"
  else
    echo "ERROR: Neither xcodegen nor generate-pbxproj.py found."
    echo "Install xcodegen: brew install xcodegen"
    exit 1
  fi
fi

echo "Project scaffolding complete: ${PROJECT_DIR}/"
