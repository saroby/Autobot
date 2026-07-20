#!/usr/bin/env bash
# clone_idb.sh — idb-backed device analysis for /autobot:clone.
#
# idb (facebook/idb) drives a connected iPhone via XCTest: screenshot, the full
# accessibility tree (`ui describe-all`), and optional input (tap/swipe). The
# accessibility tree is the prize — exact element roles/labels/frames/ids, far
# richer than vision on screenshots.
#
# Subcommands:
#   targets                          List idb targets, flagging the physical device.
#   screen <udid> <outdir> <name>    Capture <name>.png + <name>.a11y.json together.
#
# Output follows CONVENTIONS.md prefixes (OK:/WARN:/ERROR:). Target parsing is
# testable offline by pointing CLONE_TARGETS_RAW at a file holding
# `idb list-targets` output.
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

cmd_screen() {
  local udid="${1:-}" outdir="${2:-}" name="${3:-}"
  if [[ -z "$udid" || -z "$outdir" || -z "$name" ]]; then
    echo "ERROR: usage: clone_idb.sh screen <udid> <outdir> <name>" >&2
    return 1
  fi
  mkdir -p "$outdir"
  local png="$outdir/$name.png" a11y="$outdir/$name.a11y.json" err
  if ! err="$(idb screenshot --udid "$udid" "$png" 2>&1)"; then
    echo "ERROR: screenshot failed — is the device unlocked and awake? ($(tail -1 <<<"$err"))" >&2
    return 1
  fi
  if ! idb ui describe-all --udid "$udid" > "$a11y" 2>/dev/null; then
    echo "WARN: captured $png but accessibility dump failed (app may disable accessibility)"
    return 0
  fi
  echo "OK: captured $png + $a11y"
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    targets) cmd_targets "$@" ;;
    screen)  cmd_screen "$@" ;;
    *) echo "ERROR: unknown subcommand '${sub:-}'. Use: targets | screen" >&2; return 1 ;;
  esac
}

main "$@"
