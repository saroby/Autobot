#!/bin/bash
# Create an Xcode project programmatically without xcodegen
# Usage: create-xcode-project.sh --name AppName --bundle-id com.example.app --deployment-target 26.0
set -euo pipefail

# Parse arguments
APP_NAME=""
BUNDLE_ID=""
TEAM_ID="AUTO"
DEPLOYMENT_TARGET="26.0"

while [[ $# -gt 0 ]]; do
  case $1 in
    --name) APP_NAME="$2"; shift 2;;
    --bundle-id) BUNDLE_ID="$2"; shift 2;;
    --team-id) TEAM_ID="$2"; shift 2;;
    --deployment-target) DEPLOYMENT_TARGET="$2"; shift 2;;
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

if [ -z "$BUNDLE_ID" ]; then
  BUNDLE_ID="com.saroby.$(echo "$APP_NAME" | tr '[:upper:]' '[:lower:]')"
fi

PROJECT_DIR="${APP_NAME}"
SOURCES_DIR="${PROJECT_DIR}/${APP_NAME}"
TESTS_DIR="${PROJECT_DIR}/${APP_NAME}Tests"

echo "Creating Xcode project: ${APP_NAME}"
echo "Bundle ID: ${BUNDLE_ID}"
echo "Deployment Target: iOS ${DEPLOYMENT_TARGET}"

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

# Create App Entry Point
cat > "${SOURCES_DIR}/App/${APP_NAME}App.swift" << SWIFT_EOF
import SwiftUI
import SwiftData

@main
struct ${APP_NAME}App: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
SWIFT_EOF

# Create ContentView placeholder
cat > "${SOURCES_DIR}/Views/Screens/ContentView.swift" << SWIFT_EOF
import SwiftUI

struct ContentView: View {
    var body: some View {
        NavigationStack {
            Text("${APP_NAME}")
                .font(.largeTitle)
                .navigationTitle("Home")
        }
    }
}

#Preview {
    ContentView()
}
SWIFT_EOF

# Create Test file
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

# Check if xcodegen is available for project generation
if command -v xcodegen &>/dev/null; then
  # Create project.yml for xcodegen
  cat > "${PROJECT_DIR}/project.yml" << YAML_EOF
name: ${APP_NAME}
options:
  bundleIdPrefix: $(echo "$BUNDLE_ID" | sed "s/\\.${APP_NAME,,}$//")
  deploymentTarget:
    iOS: "${DEPLOYMENT_TARGET}"
  xcodeVersion: "16.0"

settings:
  base:
    SWIFT_VERSION: "6.0"
    SWIFT_STRICT_CONCURRENCY: complete
    MARKETING_VERSION: "1.0.0"
    CURRENT_PROJECT_VERSION: 1
    CODE_SIGN_STYLE: Automatic

targets:
  ${APP_NAME}:
    type: application
    platform: iOS
    sources:
      - path: ${APP_NAME}
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: ${BUNDLE_ID}
        GENERATE_INFOPLIST_FILE: YES
        INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES
        INFOPLIST_KEY_UILaunchScreen_Generation: YES

  ${APP_NAME}Tests:
    type: bundle.unit-test
    platform: iOS
    sources:
      - path: ${APP_NAME}Tests
    dependencies:
      - target: ${APP_NAME}
YAML_EOF

  cd "${PROJECT_DIR}" && xcodegen generate && cd ..
  echo "Xcode project generated with xcodegen"
else
  echo "xcodegen not found. Project directory created, but .xcodeproj needs to be created manually."
  echo "Install xcodegen: brew install xcodegen"
  echo "Or open the directory in Xcode: File → New → Project from existing files"
fi

echo "Project scaffolding complete: ${PROJECT_DIR}/"
