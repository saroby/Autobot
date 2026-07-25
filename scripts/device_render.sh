#!/usr/bin/env bash
# device_render.sh — render a reproduced SwiftUI screen in a simulator.
#
# `/autobot:clone` may not claim a reproduction without putting it next to the
# original (SKILL rule 4), which needs a screenshot of the generated code. The
# generated files are loose views with no app target, so this builds the smallest
# thing that can host one: swiftc straight to a .app bundle, no project file, no
# xcodegen, no new dependency.
#
#   device_render.sh <sources-dir> <RootView> <simulator> <out.png>
#
# <simulator> is a name or udid. Use one whose LOGICAL size matches the device
# the measurements came from — the numbers are points from that screen, so a
# different size renders a different layout. Create one if needed:
#   xcrun simctl create clone-probe com.apple.CoreSimulator.SimDeviceType.iPhone-12-mini <runtime>
#
# <RootView> must take no required arguments (the SKILL's generated views expose
# state through defaulted initializers, so this holds).
set -euo pipefail

BUNDLE_ID="autobot.clone.preview"
DEPLOY_TARGET="${CLONE_IOS_TARGET:-17.0}"
# Global, not a local of main(): the EXIT trap fires after main returns, and
# under `set -u` a local by then is an unbound-variable error on a good run.
WORK=""
trap '[[ -n "$WORK" ]] && rm -rf "$WORK"' EXIT

main() {
  local src="${1:-}" view="${2:-}" sim="${3:-}" out="${4:-}"
  if [[ -z "$src" || -z "$view" || -z "$sim" || -z "$out" ]]; then
    echo "ERROR: usage: device_render.sh <sources-dir> <RootView> <simulator> <out.png>" >&2
    return 1
  fi
  if [[ ! -d "$src" ]]; then
    echo "ERROR: no such sources directory '$src'" >&2
    return 1
  fi
  local swifts=()
  while IFS= read -r f; do swifts+=("$f"); done < <(find "$src" -name '*.swift' | sort)
  if [[ "${#swifts[@]}" -eq 0 ]]; then
    echo "ERROR: no .swift files under '$src' — generate the views first (SKILL Step 5)" >&2
    return 1
  fi

  local work app
  WORK="$(mktemp -d -t device_render)"
  work="$WORK"
  app="$work/ClonePreview.app"
  mkdir -p "$app"

  # Named Entry.swift, not main.swift: a file called main.swift is top-level code
  # and @main is then rejected.
  cat > "$work/Entry.swift" <<EOF
import SwiftUI

@main
struct ClonePreviewApp: App {
    var body: some Scene { WindowGroup { $view() } }
}
EOF
  cat > "$app/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>ClonePreview</string>
<key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
<key>CFBundleName</key><string>ClonePreview</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSRequiresIPhoneOS</key><true/>
<key>MinimumOSVersion</key><string>$DEPLOY_TARGET</string>
<key>UILaunchScreen</key><dict/>
<key>UISupportedInterfaceOrientations</key><array><string>UIInterfaceOrientationPortrait</string></array>
</dict></plist>
EOF

  local sdk arch
  sdk="$(xcrun --sdk iphonesimulator --show-sdk-path)"
  arch="$(uname -m)"; [[ "$arch" == "arm64" ]] || arch="x86_64"
  if ! xcrun swiftc -sdk "$sdk" -target "$arch-apple-ios$DEPLOY_TARGET-simulator" \
       -parse-as-library -o "$app/ClonePreview" "$work/Entry.swift" "${swifts[@]}" 2>&1 \
       | grep -v 'warning: using sysroot'; then
    :  # grep exits 1 when the compiler printed nothing — that is the success case
  fi
  if [[ ! -x "$app/ClonePreview" ]]; then
    echo "ERROR: swiftc failed — fix the generated views above before comparing" >&2
    return 1
  fi

  xcrun simctl boot "$sim" 2>/dev/null || true
  if ! xcrun simctl bootstatus "$sim" -b >/dev/null 2>&1; then
    echo "ERROR: simulator '$sim' did not boot — check 'xcrun simctl list devices'" >&2
    return 1
  fi
  xcrun simctl uninstall "$sim" "$BUNDLE_ID" >/dev/null 2>&1 || true
  if ! xcrun simctl install "$sim" "$app" >/dev/null; then
    echo "ERROR: install failed on '$sim'" >&2
    return 1
  fi
  xcrun simctl launch "$sim" "$BUNDLE_ID" >/dev/null
  sleep "${CLONE_RENDER_SETTLE:-3}"   # first frame + any animation
  mkdir -p "$(dirname "$out")"
  if ! xcrun simctl io "$sim" screenshot "$out" >/dev/null 2>&1; then
    echo "ERROR: screenshot failed on '$sim'" >&2
    return 1
  fi
  echo "OK: rendered $view -> $out"
}

main "$@"
