#!/usr/bin/env bash
# device_idb.sh — idb-backed SIMULATOR analysis for /autobot:copy.
#
# ⚠️ SIMULATORS ONLY. Verified 2026-07-25: fb-idb's UI commands are not
# implemented for physical devices — `ui describe-all` fails with "Target
# doesn't conform to FBAccessibilityCommands protocol", `ui tap` with
# "...FBSimulatorLifecycleCommands protocol", and `idb screenshot` with
# "screenshotr ... 0xe8000022" on iOS 26. Attaching a fresh companion does not
# change it. **Real devices go through `device_wda.sh` (Appium/WebDriverAgent).**
#
# On a simulator idb does work, and the accessibility tree is the prize — exact
# element roles/labels/frames/ids, far richer than vision on screenshots. Useful
# when the target ships as an .ipa you can install on a simulator.
#
# Subcommands:
#   targets                          List idb targets, flagging the physical device.
#   device [<udid|name>]             Print THE physical device udid on stdout, or fail.
#   screen <udid> <outdir> <name>    Capture <name>.png + <name>.a11y.json together.
#   candidates <a11y.json>           Tappable elements w/ centers; destructive ones withheld.
#   sig <a11y.json>                  Screen signature (label-set hash) — loop termination.
#   tap <udid> <x> <y>               Tap a point (thin idb passthrough).
#   swipe <udid> <x1> <y1> <x2> <y2> Swipe between two points (thin idb passthrough).
#
# `device` is the hard gate for /autobot:copy — agent-driven exploration only
# runs against a connected iPhone. Its stdout is the bare udid and nothing else
# (all diagnostics go to stderr) so callers can do `udid=$(device_idb.sh device)`.
# It proves idb can *enumerate* the device; locked/asleep only surfaces on the
# first `idb screenshot`, which stays the second gate.
#
# Output follows CONVENTIONS.md prefixes (OK:/WARN:/ERROR:). Target parsing is
# testable offline by pointing CLONE_TARGETS_RAW at a file holding
# `idb list-targets` output; `candidates` reads a file, so it is offline by
# construction. `tap`/`swipe` are thin passthroughs and are not injectable.
#
# Setup (once):
#   brew tap facebook/fb && brew trust --formula facebook/fb/idb-companion \
#     && brew install idb-companion            # native, compiles from source
#   pipx install fb-idb --python python3.11     # fb-idb 1.1.x needs Python <=3.13
# A physical device also needs Developer Mode ON + this Mac trusted.
set -euo pipefail

_targets_raw() {
  if [[ -n "${CLONE_TARGETS_RAW:-}" ]]; then
    cat "$CLONE_TARGETS_RAW"
  else
    idb list-targets 2>/dev/null
  fi
}

cmd_targets() {
  local out saw_physical=0 line
  out="$(_targets_raw)"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    # Name | UDID | State | type | iOS | arch | companion
    local name udid state type
    name="$(cut -d'|' -f1 <<<"$line" | xargs)"
    udid="$(cut -d'|' -f2 <<<"$line" | xargs)"
    state="$(cut -d'|' -f3 <<<"$line" | xargs)"
    type="$(cut -d'|' -f4 <<<"$line" | xargs)"
    if [[ "$type" == "device" ]]; then
      saw_physical=1
      echo "OK: ${udid}	device	${state}	${name}"
    else
      echo "INFO: ${udid}	${type}	${state}	${name}"
    fi
  done <<<"$out"
  if [[ "$saw_physical" -eq 0 ]]; then
    echo "WARN: no physical device — plug an iPhone in via USB, enable Developer Mode, and trust this Mac (simulators can't run App Store apps)"
  fi
}

_DEVICE_HINT='plug an iPhone in via USB, unlock it, enable Developer Mode (설정 > 개인정보 보호 및 보안 > 개발자 모드), and trust this Mac (simulators cannot run App Store apps)'

# Hard gate. stdout = the udid alone; every diagnostic goes to stderr.
cmd_device() {
  local want="${1:-}" line udids=() names=() name udid type
  if [[ -z "${CLONE_TARGETS_RAW:-}" ]] && ! command -v idb >/dev/null 2>&1; then
    echo "ERROR: idb not installed — agent-driven exploration needs it. Install: brew tap facebook/fb && brew trust --formula facebook/fb/idb-companion && brew install idb-companion && pipx install fb-idb --python python3.11" >&2
    return 1
  fi
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    name="$(cut -d'|' -f1 <<<"$line" | xargs)"
    udid="$(cut -d'|' -f2 <<<"$line" | xargs)"
    type="$(cut -d'|' -f4 <<<"$line" | xargs)"
    [[ "$type" != "device" ]] && continue
    # Optional selector: udid or a substring of the device name.
    if [[ -n "$want" && "$udid" != "$want" && "$name" != *"$want"* ]]; then
      continue
    fi
    udids+=("$udid")
    names+=("$name")
  done <<<"$(_targets_raw)"

  if [[ "${#udids[@]}" -eq 0 ]]; then
    if [[ -n "$want" ]]; then
      echo "ERROR: no physical device matches '$want' — run 'device_idb.sh targets' to see what idb sees" >&2
    else
      echo "ERROR: no physical device connected — $_DEVICE_HINT" >&2
    fi
    return 1
  fi
  if [[ "${#udids[@]}" -gt 1 ]]; then
    echo "ERROR: ${#udids[@]} physical devices match — ask the user which one to analyze, then re-run 'device_idb.sh device <udid|name>':" >&2
    local i
    for i in "${!udids[@]}"; do
      echo "ERROR:   ${udids[$i]}	${names[$i]}" >&2
    done
    return 1
  fi
  echo "OK: analysis device ${udids[0]}	${names[0]}" >&2
  echo "${udids[0]}"
}

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cmd_tap() {
  local udid="${1:-}" x="${2:-}" y="${3:-}" err
  if [[ -z "$udid" || -z "$x" || -z "$y" ]]; then
    echo "ERROR: usage: device_idb.sh tap <udid> <x> <y>" >&2
    return 1
  fi
  if ! err="$(idb ui tap --udid "$udid" "$x" "$y" 2>&1)"; then
    echo "ERROR: tap failed at $x,$y — device disconnected or locked? ($(tail -1 <<<"$err"))" >&2
    return 1
  fi
  echo "OK: tapped $x,$y"
}

cmd_swipe() {
  local udid="${1:-}" x1="${2:-}" y1="${3:-}" x2="${4:-}" y2="${5:-}" err
  if [[ -z "$udid" || -z "$x1" || -z "$y1" || -z "$x2" || -z "$y2" ]]; then
    echo "ERROR: usage: device_idb.sh swipe <udid> <x1> <y1> <x2> <y2>" >&2
    return 1
  fi
  if ! err="$(idb ui swipe --udid "$udid" "$x1" "$y1" "$x2" "$y2" 2>&1)"; then
    echo "ERROR: swipe failed — device disconnected or locked? ($(tail -1 <<<"$err"))" >&2
    return 1
  fi
  echo "OK: swiped $x1,$y1 -> $x2,$y2"
}

cmd_screen() {
  local udid="${1:-}" outdir="${2:-}" name="${3:-}"
  if [[ -z "$udid" || -z "$outdir" || -z "$name" ]]; then
    echo "ERROR: usage: device_idb.sh screen <udid> <outdir> <name>" >&2
    return 1
  fi
  mkdir -p "$outdir"
  local png="$outdir/$name.png" a11y="$outdir/$name.a11y.json" err
  if ! err="$(idb screenshot --udid "$udid" "$png" 2>&1)"; then
    echo "ERROR: screenshot failed — is the device unlocked and awake? ($(tail -1 <<<"$err"))" >&2
    return 1
  fi
  # --nested keeps the hierarchy (children arrays); device_a11y.py flattens it
  # with depth/parent so ancestor checks match the WDA path.
  if ! idb ui describe-all --udid "$udid" --json --nested > "$a11y" 2>/dev/null; then
    echo "WARN: captured $png but accessibility dump failed (app may disable accessibility)"
    return 0
  fi
  # Screen signature — the loop's termination primitive: same sig = same screen.
  python3 "$_HERE/device_a11y.py" sig "$a11y" || true
  echo "OK: captured $png + $a11y"
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    targets)    cmd_targets "$@" ;;
    device)     cmd_device "$@" ;;
    screen)     cmd_screen "$@" ;;
    candidates) python3 "$_HERE/device_a11y.py" candidates "$@" ;;
    sig)        python3 "$_HERE/device_a11y.py" sig "$@" ;;
    tap)        cmd_tap "$@" ;;
    swipe)      cmd_swipe "$@" ;;
    *) echo "ERROR: unknown subcommand '${sub:-}'. Use: targets | device | screen | candidates | sig | tap | swipe" >&2; return 1 ;;
  esac
}

main "$@"
