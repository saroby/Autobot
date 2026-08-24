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
# cwd-relative like every other clone script. The scripts run from wherever the
# plugin is installed (the repo, or ~/.claude/plugins/cache/...), but the clone
# lives in the USER'S project — a SCRIPT_DIR-relative default pointed into the
# plugin cache and failed `functional`/`polish` with "needs a device profile"
# while observe had just written one. Measured 2026-08-23.
CLONE_ROOT="${CLONE_ROOT:-.autobot/clone}"
RENDER_CACHE="${CLONE_RENDER_CACHE:-$CLONE_ROOT/render-cache}"
DEVICE_PROFILE="${CLONE_DEVICE_PROFILE:-$CLONE_ROOT/device-profile.json}"
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

# Match on the simulator's DEVICE TYPE, not its name. The logical size — the
# only thing that makes a render comparable to the measurements — comes from the
# type; the name is whatever the person who created it typed. This header's own
# instructions say `simctl create clone-probe ...iPhone-12-mini`, which produces
# a simulator named "clone-probe" that a name match can never select.
device_type_suffix = "." + marketing_name.replace(" ", "-")


def matches(device: dict) -> bool:
    if device.get("name") == marketing_name:
        return True
    identifier = device.get("deviceTypeIdentifier")
    return isinstance(identifier, str) and identifier.endswith(device_type_suffix)


candidates = []
for runtime, devices in (payload.get("devices") or {}).items():
    version = tuple(int(part) for part in re.findall(r"\d+", runtime))
    for device in devices or []:
        if not matches(device) or device.get("isAvailable", True) is False:
            continue
        udid = device.get("udid")
        if not isinstance(udid, str) or not udid:
            continue
        booted = str(device.get("state", "")).lower() == "booted"
        last_booted = str(device.get("lastBootedAt") or "")
        candidates.append((booted, version, last_booted, udid))

if not candidates:
    print(f"ERROR: no available simulator of device type '{marketing_name}' "
          f"(looked for a name match or a deviceTypeIdentifier ending in "
          f"'{device_type_suffix}'). Create one:\n"
          f"ERROR:   xcrun simctl create clone-probe "
          f"com.apple.CoreSimulator.SimDeviceType{device_type_suffix} <runtime>",
          file=sys.stderr)
    raise SystemExit(1)

candidates.sort(reverse=True)
print(candidates[0][3])
PY
}

capture_stable_frame() {
  local sim="$1" out="$2" work="$3" baseline="${4:-}"
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

  local attempt previous="" current settled=""
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    current="$work/frame-$attempt.png"
    if ! xcrun simctl io "$sim" screenshot "$current" >/dev/null 2>&1; then
      echo "ERROR: screenshot failed on '$sim'" >&2
      return 1
    fi
    if [[ -n "$previous" ]] && cmp -s "$previous" "$current"; then
      settled="$current"
      # A baseline is what was on screen just before this launch. The app is
      # relaunched in place now (one build hosts every root view), so "two
      # identical frames" is satisfied by the home screen while the app is
      # still coming up — and that frame would be filed as the reproduction.
      if [[ -z "$baseline" ]] || ! cmp -s "$baseline" "$current"; then
        cp "$current" "$out"
        echo "INFO: frame stable after $attempt captures"
        return 0
      fi
    fi
    previous="$current"
    if (( attempt < attempts )); then
      sleep "$interval"
    fi
  done
  if [[ -n "$settled" ]]; then
    # Settled, but on the pre-launch screen. Report it rather than failing: the
    # reproduction may legitimately look like what was behind it, and the
    # comparison that follows is the thing that can tell the difference.
    cp "$settled" "$out"
    echo "WARN: '$sim' settled on a frame identical to the pre-launch screen after $attempts captures — the app may not have come up" >&2
    return 0
  fi
  echo "ERROR: simulator '$sim' did not produce two identical frames after $attempts captures; set CLONE_RENDER_SETTLE to use the legacy fixed wait" >&2
  return 1
}

main() {
  # `resolve-simulator` lets a batch caller settle the simulator ONCE. Without
  # it, a missing simulator is reported per screen, as though each view were at
  # fault — the same "24 identical failures" the views.json pre-check exists to
  # avoid, and its advice ("fix the compiler diagnostics") names a cause that
  # is not there.
  if [[ "${1:-}" == "resolve-simulator" ]]; then
    WORK="$(mktemp -d -t device_render)"
    select_simulator "$DEVICE_PROFILE" "$WORK"
    return
  fi
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

  # The roots the one build can host. A batch caller (clone_run.sh) passes the
  # exact set from views.json; standalone callers get every `struct X: ... View`
  # in Sources/, which is right until a helper view needs an argument the
  # dispatcher cannot supply — that is what CLONE_ROOT_VIEWS is for.
  local roots
  if [[ -n "${CLONE_ROOT_VIEWS:-}" ]]; then
    roots="$(tr ' ' '\n' <<<"$CLONE_ROOT_VIEWS" | grep -v '^$' | LC_ALL=C sort -u)"
  else
    roots="$(grep -hoE '^[[:space:]]*(public[[:space:]]+)?struct[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*:[^{]*\bView\b' "${swifts[@]}" \
      | sed -E 's/.*struct[[:space:]]+([A-Za-z_][A-Za-z0-9_]*).*/\1/' | LC_ALL=C sort -u)"
  fi
  if ! grep -qx "$view" <<<"$roots"; then
    echo "ERROR: '$view' is not a View declared under '$src' — found: $(tr '\n' ' ' <<<"$roots")" >&2
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

  # Capture crops the reproduction draws for measured images. Their file names
  # are content hashes, so listing the names is enough to key the cache.
  local assets="${CLONE_ASSET_DIR:-$src/../assets/crops}"
  local asset_names=""
  if [[ -d "$assets" ]]; then
    asset_names="$(cd "$assets" && ls *.png 2>/dev/null | LC_ALL=C sort | tr '\n' ',')"
  fi

  local cache_key source_hash index
  cache_key="$({
    printf 'renderer=4\nsdk=%s\ndeployment=%s\narch=%s\nroots=%s\nassets=%s\n' \
      "$sdk" "$DEPLOY_TARGET" "$arch" "$(tr '\n' ',' <<<"$roots")" "$asset_names"
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
    #
    # The root view is picked at LAUNCH from CLONE_ROOT_VIEW, not baked in at
    # compile time. swiftc already compiles all of Sources/ for every render, so
    # baking the root in meant N screens cost N full compiles of the same files
    # (measured 2026-08-23: 31 mapped screens, one compile each, and every source
    # edit invalidated all 31). Dispatching makes it one compile per source edit.
    {
      echo 'import SwiftUI'
      echo ''
      echo '@main'
      echo 'struct ClonePreviewApp: App {'
      echo '    var body: some Scene { WindowGroup { ClonePreviewRoot() } }'
      echo '}'
      echo ''
      echo 'struct ClonePreviewRoot: View {'
      echo '    var body: some View {'
      echo '        switch ProcessInfo.processInfo.environment["CLONE_ROOT_VIEW"] ?? "" {'
      while IFS= read -r root; do
        [[ -n "$root" ]] || continue
        printf '        case "%s": AnyView(%s())\n' "$root" "$root"
      done <<<"$roots"
      echo '        case let other: AnyView(Text("no such root view: " + other).foregroundColor(.red))'
      echo '        }'
      echo '    }'
      echo '}'
    } > "$work/Entry.swift"
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
    if [[ -n "$asset_names" ]]; then
      cp "$assets"/*.png "$build_app/" || {
        echo "ERROR: could not copy capture crops from '$assets'" >&2
        return 1
      }
    fi

    if mkdir "$cache_entry" 2>/dev/null; then
      if ! cp -R "$build_app" "$cache_app"; then
        rm -rf "$cache_entry"
        echo "ERROR: could not populate render cache '$cache_entry'" >&2
        return 1
      fi
      : > "$cache_entry/.complete"
      # Bounded, because every entry now ships the capture crops with it (~4MB)
      # and every source edit mints a new one. This repo has a lesson where a
      # full disk surfaced as "Unable to resolve module dependency" and read as
      # a SwiftUI error; a polish loop is exactly the workload that gets there.
      local keep="${CLONE_RENDER_CACHE_KEEP:-12}" stale
      while IFS= read -r stale; do
        [[ -n "$stale" && "$stale" != "$cache_key" ]] && rm -rf "${RENDER_CACHE:?}/$stale"
      done < <(cd "$RENDER_CACHE" && ls -1td */ 2>/dev/null | tail -n "+$((keep + 1))" | tr -d /)
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
  # Reinstall only when the build changed. The install is the same bundle for
  # every screen now, so doing it per screen was pure latency.
  local marker installed=""
  marker="$RENDER_CACHE/.installed-$(printf '%s' "$sim" | tr -c 'A-Za-z0-9._-' '_')"
  [[ -f "$marker" ]] && installed="$(cat "$marker")"
  if [[ "$installed" != "$cache_key" ]] \
     || ! xcrun simctl get_app_container "$sim" "$BUNDLE_ID" >/dev/null 2>&1; then
    xcrun simctl uninstall "$sim" "$BUNDLE_ID" >/dev/null 2>&1 || true
    if ! xcrun simctl install "$sim" "$app" >/dev/null; then
      echo "ERROR: install failed on '$sim'" >&2
      return 1
    fi
    printf '%s' "$cache_key" > "$marker"
  fi
  xcrun simctl terminate "$sim" "$BUNDLE_ID" >/dev/null 2>&1 || true
  # Only the polling path needs to know what was on screen before the launch;
  # the legacy fixed wait takes exactly one screenshot by contract.
  local baseline=""
  if [[ "${CLONE_RENDER_SETTLE+x}" != "x" ]]; then
    baseline="$work/baseline.png"
    xcrun simctl io "$sim" screenshot "$baseline" >/dev/null 2>&1 || baseline=""
  fi
  SIMCTL_CHILD_CLONE_ROOT_VIEW="$view" \
    xcrun simctl launch --terminate-running-process "$sim" "$BUNDLE_ID" >/dev/null
  mkdir -p "$(dirname "$out")"
  if [[ "${CLONE_RENDER_SETTLE+x}" == "x" ]]; then
    sleep "$CLONE_RENDER_SETTLE"
    if ! xcrun simctl io "$sim" screenshot "$out" >/dev/null 2>&1; then
      echo "ERROR: screenshot failed on '$sim'" >&2
      return 1
    fi
  else
    capture_stable_frame "$sim" "$out" "$work" "$baseline"
  fi
  # Best-effort: dump the RENDERED accessibility tree so clone_structural_diff
  # can count missing elements mechanically (Step 6-4). Never fails the render.
  #
  # The tree also settles a question the pixels cannot: pixels going quiet is
  # not the app being up — the home screen is quiet too. Five screens in one
  # polish run were filed with a tree holding none of their elements, and the
  # structural diff read each as a whole screen of missing elements. If the tree
  # does not name this app, the capture was early: take both again.
  local tree_out="${out%.png}.tree.json" capture
  # 0 disables the re-capture — for callers with no real simulator behind the udid.
  local recaptures="${CLONE_RENDER_CAPTURE_ATTEMPTS:-3}"
  if command -v axe >/dev/null 2>&1 && [[ "$recaptures" -gt 0 ]]; then
    local ready=0
    for ((capture = 1; capture <= recaptures; capture++)); do
      if axe describe-ui --udid "$sim" 2>/dev/null | grep -q 'ClonePreview'; then
        ready=1
        break
      fi
      echo "INFO: ClonePreview is not on screen yet — waiting ($capture)" >&2
      sleep 0.5
    done
    # Wait first, capture once. Re-capturing on every failed check paid for a
    # full stable-frame poll per attempt and roughly halved the throughput of a
    # polish run; the app is simply not up yet, and waiting is what that costs.
    if [[ "$ready" -eq 1 && "$capture" -gt 1 ]]; then
      if [[ "${CLONE_RENDER_SETTLE+x}" == "x" ]]; then
        xcrun simctl io "$sim" screenshot "$out" >/dev/null 2>&1 || true
      else
        capture_stable_frame "$sim" "$out" "$work" "$baseline" || true
      fi
    fi
  fi
  if command -v axe >/dev/null 2>&1; then
    # Retry once: the first render of a run races the simulator finishing its
    # boot, and axe returns nothing. Losing the tree loses the structural diff,
    # which is the primary failure detector (SKILL Step 6-4) — so a screen whose
    # tree is missing is unchecked, not passing.
    local axe_err attempt
    axe_err="$(mktemp -t device_render_axe)"
    for attempt in 1 2; do
      if axe describe-ui --udid "$sim" > "$tree_out" 2>"$axe_err" && [[ -s "$tree_out" ]]; then
        echo "INFO: rendered accessibility tree -> $tree_out"
        rm -f "$axe_err"
        echo "OK: rendered $view -> $out"
        return 0
      fi
      [[ "$attempt" -eq 1 ]] && sleep 1
    done
    rm -f "$tree_out"
    echo "WARN: axe describe-ui failed after 2 attempts — structural diff unavailable" >&2
    sed 's/^/WARN:   /' "$axe_err" >&2 || true
    rm -f "$axe_err"
  else
    echo "INFO: AXe not installed — skipping rendered tree dump (structural diff unavailable)"
  fi
  echo "OK: rendered $view -> $out"
}

main "$@"
