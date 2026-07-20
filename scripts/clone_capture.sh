#!/usr/bin/env bash
# clone_capture.sh — physical-device screen capture for /autobot:clone.
#
# Subcommands:
#   devices                     List connected *physical* iOS devices, one per line.
#   shot <udid> <dest.png>      Capture the device's current screen to <dest.png>.
#
# Output follows CONVENTIONS.md prefixes (OK:/WARN:/ERROR:). Device enumeration
# can be tested offline by pointing CLONE_DEVICES_JSON at a fixture file holding
# `xcrun devicectl list devices --json-output` output.
#
# Reality: devicectl capture requires the device unlocked, awake, and trusted.
# A locked/asleep device returns CoreDeviceError 4016 — mapped here to an
# actionable remedy so the caller can prompt the human, not just fail.
set -euo pipefail

_devices_json() {
  if [[ -n "${CLONE_DEVICES_JSON:-}" ]]; then
    cat "$CLONE_DEVICES_JSON"
  else
    xcrun devicectl list devices --json-output - 2>/dev/null
  fi
}

cmd_devices() {
  local out
  out="$(_devices_json | python3 -c '
import json, sys
try:
    devs = json.load(sys.stdin).get("result", {}).get("devices", [])
except Exception:
    print("ERROR: could not parse devicectl device list", file=sys.stderr)
    sys.exit(1)
found = False
for d in devs:
    hp = d.get("hardwareProperties", {})
    if hp.get("reality") != "physical":
        continue
    found = True
    udid = hp.get("udid") or d.get("identifier", "")
    tunnel = d.get("connectionProperties", {}).get("tunnelState", "unknown")
    name = d.get("deviceProperties", {}).get("name", "?")
    # tab-separated: udid, tunnelState, name
    print(f"OK: {udid}\t{tunnel}\t{name}")
if not found:
    print("WARN: no connected physical iOS device — plug an iPhone in via USB and trust this Mac")
')"
  echo "$out"
}

# Print "ddi=<bool> tunnel=<state>" for the given udid, from the device list.
_device_diag() {
  local udid="$1"
  _devices_json | python3 -c '
import json, sys
udid = sys.argv[1]
for d in json.load(sys.stdin).get("result", {}).get("devices", []):
    hp = d.get("hardwareProperties", {})
    if (hp.get("udid") or d.get("identifier")) != udid:
        continue
    ddi = d.get("deviceProperties", {}).get("ddiServicesAvailable")
    tunnel = d.get("connectionProperties", {}).get("tunnelState", "unknown")
    print(f"ddi={ddi} tunnel={tunnel}")
    break
' "$udid" 2>/dev/null
}

cmd_shot() {
  local udid="${1:-}" dest="${2:-}"
  if [[ -z "$udid" || -z "$dest" ]]; then
    echo "ERROR: usage: clone_capture.sh shot <udid> <dest.png>" >&2
    return 1
  fi
  case "$dest" in
    *.png) ;;
    *) echo "ERROR: destination must be a .png path" >&2; return 1 ;;
  esac
  local err
  if err="$(xcrun devicectl device capture screenshot --device "$udid" --destination "$dest" 2>&1)"; then
    echo "OK: captured $dest"
    return 0
  fi
  if grep -q "4016" <<<"$err"; then
    # 4016 (empty CurrentlyAssertableStates) has two distinct causes with
    # opposite remedies. ddiServicesAvailable=false → developer path not set up;
    # otherwise the device is present but not awake/unlocked.
    local diag
    diag="$(_device_diag "$udid")"
    if grep -q "ddi=False" <<<"$diag"; then
      echo "ERROR: developer services unavailable ($diag) — enable Developer Mode (Settings > Privacy & Security > Developer Mode), trust this Mac, and reconnect" >&2
    else
      echo "ERROR: device is locked or asleep ($diag) — unlock the iPhone, keep the screen on, tap 'Trust' if prompted, then retry" >&2
    fi
    return 1
  fi
  echo "ERROR: screenshot failed: $(tail -1 <<<"$err")" >&2
  return 1
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    devices) cmd_devices "$@" ;;
    shot)    cmd_shot "$@" ;;
    *) echo "ERROR: unknown subcommand '${sub:-}'. Use: devices | shot" >&2; return 1 ;;
  esac
}

main "$@"
