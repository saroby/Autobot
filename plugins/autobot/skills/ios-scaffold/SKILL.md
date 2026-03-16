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

## Fallback Method: Swift Package with Xcode Project

If xcodegen is not available:

```bash
# Create project structure manually
mkdir -p AppName/App AppName/Models AppName/Views/Screens AppName/Views/Components \
         AppName/ViewModels AppName/Services AppName/Utilities AppName/Assets.xcassets

# Create Package.swift for dependency management (if needed)
# Then open in Xcode to generate .xcodeproj
```

## Manual Xcode Project Creation

Use the `scripts/create-xcode-project.sh` script at `$CLAUDE_PLUGIN_ROOT/skills/ios-scaffold/scripts/create-xcode-project.sh`:

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
- **`scripts/create-xcode-project.sh`** — Shell script for manual project creation
