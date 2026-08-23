#!/usr/bin/env bash
# device_install.sh — put the reproduction on the connected iPhone.
#
#   device_install.sh <sources-dir> <RootView> <udid> [bundle-id]
#
# `device_render.sh` builds the same sources with `swiftc` straight to a .app,
# which is all a simulator needs. A phone needs a signed build, and signing
# needs a development provisioning profile for this device — only Xcode can
# mint one, so this path goes through a generated project and `xcodebuild
# -allowProvisioningUpdates` rather than swiftc.
set -euo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLONE_ROOT="${CLONE_ROOT:-.autobot/clone}"
APP_NAME="${CLONE_DEVICE_APP_NAME:-CloneApp}"
DEPLOY_TARGET="${CLONE_IOS_TARGET:-17.0}"

main() {
  local src="${1:-}" view="${2:-}" udid="${3:-}" bundle_id="${4:-${CLONE_DEVICE_BUNDLE_ID:-}}"
  if [[ -z "$src" || -z "$view" || -z "$udid" ]]; then
    echo "ERROR: usage: device_install.sh <sources-dir> <RootView> <udid> [bundle-id]" >&2
    return 1
  fi
  if [[ ! -d "$src" ]]; then
    echo "ERROR: no such sources directory '$src'" >&2
    return 1
  fi
  # The same team doctor resolves and reports. Picking a different one here —
  # the first codesigning identity in the keychain, say — signs with a team the
  # rest of the run never validated.
  local team="${CLONE_SIGNING_TEAM:-${DEVELOPMENT_TEAM:-${TEAM_ID:-}}}"
  if [[ -z "$team" && -r "$HOME/.autobot/.env" ]]; then
    team="$(sed -nE 's/^[[:space:]]*(DEVELOPMENT_TEAM|TEAM_ID)=["'"'"']?([A-Za-z0-9]{10}).*/\2/p' \
            "$HOME/.autobot/.env" | head -1)"
  fi
  if [[ -z "$team" ]]; then
    echo "ERROR: no Apple development team — run 'device_wda.sh doctor' and set CLONE_SIGNING_TEAM" >&2
    return 1
  fi
  bundle_id="${bundle_id:-com.axi.clone.$(printf '%s' "$view" | tr '[:upper:]' '[:lower:]')}"
  # Home-screen name = the original app's, as `observe` resolved it on the
  # device (target.json). Only the display name; the bundle id above stays the
  # clone's own so both can sit on one phone.
  local display="${CLONE_APP_DISPLAY_NAME:-}"
  if [[ -z "$display" && -f "$CLONE_ROOT/target.json" ]]; then
    display="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("name",""))' \
               "$CLONE_ROOT/target.json" 2>/dev/null || true)"
  fi
  [[ -n "$display" ]] || echo "WARN: no original app name in $CLONE_ROOT/target.json — the clone keeps the name $APP_NAME (set CLONE_APP_DISPLAY_NAME)" >&2

  local project="$CLONE_ROOT/device-app" stage="$CLONE_ROOT/device-app/$APP_NAME"
  rm -rf "$stage"
  mkdir -p "$stage"
  python3 "$_HERE/clone_device_project.py" "$project" --name "$APP_NAME" \
    --bundle-id "$bundle_id" --team "$team" --deployment-target "$DEPLOY_TARGET" \
    ${display:+--display-name "$display"}

  cp "$src"/*.swift "$stage/"
  # The capture crops travel with the app. The synchronized group makes every
  # file under the folder a build input, so they land in the bundle as-is and
  # cloneImage() finds them by name.
  local crops="${CLONE_ASSET_DIR:-$CLONE_ROOT/assets/crops}"
  if [[ -d "$crops" ]]; then
    mkdir -p "$stage/Crops"
    cp "$crops"/*.png "$stage/Crops/" 2>/dev/null || true
  fi
  cat > "$stage/CloneAppEntry.swift" <<EOF
import SwiftUI

@main
struct CloneAppEntry: App {
    var body: some Scene { WindowGroup { $view() } }
}
EOF

  local derived="$CLONE_ROOT/device-app/DerivedData"
  echo "INFO: building $APP_NAME for $udid (team $team, bundle $bundle_id)"
  if ! xcodebuild -project "$project/$APP_NAME.xcodeproj" -scheme "$APP_NAME" \
        -configuration Debug -destination "id=$udid" -derivedDataPath "$derived" \
        -allowProvisioningUpdates build > "$CLONE_ROOT/device-app/build.log" 2>&1; then
    echo "ERROR: the device build failed — last errors:" >&2
    grep -E "error:|Signing for|Provisioning" "$CLONE_ROOT/device-app/build.log" | tail -12 >&2
    return 1
  fi
  local app="$derived/Build/Products/Debug-iphoneos/$APP_NAME.app"
  if [[ ! -d "$app" ]]; then
    echo "ERROR: build reported success but $app is missing" >&2
    return 1
  fi

  echo "INFO: installing $app"
  if ! xcrun devicectl device install app --device "$udid" "$app" >/dev/null 2>&1; then
    echo "ERROR: install failed — is the device unlocked and trusted?" >&2
    return 1
  fi
  if ! xcrun devicectl device process launch --device "$udid" "$bundle_id" >/dev/null 2>&1; then
    echo "WARN: installed, but the launch request failed — open it on the device" >&2
  fi
  echo "OK: $bundle_id is installed on $udid showing $view"
}

main "$@"
