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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER_CACHE="${CLONE_RENDER_CACHE:-$SCRIPT_DIR/../.autobot/clone/render-cache}"
DEVICE_PROFILE="${CLONE_DEVICE_PROFILE:-$SCRIPT_DIR/../.autobot/clone/device-profile.json}"
# Global, not a local of main(): the EXIT trap fires after main returns, and
# under `set -u` a local by then is an unbound-variable error on a good run.
WORK=""
trap '[[ -n "$WORK" ]] && rm -rf "$WORK"' EXIT

select_simulator() {
  local profile="$1" work="$2"
  if [[ ! -f "$profile" ]]; then
    echo "ERROR: simulator 'auto' needs a device profile at '$profile' (or set CLONE_DEVICE_PROFILE)" >&2
    return 1
  fi

  local devices="$work/available-simulators.json"
  if ! xcrun simctl list devices available --json > "$devices"; then
    echo "ERROR: could not list available simulators for automatic selection" >&2
    return 1
  fi

  python3 - "$profile" "$devices" <<'PY'
import json
import re
import sys

profile_path, devices_path = sys.argv[1:]
try:
    with open(profile_path, encoding="utf-8") as handle:
        profile = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    print(f"ERROR: could not read device profile '{profile_path}': {exc}", file=sys.stderr)
    raise SystemExit(1)

marketing_name = profile.get("marketingName") if isinstance(profile, dict) else None
if not isinstance(marketing_name, str) or not marketing_name.strip():
    print(f"ERROR: device profile '{profile_path}' has no non-empty marketingName", file=sys.stderr)
    raise SystemExit(1)
marketing_name = marketing_name.strip()

try:
    with open(devices_path, encoding="utf-8") as handle:
        payload = json.load(handle)
except (OSError, json.JSONDecodeError) as exc:
    print(f"ERROR: invalid simulator list from simctl: {exc}", file=sys.stderr)
    raise SystemExit(1)

candidates = []
for runtime, devices in (payload.get("devices") or {}).items():
    version = tuple(int(part) for part in re.findall(r"\d+", runtime))
    for device in devices or []:
        if device.get("name") != marketing_name or device.get("isAvailable", True) is False:
            continue
        udid = device.get("udid")
        if not isinstance(udid, str) or not udid:
            continue
        booted = str(device.get("state", "")).lower() == "booted"
        last_booted = str(device.get("lastBootedAt") or "")
        candidates.append((booted, version, last_booted, udid))

if not candidates:
    print(f"ERROR: no available simulator matching marketingName '{marketing_name}'", file=sys.stderr)
    raise SystemExit(1)

candidates.sort(reverse=True)
print(candidates[0][3])
PY
}

capture_stable_frame() {
  local sim="$1" out="$2" work="$3"
  local attempts="${CLONE_RENDER_POLL_ATTEMPTS:-20}"
  local interval="${CLONE_RENDER_POLL_INTERVAL:-0.2}"
  if [[ ! "$attempts" =~ ^[0-9]+$ ]] || (( attempts < 2 )); then
    echo "ERROR: CLONE_RENDER_POLL_ATTEMPTS must be an integer of at least 2" >&2
    return 1
  fi
  if [[ ! "$interval" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "ERROR: CLONE_RENDER_POLL_INTERVAL must be a non-negative number" >&2
    return 1
  fi

  local attempt previous="" current
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    current="$work/frame-$attempt.png"
    if ! xcrun simctl io "$sim" screenshot "$current" >/dev/null 2>&1; then
      echo "ERROR: screenshot failed on '$sim'" >&2
      return 1
    fi
    if [[ -n "$previous" ]] && cmp -s "$previous" "$current"; then
      cp "$current" "$out"
      echo "INFO: frame stable after $attempt captures"
      return 0
    fi
    previous="$current"
    if (( attempt < attempts )); then
      sleep "$interval"
    fi
  done
  echo "ERROR: simulator '$sim' did not produce two identical frames after $attempts captures; set CLONE_RENDER_SETTLE to use the legacy fixed wait" >&2
  return 1
}

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
  local swifts=() relatives=()
  local relative
  while IFS= read -r relative; do
    relative="${relative#./}"
    relatives+=("$relative")
    swifts+=("$src/$relative")
  done < <(cd "$src" && find . -name '*.swift' | LC_ALL=C sort)
  if [[ "${#swifts[@]}" -eq 0 ]]; then
    echo "ERROR: no .swift files under '$src' — generate the views first (SKILL Step 5)" >&2
    return 1
  fi

  local work app build_app
  WORK="$(mktemp -d -t device_render)"
  work="$WORK"
  build_app="$work/ClonePreview.app"

  if [[ "$sim" == "auto" ]]; then
    if ! sim="$(select_simulator "$DEVICE_PROFILE" "$work")"; then
      return 1
    fi
    echo "INFO: selected simulator $sim from $DEVICE_PROFILE"
  fi

  local sdk arch
  sdk="$(xcrun --sdk iphonesimulator --show-sdk-path)"
  arch="$(uname -m)"; [[ "$arch" == "arm64" ]] || arch="x86_64"

  local cache_key source_hash index
  cache_key="$({
    printf 'renderer=2\nroot=%s\nsdk=%s\ndeployment=%s\narch=%s\n' \
      "$view" "$sdk" "$DEPLOY_TARGET" "$arch"
    for ((index = 0; index < ${#swifts[@]}; index++)); do
      source_hash="$(shasum -a 256 < "${swifts[$index]}" | awk '{print $1}')"
      printf 'source=%s:%s\n' "${relatives[$index]}" "$source_hash"
    done
  } | shasum -a 256 | awk '{print $1}')"
  local cache_entry="$RENDER_CACHE/$cache_key"
  local cache_app="$cache_entry/ClonePreview.app"
  mkdir -p "$RENDER_CACHE"

  if [[ -f "$cache_entry/.complete" && -x "$cache_app/ClonePreview" ]]; then
    app="$cache_app"
    echo "INFO: render cache hit $cache_key"
  else
    echo "INFO: render cache miss $cache_key"
    mkdir -p "$build_app"

    # Named Entry.swift, not main.swift: a file called main.swift is top-level code
    # and @main is then rejected.
    cat > "$work/Entry.swift" <<EOF
import SwiftUI

@main
struct ClonePreviewApp: App {
    var body: some Scene { WindowGroup { $view() } }
}
EOF
    cat > "$build_app/Info.plist" <<EOF
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

    if ! xcrun swiftc -sdk "$sdk" -target "$arch-apple-ios$DEPLOY_TARGET-simulator" \
         -parse-as-library -o "$build_app/ClonePreview" "$work/Entry.swift" "${swifts[@]}" 2>&1 \
         | grep -v 'warning: using sysroot'; then
      :  # grep exits 1 when the compiler printed nothing — that is the success case
    fi
    if [[ ! -x "$build_app/ClonePreview" ]]; then
      echo "ERROR: swiftc failed — fix the generated views above before comparing" >&2
      return 1
    fi

    if mkdir "$cache_entry" 2>/dev/null; then
      if ! cp -R "$build_app" "$cache_app"; then
        rm -rf "$cache_entry"
        echo "ERROR: could not populate render cache '$cache_entry'" >&2
        return 1
      fi
      : > "$cache_entry/.complete"
    else
      # Another renderer may have compiled the same key concurrently. Wait only
      # for its atomic completion marker; never install a partially copied app.
      local wait_count
      for ((wait_count = 0; wait_count < 50; wait_count++)); do
        [[ -f "$cache_entry/.complete" && -x "$cache_app/ClonePreview" ]] && break
        sleep 0.1
      done
      if [[ ! -f "$cache_entry/.complete" || ! -x "$cache_app/ClonePreview" ]]; then
        echo "ERROR: render cache entry '$cache_entry' is incomplete" >&2
        return 1
      fi
    fi
    app="$cache_app"
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
  mkdir -p "$(dirname "$out")"
  if [[ "${CLONE_RENDER_SETTLE+x}" == "x" ]]; then
    sleep "$CLONE_RENDER_SETTLE"
    if ! xcrun simctl io "$sim" screenshot "$out" >/dev/null 2>&1; then
      echo "ERROR: screenshot failed on '$sim'" >&2
      return 1
    fi
  else
    capture_stable_frame "$sim" "$out" "$work"
  fi
  echo "OK: rendered $view -> $out"
}

main "$@"
