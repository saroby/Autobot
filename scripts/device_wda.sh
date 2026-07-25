#!/usr/bin/env bash
# device_wda.sh — real-device app exploration for /autobot:copy, over Appium/WDA.
#
# Why not idb: fb-idb's `ui tap`/`ui describe-all` are SIMULATOR-ONLY. On a
# physical device they fail with "Target doesn't conform to
# FBSimulatorLifecycleCommands / FBAccessibilityCommands protocol", and
# `idb screenshot` fails on iOS 26 too. WebDriverAgent (XCUITest) is the only
# path that actually drives a real iPhone. See tasks/lessons.md 2026-07-25.
#
# Subcommands:
#   device [<udid|name>]              Print THE connected device udid, or fail.
#   session <udid>                    Start a WDA session; prints the session id.
#   screen <sid> <outdir> <name>      Capture <name>.png + <name>.xml + signature.
#   candidates <tree>                 Safe tap targets (delegates to device_a11y.py).
#   sig <tree>                        Screen signature (delegates to device_a11y.py).
#   tap <sid> <x> <y> <tree.xml>      Tap a candidate — refuses stale/non-candidate points.
#   swipe <sid> <x1> <y1> <x2> <y2>   Swipe between two points.
#   quit <sid>                        End the session.
#
# `device` and `session` are the two hard gates: no connected iPhone, or no WDA
# session, means /autobot:copy stops instead of degrading to store metadata.
# stdout of both is the bare id and nothing else, so callers can do
# `udid="$(device_wda.sh device)"` / `sid="$(device_wda.sh session "$udid")"`.
#
# Output follows CONVENTIONS.md prefixes (OK:/INFO:/WARN:/ERROR:).
#
# Prerequisites (once):
#   npm i -g appium && appium driver install xcuitest
#   appium server --port 4723 &            # or set APPIUM_URL
#   iPhone: Developer Mode ON + this Mac trusted + Settings > Developer >
#           Enable UI Automation ON (without it WDA dies with
#           "Timed out while enabling automation mode")
#   A signing team: DEVELOPMENT_TEAM (or TEAM_ID) in the environment.
set -euo pipefail

APPIUM_URL="${APPIUM_URL:-http://127.0.0.1:4723}"
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_curl() { curl -fsS --max-time "${CLONE_WDA_TIMEOUT:-600}" "$@"; }

_team() {
  local team="${DEVELOPMENT_TEAM:-${TEAM_ID:-}}"
  # BSD sed has no `\|` in basic regex — -E is required for the alternation.
  if [[ -z "$team" && -r "$HOME/.autobot/.env" ]]; then
    team="$(sed -nE 's/^[[:space:]]*(DEVELOPMENT_TEAM|TEAM_ID)=["'"'"']?([A-Za-z0-9]{10}).*/\2/p' \
            "$HOME/.autobot/.env" | head -1)"
  fi
  printf '%s' "$team"
}

cmd_device() {
  local want="${1:-}" line udid state name udids=() names=()
  while IFS= read -r line; do
    [[ "$line" == OK:* ]] || continue
    udid="$(cut -f1 <<<"${line#OK: }")"
    state="$(cut -f2 <<<"${line#OK: }")"
    name="$(cut -f3 <<<"${line#OK: }")"
    # `paired` is only a trust record — `connected` is the live transport.
    [[ "$state" == "connected" ]] || continue
    if [[ -n "$want" && "$udid" != "$want" && "$name" != *"$want"* ]]; then
      continue
    fi
    udids+=("$udid")
    names+=("$name")
  done < <("$_HERE/device_capture.sh" devices)

  if [[ "${#udids[@]}" -eq 0 ]]; then
    echo "ERROR: no connected iPhone — plug it in via USB, unlock it, enable Developer Mode, and trust this Mac. If Xcode sees it but this does not, open Xcode > Window > Devices and Simulators once to re-establish the CoreDevice tunnel." >&2
    return 1
  fi
  if [[ "${#udids[@]}" -gt 1 ]]; then
    echo "ERROR: ${#udids[@]} connected devices match — ask the user which one, then re-run 'device_wda.sh device <udid|name>':" >&2
    local i
    for i in "${!udids[@]}"; do echo "ERROR:   ${udids[$i]}	${names[$i]}" >&2; done
    return 1
  fi
  echo "OK: analysis device ${udids[0]}	${names[0]}" >&2
  echo "${udids[0]}"
}

cmd_session() {
  local udid="${1:-}" team body sid err
  if [[ -z "$udid" ]]; then
    echo "ERROR: usage: device_wda.sh session <udid>" >&2
    return 1
  fi
  team="$(_team)"
  if [[ -z "$team" ]]; then
    echo "ERROR: no signing team — export DEVELOPMENT_TEAM=<10-char team id> (WDA must be signed to install on a real device)" >&2
    return 1
  fi
  # Building + installing WDA on first run takes minutes; later runs reattach.
  body="$(python3 -c "
import json, os, sys
print(json.dumps({'capabilities': {'alwaysMatch': {
    'platformName': 'iOS',
    'appium:automationName': 'XCUITest',
    'appium:udid': sys.argv[1],
    'appium:xcodeOrgId': sys.argv[2],
    'appium:xcodeSigningId': 'Apple Development',
    'appium:newCommandTimeout': 900,
    'appium:wdaLaunchTimeout': 420000,
    'appium:wdaConnectionTimeout': 420000,
    'appium:shouldTerminateApp': False,
    'appium:noReset': True,
    # code 65 is opaque on its own; this puts the real xcodebuild error in the
    # Appium log. Opt-in because it is very verbose.
    'appium:showXcodeLog': bool(os.environ.get('CLONE_WDA_DEBUG')),
}}}))" "$udid" "$team")"

  # NOT _curl: `-f` throws the response body away on a non-2xx, and Appium puts
  # the actual reason (WDA build log, automation-mode timeout, bad caps) in the
  # body of a 500. Losing it turns every session failure into "unreachable".
  err="$(curl -sS --max-time "${CLONE_WDA_TIMEOUT:-600}" \
         -X POST "$APPIUM_URL/session" -H 'Content-Type: application/json' -d "$body" 2>&1)" || true
  if [[ -z "$err" ]] || ! grep -q '"value"' <<<"$err"; then
    echo "ERROR: Appium did not answer at $APPIUM_URL — start it with 'appium server --port 4723' (${err##*$'\n'})" >&2
    return 1
  fi
  sid="$(python3 -c "
import json, sys
v = json.load(sys.stdin).get('value', {})
if v.get('sessionId'):
    print(v['sessionId'])
else:
    msg = (v.get('message') or 'unknown error').splitlines()[0]
    hint = ''
    if 'automation mode' in msg:
        hint = ' — turn ON Settings > Developer > Enable UI Automation on the device'
    elif 'code 65' in msg:
        hint = (' — WDA failed to build/sign. Check DEVELOPMENT_TEAM and that the device is'
                ' unlocked; if both look fine, re-run with CLONE_WDA_DEBUG=1 against an Appium'
                ' server started with --log-level debug and read the xcodebuild error there.'
                ' Most common cause: Settings > Developer > Enable UI Automation is OFF.')
    print('ERROR: WDA session failed: %s%s' % (msg, hint), file=sys.stderr)
" <<<"$err")"
  if [[ -z "$sid" ]]; then
    return 1
  fi
  echo "OK: WDA session on $udid" >&2
  echo "$sid"
}

cmd_screen() {
  local sid="${1:-}" outdir="${2:-}" name="${3:-}"
  if [[ -z "$sid" || -z "$outdir" || -z "$name" ]]; then
    echo "ERROR: usage: device_wda.sh screen <sid> <outdir> <name>" >&2
    return 1
  fi
  mkdir -p "$outdir"
  local png="$outdir/$name.png" xml="$outdir/$name.xml" base="$APPIUM_URL/session/$sid"
  if ! _curl "$base/screenshot" | python3 -c "
import base64, json, sys
open(sys.argv[1], 'wb').write(base64.b64decode(json.load(sys.stdin)['value']))" "$png"; then
    echo "ERROR: screenshot failed — is the session alive and the device unlocked?" >&2
    return 1
  fi
  if ! _curl "$base/source" | python3 -c "
import json, sys
open(sys.argv[1], 'w', encoding='utf-8').write(json.load(sys.stdin)['value'])" "$xml"; then
    echo "WARN: captured $png but the accessibility tree failed"
    return 0
  fi
  python3 "$_HERE/device_a11y.py" sig "$xml" || true
  local key
  key="$(_key_of "$xml" || true)"
  if [[ -n "$key" ]]; then
    echo "INFO: nodekey $key"
    _flow_event screen "node=$key" "sig=$(_sig_of "$xml")" "name=$name" "tree=$xml" "png=$png"
  fi
  echo "OK: captured $png + $xml"
}

_actions() {
  local sid="$1" payload="$2"
  if ! _curl -X POST "$APPIUM_URL/session/$sid/actions" -H 'Content-Type: application/json' \
       -d "$payload" >/dev/null 2>&1; then
    echo "ERROR: input failed — session dead, device locked, or unplugged. Stop the loop." >&2
    return 1
  fi
}

# Dump the CURRENT screen's tree to $1. Callers derive sig/nodekey from it —
# one HTTP round trip for both, since the settle poll below runs it repeatedly.
_live_dump() {
  local sid="$1" out="$2"
  _curl "$APPIUM_URL/session/$sid/source" | python3 -c "
import json, sys
open(sys.argv[1], 'w', encoding='utf-8').write(json.load(sys.stdin)['value'])" "$out" 2>/dev/null
}

# Screen signature of what is on the device RIGHT NOW.
_live_sig() {
  local sid="$1" tmp out=""
  tmp="$(mktemp -t device_wda)"
  if _live_dump "$sid" "$tmp"; then
    out="$(python3 "$_HERE/device_a11y.py" sig "$tmp" | sed -n 's/^INFO: sig //p')"
  fi
  rm -f "$tmp"
  [[ -n "$out" ]] || return 1
  printf '%s' "$out"
}

_key_of() { python3 "$_HERE/device_a11y.py" nodekey "$1" | sed -n 's/^INFO: nodekey //p'; }
_sig_of() { python3 "$_HERE/device_a11y.py" sig "$1" | sed -n 's/^INFO: sig //p'; }

# One line per event in a FIXED location, so `device_flow.py` can read the run
# back — for the flow map, for the coverage report, and to resume exploration
# after the session dies (which, on a real phone, is the normal ending).
# Logging NEVER changes the verdict of the action it logs. A tap that physically
# happened must not report failure because the log path was unwritable — the
# exploration loop would retry it and double-tap a real phone.
_flow_event() {
  _flow_write "$@" || echo "WARN: could not append to the exploration log (${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}) — flow map and resume will be incomplete"
}

_flow_write() {
  CLONE_FLOW_LOG="${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}" python3 -c "
import json, os, sys
path = os.environ['CLONE_FLOW_LOG']
event = dict(a.split('=', 1) for a in sys.argv[2:])
event['type'] = sys.argv[1]
os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
with open(path, 'a', encoding='utf-8') as fh:
    fh.write(json.dumps(event, ensure_ascii=False) + '\n')
" "$@"
}

cmd_tap() {
  local sid="${1:-}" x="${2:-}" y="${3:-}" tree="${4:-}" planned live
  if [[ -z "$sid" || -z "$x" || -z "$y" || -z "$tree" ]]; then
    echo "ERROR: usage: device_wda.sh tap <sid> <x> <y> <tree.xml>" >&2
    echo "ERROR:   <tree.xml> is the capture the coordinate came from — taps are only" >&2
    echo "ERROR:   allowed at candidates of the screen currently on the device." >&2
    return 1
  fi
  if [[ ! -f "$tree" ]]; then
    echo "ERROR: no such tree '$tree' — capture the screen first with 'screen'" >&2
    return 1
  fi
  # (1) Provenance: the point must be a target this tree offered.
  python3 "$_HERE/device_a11y.py" verify "$tree" "$x" "$y" || return 1
  # (2) Freshness: the device must still be showing that screen. This is the
  # guard that a prose STOP rule could not enforce — a tap planned against a
  # stale tree walked a live run out of the target app and into another one.
  planned="$(python3 "$_HERE/device_a11y.py" sig "$tree" | sed -n 's/^INFO: sig //p')"
  if ! live="$(_live_sig "$sid")"; then
    echo "ERROR: cannot read the current screen — session dead or device gone. Stop the loop." >&2
    return 1
  fi
  if [[ "$planned" != "$live" ]]; then
    echo "ERROR: screen changed since $(basename "$tree") (planned $planned, live $live) — do NOT tap stale coordinates. Re-capture with 'screen' and pick from fresh candidates." >&2
    return 1
  fi
  local label
  label="$(python3 "$_HERE/device_a11y.py" candidates "$tree" \
           | awk -v k="INFO: tap $x $y " 'index($0, k) == 1 { sub(/^[^|]*\| [^|]*\| /, ""); print; exit }')"
  _actions "$sid" "$(printf '{"actions":[{"type":"pointer","id":"finger1","parameters":{"pointerType":"touch"},"actions":[{"type":"pointerMove","duration":0,"x":%s,"y":%s},{"type":"pointerDown","button":0},{"type":"pause","duration":60},{"type":"pointerUp","button":0}]}]}' "$x" "$y")"

  # (3) Record the transition. Reading the screen straight after the tap returns
  # the DEPARTING one — the transition is still animating — so every edge would
  # be recorded as "went nowhere". Poll until the signature moves, and if it
  # never does, record that: "this tap changes nothing" is real flow data.
  local to_tree to_sig to_key changed=false i=0
  to_tree="$(mktemp -t device_wda)"
  to_sig="$planned"
  while [[ "$i" -lt "${CLONE_TAP_SETTLE_TRIES:-10}" ]]; do
    sleep 0.3
    i=$((i + 1))
    if ! _live_dump "$sid" "$to_tree"; then break; fi
    to_sig="$(_sig_of "$to_tree" || true)"
    if [[ -n "$to_sig" && "$to_sig" != "$planned" ]]; then changed=true; break; fi
  done
  to_key="$(_key_of "$to_tree" 2>/dev/null || true)"
  _flow_event tap "from=$(_key_of "$tree" || echo '?')" "to=${to_key:-?}" \
              "label=${label:-?}" "x=$x" "y=$y" "changed=$changed"
  rm -f "$to_tree"
  echo "OK: tapped $x,$y${label:+ ($label)}"
  [[ "$changed" == true ]] || echo "INFO: screen did not change — this target is a no-op or opened nothing"
}

cmd_swipe() {
  local sid="${1:-}" x1="${2:-}" y1="${3:-}" x2="${4:-}" y2="${5:-}"
  if [[ -z "$sid" || -z "$x1" || -z "$y1" || -z "$x2" || -z "$y2" ]]; then
    echo "ERROR: usage: device_wda.sh swipe <sid> <x1> <y1> <x2> <y2>" >&2
    return 1
  fi
  _actions "$sid" "$(printf '{"actions":[{"type":"pointer","id":"finger1","parameters":{"pointerType":"touch"},"actions":[{"type":"pointerMove","duration":0,"x":%s,"y":%s},{"type":"pointerDown","button":0},{"type":"pause","duration":100},{"type":"pointerMove","duration":600,"x":%s,"y":%s},{"type":"pointerUp","button":0}]}]}' "$x1" "$y1" "$x2" "$y2")"
  echo "OK: swiped $x1,$y1 -> $x2,$y2"
}

cmd_quit() {
  local sid="${1:-}"
  if [[ -z "$sid" ]]; then
    echo "ERROR: usage: device_wda.sh quit <sid>" >&2
    return 1
  fi
  _curl -X DELETE "$APPIUM_URL/session/$sid" >/dev/null 2>&1 || true
  echo "OK: session ended"
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    device)     cmd_device "$@" ;;
    session)    cmd_session "$@" ;;
    screen)     cmd_screen "$@" ;;
    candidates) python3 "$_HERE/device_a11y.py" candidates "$@" ;;
    sig)        python3 "$_HERE/device_a11y.py" sig "$@" ;;
    tap)        cmd_tap "$@" ;;
    swipe)      cmd_swipe "$@" ;;
    quit)       cmd_quit "$@" ;;
    *) echo "ERROR: unknown subcommand '${sub:-}'. Use: device | session | screen | candidates | sig | tap | swipe | quit" >&2; return 1 ;;
  esac
}

main "$@"
