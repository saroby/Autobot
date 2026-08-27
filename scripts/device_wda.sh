#!/usr/bin/env bash
# device_wda.sh — real-device app exploration for /autobot:copy and /autobot:clone,
# over Appium/WDA.
#
# Why not idb: fb-idb's `ui tap`/`ui describe-all` are SIMULATOR-ONLY. On a
# physical device they fail with "Target doesn't conform to
# FBSimulatorLifecycleCommands / FBAccessibilityCommands protocol", and
# `idb screenshot` fails on iOS 26 too. WebDriverAgent (XCUITest) is the only
# path that actually drives a real iPhone. See tasks/lessons.md 2026-07-25.
#
# Subcommands:
#   device [<udid|name>]              Print THE connected device udid, or fail.
#   session <udid> <bundle_id>        Start a WDA session bound to the target app.
#   screen <sid> <outdir> <name>      Capture <name>.png + <name>.xml + signature.
#   step <sid> <x> <y> <tree> <outdir> <name>  Tap, settle, and capture destination evidence.
#   explore <sid> <outdir> [max_steps]  Drain safe frontier candidates mechanically (default 20 steps).
#   candidates <tree>                 Safe tap targets (delegates to device_a11y.py).
#   sig <tree>                        Screen signature (delegates to device_a11y.py).
#   tap <sid> <x> <y> <tree.xml>      Tap a candidate — refuses stale/non-candidate points.
#   type <sid> <accessibility_id> <text>  Type into a semantic text field.
#   swipe <sid> <x1> <y1> <x2> <y2>   Swipe, settle, and log the transition (POINTS).
#   swipefrac <sid> <fx1> <fy1> <fx2> <fy2> [tree]  Same, in fractions of the app
#                                     frame — no pixel/point conversion to get wrong.
#   back <sid>                        Tap the nav bar's leading control — the only
#                                     unlabelled tap, for escaping a dead-end screen.
#   quit <sid>                        End the session.
#   stop-server                       Stop only the Appium server started by this script.
#   doctor [<udid|name>] [<bundle_id>]  Diagnose the local real-device toolchain.
#
# `device` and `session` are the two hard gates: no connected iPhone, or no WDA
# session bound to the target bundle, means /autobot:clone stops instead of
# exploring whichever app happens to be in the foreground.
# stdout of both is the bare id and nothing else, so callers can do
# `udid="$(device_wda.sh device)"` / `sid="$(device_wda.sh session "$udid" "$bundle_id")"`.
#
# Output follows CONVENTIONS.md prefixes (OK:/INFO:/WARN:/ERROR:).
#
# Prerequisites (once):
#   npm i -g appium && appium driver install xcuitest
#   Appium is auto-started locally when APPIUM_URL is unavailable.
#   iOS 18+ real device: when the target tunnel is missing, the clone Xcode
#   project is opened first and macOS administrator authorization is requested
#   once to start Appium's RemoteXPC tunnel in the background.
#   iPhone: Developer Mode ON + this Mac trusted + Settings > Developer >
#           Enable UI Automation ON (without it WDA dies with
#           "Timed out while enabling automation mode")
#   A signing team: DEVELOPMENT_TEAM (or TEAM_ID) in the environment.
set -euo pipefail

# Reset, never inherited. This grants an exemption from the tap budget, so a
# caller that exported it would lift the ceiling on someone's real account:
# `_TAP_REVERTING=1 device_wda.sh tap ...` would tap without limit. Only the
# revert path inside this script may set it.
_TAP_REVERTING=0
# Set when a tap could not be written to the flow log; the budget is blind after
# that, so no further tap is allowed.
_FLOW_BROKEN=0

APPIUM_URL="${APPIUM_URL:-http://127.0.0.1:4723}"
_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLONE_STATE_DIR="${CLONE_STATE_DIR:-$PWD/.autobot/clone}"
CLONE_SESSION_FILE="${CLONE_SESSION_FILE:-$CLONE_STATE_DIR/wda-session.json}"
CLONE_DEVICE_PROFILE_FILE="${CLONE_DEVICE_PROFILE_FILE:-$CLONE_STATE_DIR/device-profile.json}"
CLONE_APPIUM_PID_FILE="${CLONE_APPIUM_PID_FILE:-$CLONE_STATE_DIR/appium-server.pid}"
CLONE_APPIUM_LABEL_FILE="${CLONE_APPIUM_LABEL_FILE:-$CLONE_STATE_DIR/appium-server.label}"
CLONE_APPIUM_LOG="${CLONE_APPIUM_LOG:-$CLONE_STATE_DIR/appium-server.log}"
CLONE_METRICS_LOG="${CLONE_METRICS_LOG:-$CLONE_STATE_DIR/http-metrics.jsonl}"
CLONE_TUNNEL_REGISTRY_URL="${CLONE_TUNNEL_REGISTRY_URL:-http://127.0.0.1:42314/remotexpc/tunnels}"
CLONE_TUNNEL_LOG="${CLONE_TUNNEL_LOG:-$CLONE_STATE_DIR/remotexpc-tunnel.log}"

_metric_write() {
  [[ "${CLONE_METRICS:-0}" == "1" ]] || return 0
  local method="$1" url="$2" status="$3" elapsed="$4" exit_code="$5"
  mkdir -p "$(dirname "$CLONE_METRICS_LOG")" 2>/dev/null || return 0
  python3 -c '
import json, os, sys
from datetime import datetime, timezone
path, method, url, status, elapsed, exit_code = sys.argv[1:]
event = {
    "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    "method": method,
    "url": url,
    "status": int(status) if status.isdigit() else 0,
    "seconds": float(elapsed) if elapsed else 0.0,
    "exitCode": int(exit_code),
}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
' "$CLONE_METRICS_LOG" "$method" "$url" "$status" "$elapsed" "$exit_code" \
    >/dev/null 2>&1 || true
}

# Metrics use curl's separate --output/--write-out files. Timing data therefore
# never shares stdout with the JSON response consumed by callers.
_curl_impl() {
  local fail_http="$1"
  shift
  if [[ "${CLONE_METRICS:-0}" != "1" ]]; then
    if [[ "$fail_http" == "1" ]]; then
      curl -fsS --max-time "${CLONE_WDA_TIMEOUT:-600}" "$@"
    else
      curl -sS --max-time "${CLONE_WDA_TIMEOUT:-600}" "$@"
    fi
    return
  fi

  local body_file timing_file rc=0 method=GET url="" status=000 elapsed=0 effective=""
  local arg previous="" saw_data=0
  body_file="$(mktemp -t device_wda_http_body)"
  timing_file="$(mktemp -t device_wda_http_timing)"
  for arg in "$@"; do
    if [[ "$previous" == "request" ]]; then
      method="$arg"
      previous=""
      continue
    fi
    case "$arg" in
      -X|--request) previous=request ;;
      -d|--data|--data-raw|--data-binary) saw_data=1 ;;
      http://*|https://*) url="$arg" ;;
    esac
  done
  [[ "$method" != "GET" || "$saw_data" -eq 0 ]] || method=POST

  local curl_args=(-sS --max-time "${CLONE_WDA_TIMEOUT:-600}")
  [[ "$fail_http" == "1" ]] && curl_args+=(-f)
  if curl "${curl_args[@]}" --output "$body_file" \
       --write-out $'%{http_code}\t%{time_total}\t%{url_effective}' "$@" >"$timing_file"; then
    rc=0
  else
    rc=$?
  fi
  cat "$body_file"
  IFS=$'\t' read -r status elapsed effective <"$timing_file" || true
  [[ -n "$effective" ]] && url="$effective"
  _metric_write "$method" "$url" "${status:-000}" "${elapsed:-0}" "$rc"
  rm -f "$body_file" "$timing_file"
  return "$rc"
}

_curl() { _curl_impl 1 "$@"; }
_curl_keep_body() { _curl_impl 0 "$@"; }

_team() {
  local team="${DEVELOPMENT_TEAM:-${TEAM_ID:-}}"
  # BSD sed has no `\|` in basic regex — -E is required for the alternation.
  if [[ -z "$team" && -r "$HOME/.autobot/.env" ]]; then
    team="$(sed -nE 's/^[[:space:]]*(DEVELOPMENT_TEAM|TEAM_ID)=["'"'"']?([A-Za-z0-9]{10}).*/\2/p' \
            "$HOME/.autobot/.env" | head -1)"
  fi
  printf '%s' "$team"
}

# Two things about `devicectl device info details` are not portable across the
# Xcode versions this runs on, and both used to read as "no device":
#   * `--omit-deprecated-fields-in-json` only trims the payload, and it is not
#     on every shipped devicectl — Xcode 26.6 rejects it with "Unknown option"
#     while a connected phone sits right there. Every field this profile reads
#     is present without it, so the flag is a preference, not a requirement.
#   * `--json-output -` interleaves devicectl's own progress text with the
#     payload on stdout, so the JSON goes to a file and stdout is discarded.
_devicectl_details() {
  local udid="$1" tmp rc=1
  tmp="$(mktemp -t device_wda_details)" || return 1
  if xcrun devicectl device info details --device "$udid" \
       --json-output "$tmp" --omit-deprecated-fields-in-json >/dev/null 2>&1 \
     || xcrun devicectl device info details --device "$udid" \
       --json-output "$tmp" >/dev/null 2>&1; then
    if [[ -s "$tmp" ]]; then
      cat "$tmp"
      rc=0
    fi
  fi
  rm -f "$tmp"
  return "$rc"
}

_persist_device_profile() {
  local udid="$1" fallback_name="$2" details
  if [[ -n "${CLONE_DEVICE_DETAILS_JSON:-}" ]]; then
    if [[ ! -r "$CLONE_DEVICE_DETAILS_JSON" ]]; then
      echo "ERROR: device details fixture is unreadable: $CLONE_DEVICE_DETAILS_JSON" >&2
      return 1
    fi
    details="$(<"$CLONE_DEVICE_DETAILS_JSON")"
  else
    if ! details="$(_devicectl_details "$udid")"; then
      echo "ERROR: could not read structured details for $udid — unlock/reconnect the iPhone and retry 'device'" >&2
      return 1
    fi
  fi

  mkdir -p "$(dirname "$CLONE_DEVICE_PROFILE_FILE")"
  if ! python3 -c '
import json, os, sys
from datetime import datetime, timezone

out_path, expected_udid, fallback_name = sys.argv[1:]
doc = json.load(sys.stdin)
props = doc.get("result", {}).get("properties", {})
hardware = props.get("hardware", {})
software = props.get("software", {})
state = props.get("state", {})
connection = props.get("connection", {})
actual_udid = hardware.get("udid") or ""
if hardware.get("reality") != "physical":
    raise SystemExit("details are not for a physical device")
if actual_udid != expected_udid:
    raise SystemExit("details UDID %r does not match selected %r" % (actual_udid, expected_udid))
builds = software.get("osBuildVersions", {})
build = (builds.get("buildVersion", {}) or {}).get("name") or ""
profile = {
    "udid": actual_udid,
    "name": state.get("name") or fallback_name,
    "marketingName": hardware.get("marketingName") or "",
    "productType": hardware.get("productType") or "",
    "osVersion": (software.get("osVersionNumber", {}) or {}).get("stringValue") or "",
    "osBuild": build,
    "connectionState": connection.get("state") or "",
    "capturedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
}

tmp = out_path + ".tmp.%d" % os.getpid()
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(profile, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, out_path)
' "$CLONE_DEVICE_PROFILE_FILE" "$udid" "$fallback_name" <<<"$details"; then
    echo "ERROR: devicectl details did not contain a valid physical-device profile for $udid" >&2
    return 1
  fi
  echo "INFO: device profile $CLONE_DEVICE_PROFILE_FILE" >&2
}

_device_requires_tunnel() {
  local udid="$1"
  [[ -r "$CLONE_DEVICE_PROFILE_FILE" ]] || return 1
  python3 -c '
import json, re, sys
path, udid = sys.argv[1:]
try:
    value = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
match = re.match(r"\s*(\d+)", str(value.get("osVersion") or ""))
required = value.get("udid") == udid and match and int(match.group(1)) >= 18
raise SystemExit(0 if required else 1)
' "$CLONE_DEVICE_PROFILE_FILE" "$udid" 2>/dev/null
}

_tunnel_registry_ready() {
  local udid="$1" response
  case "${CLONE_TUNNEL_READY:-}" in
    1) return 0 ;;
    0) return 1 ;;
  esac
  response="$(curl -fsS --max-time "${CLONE_TUNNEL_STATUS_TIMEOUT:-2}" \
    "$CLONE_TUNNEL_REGISTRY_URL" 2>/dev/null)" || return 1
  python3 -c '
import json, sys
needle = sys.argv[1]
def contains(value):
    if isinstance(value, dict):
        return any(contains(item) for item in value.values())
    if isinstance(value, list):
        return any(contains(item) for item in value)
    return value == needle
raise SystemExit(0 if contains(json.load(sys.stdin)) else 1)
' "$udid" <<<"$response" 2>/dev/null
}

_tunnel_registry_port() {
  python3 -c '
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
    raise SystemExit(1)
try:
    port = parsed.port or 80
except ValueError:
    raise SystemExit(1)
if not 1 <= port <= 65535:
    raise SystemExit(1)
print(port)
' "$CLONE_TUNNEL_REGISTRY_URL" 2>/dev/null
}

_open_xcode_project_for_tunnel() {
  [[ "${CLONE_AUTO_OPEN_XCODE:-1}" == "1" ]] || return 0
  local project="${CLONE_XCODE_PROJECT:-}"
  [[ -n "$project" ]] || return 0
  if [[ ! -e "$project" ]]; then
    echo "ERROR: clone Xcode project does not exist: $project — run 'scripts/clone_workspace.sh prepare' first" >&2
    return 1
  fi
  if ! command -v open >/dev/null 2>&1; then
    echo "ERROR: cannot open the clone Xcode project before RemoteXPC setup — macOS 'open' is unavailable" >&2
    return 1
  fi
  echo "INFO: opening clone Xcode project before RemoteXPC setup: $project" >&2
  if ! open -g -a Xcode "$project" >/dev/null 2>&1; then
    echo "ERROR: Xcode could not open the clone project before RemoteXPC setup: $project" >&2
    return 1
  fi
}

_tunnel_launch_command() {
  local udid="$1" port="$2" appium_bin node_bin appium_home launch_path user_home
  appium_bin="$(command -v appium 2>/dev/null || true)"
  node_bin="$(command -v node 2>/dev/null || true)"
  if [[ -z "$appium_bin" || -z "$node_bin" ]]; then
    echo "ERROR: automatic RemoteXPC setup requires appium and node on PATH" >&2
    return 1
  fi
  appium_home="${APPIUM_HOME:-$HOME/.appium}"
  user_home="$HOME"
  launch_path="$(dirname "$node_bin"):$(dirname "$appium_bin"):/usr/bin:/bin:/usr/sbin:/sbin"
  mkdir -p "$(dirname "$CLONE_TUNNEL_LOG")"
  touch "$CLONE_TUNNEL_LOG"
  python3 -c '
import shlex, sys

appium, path, appium_home, home, udid, port, retry_count, log = sys.argv[1:]
args = [
    "/usr/bin/env", "PATH=" + path, "APPIUM_HOME=" + appium_home, "HOME=" + home,
    appium, "driver", "run", "xcuitest", "tunnel-creation", "--",
    "--udid", udid,
    "--tunnel-registry-port", port,
    "--disconnect-retry-max-attempts", retry_count,
]
print(" ".join(shlex.quote(arg) for arg in args)
      + " >> " + shlex.quote(log) + " 2>&1 </dev/null &")
' "$appium_bin" "$launch_path" "$appium_home" "$user_home" "$udid" "$port" \
    "${CLONE_TUNNEL_RETRY_MAX_ATTEMPTS:-0}" "$CLONE_TUNNEL_LOG"
}

_authorize_tunnel_with_gui() {
  local launch_command="$1" osascript_bin="${CLONE_OSASCRIPT_BIN:-/usr/bin/osascript}"
  local timeout="${CLONE_TUNNEL_AUTH_TIMEOUT:-120}"
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] || timeout=120
  if [[ ! -x "$osascript_bin" ]]; then
    echo "ERROR: macOS administrator authorization is unavailable: $osascript_bin" >&2
    return 1
  fi
  echo "INFO: requesting macOS administrator authorization for the RemoteXPC TUN interface" >&2
  python3 -c '
import subprocess, sys

osascript, command, timeout = sys.argv[1:]
source = """on run argv
  do shell script (item 1 of argv) with administrator privileges
end run
"""
try:
    completed = subprocess.run(
        [osascript, "-", command], input=source, text=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        timeout=int(timeout), check=False,
    )
except subprocess.TimeoutExpired:
    print("ERROR: macOS administrator authorization timed out", file=sys.stderr)
    raise SystemExit(124)
if completed.returncode:
    message = (completed.stderr or "administrator authorization was cancelled").strip().splitlines()[0]
    print("ERROR: RemoteXPC administrator authorization failed: " + message, file=sys.stderr)
raise SystemExit(completed.returncode)
' "$osascript_bin" "$launch_command" "$timeout"
}

_wait_for_tunnel() {
  local udid="$1" tries="${CLONE_TUNNEL_START_TRIES:-60}"
  local interval="${CLONE_TUNNEL_POLL_INTERVAL:-1}" i=0
  [[ "$tries" =~ ^[1-9][0-9]*$ ]] || tries=60
  while [[ "$i" -lt "$tries" ]]; do
    if _tunnel_registry_ready "$udid"; then
      echo "OK: RemoteXPC tunnel ready for $udid" >&2
      return 0
    fi
    sleep "$interval"
    i=$((i + 1))
  done
  return 1
}

# Observed 2026-08-27: authorization succeeded, the elevated tunnel-creation ran
# to completion, and it logged "No USB devices found" — while the same usbmuxd
# enumeration from this shell listed the phone. A root process started from
# osascript has no login session, so usbmuxd shows it nothing. Telling the
# operator to approve a prompt they already approved sends them in a circle.
_tunnel_log_says_usbmux_empty() {
  [[ -r "$CLONE_TUNNEL_LOG" ]] || return 1
  grep -q "No USB devices found" "$CLONE_TUNNEL_LOG" 2>/dev/null
}

_tunnel_manual_command() {
  local udid="$1" port
  port="$(_tunnel_registry_port || true)"
  printf "sudo appium driver run xcuitest tunnel-creation -- --udid '%s'" "$udid"
  [[ -n "$port" ]] && printf ' --tunnel-registry-port %s' "$port"
  return 0
}

_tunnel_manual_help() {
  local udid="$1"
  echo "ERROR: RemoteXPC tunnel is not ready for $udid at $CLONE_TUNNEL_REGISTRY_URL." >&2
  if _tunnel_log_says_usbmux_empty; then
    echo "ERROR: the elevated tunnel process reached usbmuxd but saw no USB device — a root process started outside your login session cannot enumerate it." >&2
    echo "ERROR: run this yourself in Terminal.app and leave it running: $(_tunnel_manual_command "$udid")" >&2
  else
    echo "ERROR: approve the macOS administrator prompt, or run 'sudo -v' once and retry the same skill command." >&2
    echo "ERROR: manual fallback: $(_tunnel_manual_command "$udid")" >&2
  fi
}

_acquire_tunnel_start_lock() {
  local lock="$1" owner=""
  if mkdir "$lock" 2>/dev/null; then
    printf '%s\n' "$$" >"$lock/owner"
    return 0
  fi
  # mkdir is the atomic ownership boundary. The winner writes owner immediately
  # afterwards, but a contender can observe the directory in that tiny window.
  # Treat a missing/empty owner file as held instead of deleting a live lock.
  [[ -s "$lock/owner" ]] || return 1
  read -r owner <"$lock/owner" || return 1
  if [[ "$owner" =~ ^[0-9]+$ ]] && ps -p "$owner" >/dev/null 2>&1; then
    return 1
  fi
  rm -f "$lock/owner" 2>/dev/null || true
  rmdir "$lock" 2>/dev/null || return 1
  mkdir "$lock" 2>/dev/null || return 1
  printf '%s\n' "$$" >"$lock/owner"
}

_start_tunnel() {
  local udid="$1" port launch_command sudo_bin lock launched=0 result=1
  if ! [[ "$udid" =~ ^[A-Za-z0-9-]+$ ]]; then
    echo "ERROR: refusing unsafe RemoteXPC device identifier: $udid" >&2
    return 1
  fi
  port="$(_tunnel_registry_port || true)"
  if [[ -z "$port" ]]; then
    echo "ERROR: automatic RemoteXPC setup only supports a local HTTP registry URL, got $CLONE_TUNNEL_REGISTRY_URL" >&2
    return 1
  fi
  mkdir -p "$CLONE_STATE_DIR"
  lock="$CLONE_STATE_DIR/remotexpc-tunnel-start.lock"
  if ! _acquire_tunnel_start_lock "$lock"; then
    echo "INFO: another device_wda.sh process is starting the RemoteXPC tunnel; waiting" >&2
    if _wait_for_tunnel "$udid"; then return 0; fi
    echo "ERROR: concurrent RemoteXPC startup did not publish $udid within the bounded poll" >&2
    return 1
  fi

  if _tunnel_registry_ready "$udid"; then
    echo "INFO: RemoteXPC tunnel became ready before startup; reusing it" >&2
    result=0
  elif ! _open_xcode_project_for_tunnel; then
    result=1
  elif ! launch_command="$(_tunnel_launch_command "$udid" "$port")"; then
    result=1
  else
    sudo_bin="${CLONE_SUDO_BIN:-$(command -v sudo 2>/dev/null || true)}"
    echo "INFO: starting managed RemoteXPC tunnel for $udid" >&2
    if [[ -n "$sudo_bin" ]] && "$sudo_bin" -n /bin/sh -c "$launch_command" >/dev/null 2>&1; then
      launched=1
    elif [[ "${CLONE_TUNNEL_GUI_AUTH:-1}" == "1" && -z "${CI:-}" ]] \
      && _authorize_tunnel_with_gui "$launch_command"; then
      launched=1
    fi
    if [[ "$launched" -eq 1 ]] && _wait_for_tunnel "$udid"; then
      result=0
    else
      [[ "$launched" -eq 0 ]] \
        && echo "ERROR: automatic RemoteXPC startup could not obtain administrator authorization" >&2
      [[ "$launched" -eq 1 ]] \
        && echo "ERROR: RemoteXPC startup did not publish $udid within the bounded poll — inspect $CLONE_TUNNEL_LOG" >&2
      result=1
    fi
  fi

  rm -f "$lock/owner" 2>/dev/null || true
  rmdir "$lock" 2>/dev/null || true
  return "$result"
}

_ensure_tunnel() {
  local udid="$1"
  _device_requires_tunnel "$udid" || return 0
  if _tunnel_registry_ready "$udid"; then
    echo "INFO: RemoteXPC tunnel ready for $udid" >&2
    return 0
  fi
  if [[ "${CLONE_AUTO_START_TUNNEL:-1}" != "1" ]]; then
    _tunnel_manual_help "$udid"
    return 1
  fi
  if _start_tunnel "$udid"; then return 0; fi
  _tunnel_manual_help "$udid"
  return 1
}

_prepare_wda_bootstrap() {
  [[ "${CLONE_WDA_ISOLATE:-1}" == "1" ]] || return 0

  local appium_home="${APPIUM_HOME:-$HOME/.appium}"
  local source_root="${CLONE_WDA_SOURCE:-${appium_home}/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent}"
  local target_root="${CLONE_WDA_BOOTSTRAP:-$PWD/.autobot/clone/wda}"
  [[ -d "$source_root/WebDriverAgent.xcodeproj" ]] || return 0
  [[ "$target_root" != "$source_root" ]] || return 0

  if [[ ! -d "$target_root/WebDriverAgent.xcodeproj" || "${CLONE_WDA_REFRESH:-0}" == "1" ]]; then
    mkdir -p "$target_root"
    cp -R "$source_root/." "$target_root/"
  fi

  # The scheme's optional post-action may mutate an already-signed Runner.app.
  # A no-op replacement keeps the clone WDA copy deterministic without touching
  # the user's installed Appium package.
  if [[ -f "$target_root/Scripts/embed-runner-icon.sh" ]]; then
    cp "$_HERE/wda_post_action.sh" "$target_root/Scripts/embed-runner-icon.sh"
    chmod +x "$target_root/Scripts/embed-runner-icon.sh"
  fi
  printf '%s' "$target_root"
}

_collect_connected_devices() {
  local line udid state name coredevice
  udids=()
  names=()
  all_names=()
  while IFS= read -r line; do
    [[ "$line" == OK:* ]] || continue
    udid="$(cut -f1 <<<"${line#OK: }")"
    state="$(cut -f2 <<<"${line#OK: }")"
    name="$(cut -f3 <<<"${line#OK: }")"
    coredevice="$(cut -f4 <<<"${line#OK: }")"
    # `paired` is only a trust record — `connected` is the live transport.
    [[ "$state" == "connected" ]] || continue
    all_names+=("$name ($udid)")
    # A selector may be the hardware UDID, a name fragment, or the CoreDevice
    # UUID — the Identifier column of `devicectl list devices`, which is the
    # one a person most likely copied. They look alike; treating the CoreDevice
    # UUID as unmatched used to misdiagnose a connected phone as absent.
    if [[ -n "$want" && "$udid" != "$want" && "$name" != *"$want"* \
          && "$coredevice" != "$want" ]]; then
      continue
    fi
    udids+=("$udid")
    names+=("$name")
  done < <("$_HERE/device_capture.sh" devices)
}

_open_xcode_for_device_recovery() {
  [[ "${CLONE_AUTO_OPEN_XCODE:-1}" == "1" ]] || return 1
  if ! command -v open >/dev/null 2>&1; then
    echo "WARN: cannot open Xcode automatically — macOS 'open' command is unavailable" >&2
    return 1
  fi

  local project="${CLONE_XCODE_PROJECT:-}"
  if [[ -n "$project" && -e "$project" ]]; then
    echo "INFO: no connected iPhone; opening Xcode project to re-establish CoreDevice: $project" >&2
    open -a Xcode "$project" >/dev/null 2>&1 || return 1
  else
    echo "INFO: no connected iPhone; opening Xcode to re-establish CoreDevice" >&2
    open -a Xcode >/dev/null 2>&1 || return 1
  fi
  return 0
}

cmd_device() {
  local want="${1:-}" line udid state name udids=() names=() all_names=()
  _collect_connected_devices

  # Devices ARE connected, the selector just matches none of them. That is a
  # different failure from an empty transport: the CoreDevice tunnel is alive,
  # so opening Xcode to "recover" it answers a question nobody asked while the
  # real mistake — a typo, or a UUID from some other tool — goes unmentioned.
  if [[ "${#udids[@]}" -eq 0 && "${#all_names[@]}" -gt 0 ]]; then
    echo "ERROR: '${want}' matches none of the ${#all_names[@]} connected iPhone(s):" >&2
    for name in "${all_names[@]}"; do
      echo "ERROR:   $name" >&2
    done
    echo "ERROR: pass the hardware UDID, the device name, or the Identifier from 'xcrun devicectl list devices'" >&2
    return 1
  fi

  if [[ "${#udids[@]}" -eq 0 ]] && _open_xcode_for_device_recovery; then
    local timeout="${CLONE_XCODE_RECOVERY_TIMEOUT:-30}" elapsed=0
    if ! [[ "$timeout" =~ ^[0-9]+$ ]]; then
      timeout=30
    fi
    echo "INFO: waiting up to ${timeout}s for a connected physical iPhone" >&2
    while [[ "$elapsed" -lt "$timeout" ]]; do
      sleep 1
      _collect_connected_devices
      [[ "${#udids[@]}" -gt 0 ]] && break
      elapsed=$((elapsed + 1))
    done
  fi

  if [[ "${#udids[@]}" -eq 0 ]]; then
    echo "ERROR: no connected iPhone — plug it in via USB, unlock it, enable Developer Mode, and trust this Mac. If Xcode sees it but this does not, open Xcode > Window > Devices and Simulators once to re-establish the CoreDevice tunnel. Automatic Xcode recovery can be disabled with CLONE_AUTO_OPEN_XCODE=0." >&2
    return 1
  fi
  if [[ "${#udids[@]}" -eq 1 ]]; then
    _persist_device_profile "${udids[0]}" "${names[0]}" || return 1
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

_cached_matching_sid() {
  local udid="$1" bundle_id="$2"
  [[ "${CLONE_SESSION_REUSE:-1}" == "1" && -r "$CLONE_SESSION_FILE" ]] || return 0
  python3 -c '
import json, sys
path, udid, bundle_id, appium_url = sys.argv[1:]
try:
    value = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(0)
if (value.get("udid") == udid and value.get("bundleId") == bundle_id
        and value.get("appiumUrl") == appium_url):
    print(value.get("sid") or "")
' "$CLONE_SESSION_FILE" "$udid" "$bundle_id" "$APPIUM_URL" 2>/dev/null
}

_cached_session_bundle() {
  local sid="$1"
  [[ -r "$CLONE_SESSION_FILE" ]] || return 0
  python3 -c '
import json, sys
path, sid, appium_url = sys.argv[1:]
try:
    value = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(0)
if value.get("sid") == sid and value.get("appiumUrl") == appium_url:
    print(value.get("bundleId") or "")
' "$CLONE_SESSION_FILE" "$sid" "$APPIUM_URL" 2>/dev/null
}

_write_session_descriptor() {
  local sid="$1" udid="$2" bundle_id="$3"
  mkdir -p "$(dirname "$CLONE_SESSION_FILE")"
  python3 -c '
import json, os, sys
path, sid, udid, bundle_id, appium_url = sys.argv[1:]
value = {"sid": sid, "udid": udid, "bundleId": bundle_id, "appiumUrl": appium_url}
tmp = path + ".tmp.%d" % os.getpid()
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(value, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, path)
' "$CLONE_SESSION_FILE" "$sid" "$udid" "$bundle_id" "$APPIUM_URL"
}

_remove_session_descriptor() {
  local sid="$1"
  [[ -e "$CLONE_SESSION_FILE" ]] || return 0
  python3 -c '
import json, os, sys
path, sid, appium_url = sys.argv[1:]
try:
    value = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    value = {}
if value.get("sid") == sid and value.get("appiumUrl") == appium_url:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
' "$CLONE_SESSION_FILE" "$sid" "$APPIUM_URL" 2>/dev/null || true
}

_remote_session_matches() {
  local sid="$1" udid="$2" bundle_id="$3" response
  response="$(_curl "$APPIUM_URL/session/$sid" 2>/dev/null)" || return 1
  python3 -c '
import json, sys
udid, bundle_id = sys.argv[1:]
value = json.load(sys.stdin).get("value", {})
caps = value.get("capabilities", value)
actual_udid = caps.get("appium:udid") or caps.get("udid") or ""
actual_bundle = caps.get("appium:bundleId") or caps.get("bundleId") or ""
raise SystemExit(0 if actual_udid == udid and actual_bundle == bundle_id else 1)
' "$udid" "$bundle_id" <<<"$response" 2>/dev/null
}

_appium_status() {
  local response
  response="$(CLONE_WDA_TIMEOUT="${CLONE_APPIUM_STATUS_TIMEOUT:-2}" \
    _curl "$APPIUM_URL/status" 2>/dev/null)" || return 1
  python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get("value", {})
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if isinstance(value, dict) and value.get("ready") is True else 1)
' <<<"$response" 2>/dev/null
}

_appium_endpoint() {
  python3 -c '
import sys
from urllib.parse import urlparse
value = urlparse(sys.argv[1])
if value.scheme not in ("http", "https") or not value.hostname:
    raise SystemExit(1)
port = value.port or (443 if value.scheme == "https" else 80)
path = value.path.rstrip("/")
print("%s|%s|%s" % (value.hostname, port, path))
' "$APPIUM_URL" 2>/dev/null
}

_managed_appium_pid() {
  local pid=""
  [[ -r "$CLONE_APPIUM_PID_FILE" ]] && read -r pid <"$CLONE_APPIUM_PID_FILE" || true
  [[ "$pid" =~ ^[0-9]+$ ]] && printf '%s' "$pid"
}

_remove_managed_pid() {
  local expected="$1" actual=""
  [[ -r "$CLONE_APPIUM_PID_FILE" ]] && read -r actual <"$CLONE_APPIUM_PID_FILE" || true
  [[ "$actual" == "$expected" ]] && rm -f "$CLONE_APPIUM_PID_FILE"
  return 0
}

_managed_appium_label() {
  local label=""
  [[ -r "$CLONE_APPIUM_LABEL_FILE" ]] && read -r label <"$CLONE_APPIUM_LABEL_FILE" || true
  [[ "$label" =~ ^com\.autobot\.clone\.appium\.[0-9]+\.[0-9]+$ ]] && printf '%s' "$label"
}

_remove_managed_appium_job() {
  local label launchctl_bin
  label="$(_managed_appium_label || true)"
  if [[ -n "$label" ]]; then
    launchctl_bin="${CLONE_LAUNCHCTL_BIN:-$(command -v launchctl 2>/dev/null || true)}"
    [[ -n "$launchctl_bin" ]] && "$launchctl_bin" remove "$label" >/dev/null 2>&1 || true
  fi
  rm -f "$CLONE_APPIUM_LABEL_FILE"
}

_launchctl_job_pid() {
  local launchctl_bin="$1" label="$2"
  "$launchctl_bin" print "gui/$(id -u)/$label" 2>/dev/null \
    | awk '$1 == "pid" && $2 == "=" { print $3; exit }'
}

_start_managed_appium_server() {
  local host="$1" port="$2" base_path="$3"
  local appium_bin node_bin appium_home launch_path launchctl_bin label pid="" i=0
  local pid_tmp label_tmp
  mkdir -p "$CLONE_STATE_DIR" "$(dirname "$CLONE_APPIUM_PID_FILE")" \
    "$(dirname "$CLONE_APPIUM_LABEL_FILE")" "$(dirname "$CLONE_APPIUM_LOG")"
  appium_bin="$(command -v appium 2>/dev/null || true)"
  node_bin="$(command -v node 2>/dev/null || true)"
  if [[ -z "$appium_bin" || -z "$node_bin" ]]; then
    echo "ERROR: managed Appium startup requires appium and node on PATH" >&2
    return 1
  fi
  local server_cmd=("$appium_bin" server --address "$host" --port "$port")
  [[ -n "$base_path" ]] && server_cmd+=(--base-path "$base_path")

  if [[ "${CLONE_APPIUM_USE_LAUNCHCTL:-1}" != "0" ]]; then
    launchctl_bin="${CLONE_LAUNCHCTL_BIN:-$(command -v launchctl 2>/dev/null || true)}"
    if [[ -z "$launchctl_bin" ]]; then
      echo "ERROR: managed Appium startup requires launchctl; set CLONE_AUTO_START_APPIUM=0 and start Appium explicitly" >&2
      return 1
    fi
    label="com.autobot.clone.appium.${port}.$$"
    label_tmp="$CLONE_APPIUM_LABEL_FILE.tmp.$$"
    printf '%s\n' "$label" >"$label_tmp"
    mv "$label_tmp" "$CLONE_APPIUM_LABEL_FILE"
    appium_home="${APPIUM_HOME:-${HOME}/.appium}"
    launch_path="$(dirname "$node_bin"):$(dirname "$appium_bin"):/usr/bin:/bin:/usr/sbin:/sbin"
    if ! "$launchctl_bin" submit -l "$label" -o "$CLONE_APPIUM_LOG" -e "$CLONE_APPIUM_LOG" -- \
      /usr/bin/env "PATH=$launch_path" "APPIUM_HOME=$appium_home" "HOME=${HOME}" "${server_cmd[@]}"; then
      rm -f "$CLONE_APPIUM_LABEL_FILE"
      echo "ERROR: launchctl could not submit managed Appium job $label" >&2
      return 1
    fi
    while [[ "$i" -lt 20 ]]; do
      pid="$(_launchctl_job_pid "$launchctl_bin" "$label" || true)"
      [[ "$pid" =~ ^[0-9]+$ ]] && break
      sleep 0.05
      i=$((i + 1))
    done
    if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
      "$launchctl_bin" remove "$label" >/dev/null 2>&1 || true
      rm -f "$CLONE_APPIUM_LABEL_FILE"
      echo "ERROR: launchctl submitted $label but did not publish its pid" >&2
      return 1
    fi
  else
    nohup "${server_cmd[@]}" >"$CLONE_APPIUM_LOG" 2>&1 </dev/null &
    pid=$!
  fi

  pid_tmp="$CLONE_APPIUM_PID_FILE.tmp.$$"
  printf '%s\n' "$pid" >"$pid_tmp"
  mv "$pid_tmp" "$CLONE_APPIUM_PID_FILE"
  printf '%s' "$pid"
}

_wait_for_appium() {
  local pid="${1:-}" tries="${CLONE_APPIUM_START_TRIES:-30}"
  local interval="${CLONE_APPIUM_POLL_INTERVAL:-1}" i=0
  [[ "$tries" =~ ^[0-9]+$ ]] || tries=30
  while [[ "$i" -lt "$tries" ]]; do
    _appium_status && return 0
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    sleep "$interval"
    i=$((i + 1))
  done
  return 1
}

_appium_port_in_use() {
  local host="$1" port="$2"
  python3 -c '
import socket, sys
try:
    sock = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.2)
except OSError:
    raise SystemExit(1)
sock.close()
' "$host" "$port" 2>/dev/null
}

_ensure_appium() {
  _appium_status && return 0
  if [[ "${CLONE_AUTO_START_APPIUM:-1}" != "1" ]]; then
    echo "ERROR: Appium did not answer at $APPIUM_URL and automatic start is disabled (CLONE_AUTO_START_APPIUM=0)" >&2
    return 1
  fi

  mkdir -p "$CLONE_STATE_DIR" "$(dirname "$CLONE_APPIUM_PID_FILE")" \
    "$(dirname "$CLONE_APPIUM_LABEL_FILE")" "$(dirname "$CLONE_APPIUM_LOG")"
  local pid endpoint host port base_path lock="$CLONE_APPIUM_PID_FILE.lock"
  pid="$(_managed_appium_pid || true)"
  if [[ -n "$pid" && -e "$CLONE_APPIUM_PID_FILE" ]]; then
    if kill -0 "$pid" 2>/dev/null; then
      echo "INFO: managed Appium process $pid is still starting; waiting instead of launching a duplicate" >&2
      if _wait_for_appium "$pid"; then return 0; fi
      echo "ERROR: managed Appium process $pid did not become ready at $APPIUM_URL — inspect $CLONE_APPIUM_LOG" >&2
      return 1
    fi
    _remove_managed_appium_job
    _remove_managed_pid "$pid"
  fi

  if ! mkdir "$lock" 2>/dev/null; then
    echo "INFO: another device_wda.sh process is starting Appium; waiting" >&2
    if _wait_for_appium ""; then return 0; fi
    echo "ERROR: concurrent Appium startup did not become ready within the bounded poll" >&2
    return 1
  fi
  if _appium_status; then
    rmdir "$lock" 2>/dev/null || true
    return 0
  fi

  endpoint="$(_appium_endpoint || true)"
  if [[ -z "$endpoint" ]]; then
    rmdir "$lock" 2>/dev/null || true
    echo "ERROR: APPIUM_URL must be a valid HTTP URL, got '$APPIUM_URL'" >&2
    return 1
  fi
  IFS='|' read -r host port base_path <<<"$endpoint"
  case "$host" in
    127.0.0.1|localhost|::1) ;;
    *)
      rmdir "$lock" 2>/dev/null || true
      echo "ERROR: refusing to auto-start Appium for non-local URL $APPIUM_URL — start that server explicitly or set a local APPIUM_URL" >&2
      return 1
      ;;
  esac
  if _appium_port_in_use "$host" "$port"; then
    rmdir "$lock" 2>/dev/null || true
    echo "INFO: port $port is already occupied; waiting for its Appium /status instead of starting a duplicate" >&2
    if _wait_for_appium ""; then return 0; fi
    echo "ERROR: port $port is occupied but does not expose a ready Appium /status" >&2
    return 1
  fi
  if ! command -v appium >/dev/null 2>&1; then
    rmdir "$lock" 2>/dev/null || true
    echo "ERROR: appium binary not found — install it with 'npm i -g appium'" >&2
    return 1
  fi

  if ! pid="$(_start_managed_appium_server "$host" "$port" "$base_path")"; then
    rmdir "$lock" 2>/dev/null || true
    return 1
  fi
  rmdir "$lock" 2>/dev/null || true
  echo "INFO: started managed Appium server pid $pid; log $CLONE_APPIUM_LOG" >&2
  if _wait_for_appium "$pid"; then return 0; fi

  _remove_managed_appium_job
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  _remove_managed_pid "$pid"
  echo "ERROR: Appium did not become ready at $APPIUM_URL within the bounded poll — inspect $CLONE_APPIUM_LOG" >&2
  return 1
}

cmd_stop_server() {
  local pid label process_command tries="${CLONE_APPIUM_STOP_TRIES:-20}" i=0
  pid="$(_managed_appium_pid || true)"
  label="$(_managed_appium_label || true)"
  if [[ -z "$pid" ]]; then
    if [[ -n "$label" ]]; then
      _remove_managed_appium_job
      echo "OK: stopped managed Appium job $label"
      return 0
    fi
    echo "INFO: no Appium server managed by device_wda.sh"
    return 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    _remove_managed_appium_job
    _remove_managed_pid "$pid"
    echo "INFO: removed stale managed Appium pid $pid"
    return 0
  fi
  process_command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$process_command" in
    *appium*|*Appium*) ;;
    *)
      echo "ERROR: refusing to stop pid $pid because it no longer looks like Appium: ${process_command:-unknown command}" >&2
      return 1
      ;;
  esac
  if [[ -n "$label" ]]; then
    _remove_managed_appium_job
  else
    kill "$pid" 2>/dev/null || true
  fi
  [[ "$tries" =~ ^[0-9]+$ ]] || tries=20
  while kill -0 "$pid" 2>/dev/null && [[ "$i" -lt "$tries" ]]; do
    sleep 0.25
    i=$((i + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: managed Appium pid $pid did not stop; inspect it before retrying" >&2
    return 1
  fi
  _remove_managed_pid "$pid"
  echo "OK: stopped managed Appium server $pid"
}

cmd_session() {
  local udid="${1:-}" bundle_id="${2:-}" team body sid err wda_bootstrap cached_sid
  if [[ -z "$udid" || -z "$bundle_id" ]]; then
    echo "ERROR: usage: device_wda.sh session <udid> <bundle_id>" >&2
    echo "ERROR:   <bundle_id> is the installed target app identifier; do not rely on whichever app is foreground." >&2
    return 1
  fi
  cached_sid="$(_cached_matching_sid "$udid" "$bundle_id" || true)"
  if [[ -n "$cached_sid" ]]; then
    _ensure_appium || return 1
    if _remote_session_matches "$cached_sid" "$udid" "$bundle_id"; then
      _tune_session "$cached_sid"
      echo "OK: reusing live WDA session on $udid (target $bundle_id)" >&2
      echo "$cached_sid"
      return 0
    fi
    echo "INFO: cached WDA session $cached_sid is stale; creating a replacement" >&2
    _remove_session_descriptor "$cached_sid"
  fi
  team="$(_team)"
  if [[ -z "$team" ]]; then
    echo "ERROR: no signing team — export DEVELOPMENT_TEAM=<10-char team id> (WDA must be signed to install on a real device)" >&2
    return 1
  fi
  _ensure_tunnel "$udid" || return 1
  _ensure_appium || return 1
  wda_bootstrap="$(_prepare_wda_bootstrap || true)"
  # Building + installing WDA on first run takes minutes; later runs reattach.
  body="$(python3 -c "
import json, os, sys
caps = {
    'platformName': 'iOS',
    'appium:automationName': 'XCUITest',
    'appium:udid': sys.argv[1],
    'appium:bundleId': sys.argv[3],
    'appium:xcodeOrgId': sys.argv[2],
    'appium:xcodeSigningId': 'Apple Development',
    'appium:newCommandTimeout': 900,
    'appium:wdaLaunchTimeout': 420000,
    'appium:wdaConnectionTimeout': 420000,
    'appium:shouldTerminateApp': False,
    'appium:noReset': True,
    # code 65 is opaque on its own; this puts the real xcodebuild error in the
    # Appium log. Always on: the log is a file, not the console, and a failed
    # real-device session is expensive to reproduce — asking for a re-run with
    # CLONE_WDA_DEBUG=1 throws away the one run that had the answer.
    'appium:showXcodeLog': True,
}
if sys.argv[4]:
    caps.update({
        'appium:bootstrapPath': sys.argv[4],
        'appium:agentPath': os.path.join(sys.argv[4], 'WebDriverAgent.xcodeproj'),
    })
print(json.dumps({'capabilities': {'alwaysMatch': caps}}))" "$udid" "$team" "$bundle_id" "$wda_bootstrap")"

  # NOT _curl: `-f` throws the response body away on a non-2xx, and Appium puts
  # the actual reason (WDA build log, automation-mode timeout, bad caps) in the
  # body of a 500. Losing it turns every session failure into "unreachable".
  err="$(_curl_keep_body -X POST "$APPIUM_URL/session" \
         -H 'Content-Type: application/json' -d "$body" 2>&1)" || true
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
        hint = (' — WDA failed to build/sign or its runner failed to start. Check'
                ' DEVELOPMENT_TEAM and that the device is unlocked. Most common cause:'
                ' Settings > Developer > Enable UI Automation is OFF.')
    print('ERROR: WDA session failed: %s%s' % (msg, hint), file=sys.stderr)
" <<<"$err")"
  if [[ -z "$sid" && -f "$CLONE_APPIUM_LOG" ]]; then
    # showXcodeLog is on, so the real diagnostic is already in the log — print it
    # instead of asking for a re-run that costs another real-device session.
    # The log survives across attempts, so scope to the last xcodebuild invocation —
    # otherwise a stale failure gets reported as this run's cause.
    local xcode_err
    xcode_err="$(awk '/Beginning test with command/ {buf=""} {buf = buf $0 ORS} END {printf "%s", buf}' \
                   "$CLONE_APPIUM_LOG" \
                 | grep -aE 'error:|Testing failed|Failing tests|\*\* (TEST|BUILD) FAILED' \
                 | tail -12 || true)"
    if [[ -n "$xcode_err" ]]; then
      echo "ERROR: xcodebuild diagnostics from $CLONE_APPIUM_LOG:" >&2
      sed 's/^/ERROR:   /' <<<"$xcode_err" >&2
    else
      echo "ERROR: no xcodebuild diagnostic matched in $CLONE_APPIUM_LOG — read it directly" >&2
    fi
  fi
  if [[ -z "$sid" ]]; then
    return 1
  fi
  if ! _write_session_descriptor "$sid" "$udid" "$bundle_id"; then
    echo "ERROR: WDA session started but its descriptor could not be saved at $CLONE_SESSION_FILE" >&2
    return 1
  fi
  _tune_session "$sid"
  echo "OK: WDA session on $udid (target $bundle_id)" >&2
  echo "$sid"
}

# Clone runs its own settle loop (sig polling in _perform_tap_and_settle), so
# WDA-level idle/animation waits before every action and /source are pure
# double-waiting — on animation-heavy apps each one costs up to the full
# 10s driver default. Applied to new AND reused sessions (settings live per
# session). Failures only warn: tuning is advisory, never a session gate.
# ponytail: waitForIdleTimeout=0 assumes our settle loop is the only sync;
# raise CLONE_WDA_IDLE_TIMEOUT if a target app misbehaves without idle waits.
_tune_session() {
  local sid="$1" settings
  [[ "${CLONE_WDA_TUNE:-1}" == "0" ]] && return 0
  settings="$(python3 -c "
import json, os
def num(name, default):
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
s = {
    'waitForIdleTimeout': num('CLONE_WDA_IDLE_TIMEOUT', 0),
    'animationCoolOffTimeout': num('CLONE_WDA_ANIM_COOLOFF', 0),
}
# Off by default: lowering snapshot depth trades away exactly the deep tree
# the measurement step depends on. Knob only, for very large hierarchies.
depth = num('CLONE_WDA_SNAPSHOT_MAX_DEPTH', 0)
if depth > 0:
    s['snapshotMaxDepth'] = depth
print(json.dumps({'settings': s}))" 2>/dev/null)" || settings=""
  if [[ -z "$settings" ]]; then
    echo "WARN: could not build WDA performance settings — continuing untuned" >&2
    return 0
  fi
  if _curl -X POST "$APPIUM_URL/session/$sid/appium/settings" \
       -H 'Content-Type: application/json' -d "$settings" >/dev/null 2>&1; then
    echo "INFO: applied WDA performance settings $settings" >&2
  else
    echo "WARN: could not apply WDA performance settings — continuing untuned" >&2
  fi
  return 0
}

_capture_screenshot() {
  local sid="$1" out="$2"
  _curl "$APPIUM_URL/session/$sid/screenshot" | python3 -c "
import base64, json, sys
open(sys.argv[1], 'wb').write(base64.b64decode(json.load(sys.stdin)['value']))" "$out"
}

cmd_screen() {
  local sid="${1:-}" outdir="${2:-}" name="${3:-}"
  if [[ -z "$sid" || -z "$outdir" || -z "$name" ]]; then
    echo "ERROR: usage: device_wda.sh screen <sid> <outdir> <name>" >&2
    return 1
  fi
  _assert_target "$sid" || return 1
  mkdir -p "$outdir"
  local png="$outdir/$name.png" xml="$outdir/$name.xml" base="$APPIUM_URL/session/$sid"
  if ! _capture_screenshot "$sid" "$png"; then
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
  # The tree and every command below speak POINTS; the .png is in PIXELS at the
  # device's scale factor. An agent that reads a coordinate off the screenshot
  # has to convert, and a missed conversion silently lands the gesture somewhere
  # else entirely — measured 2026-08-27: a sheet handle at 307pt was computed as
  # 240pt, which is the scrim above the sheet, so two dismiss attempts did
  # nothing and the exploration was abandoned on a screen that was one drag from
  # continuing. State the frame and the factor instead of leaving it to be
  # inferred, and prefer `swipefrac`, which has no units to get wrong.
  _report_geometry "$xml" "$png"
  local key
  key="$(_key_of "$xml" || true)"
  if [[ -n "$key" ]]; then
    echo "INFO: nodekey $key"
    # The skill tells the agent to judge "same screen?" by statekey, so statekey
    # has to be on stdout. It was only ever written to the flow log.
    echo "INFO: statekey $(_state_of "$xml" 2>/dev/null || echo '?')"
    _flow_event screen "node=$key" "statekey=$(_state_of "$xml")" \
      "sig=$(_sig_of "$xml")" "name=$name" "tree=$xml" "png=$png"
  fi
  echo "OK: captured $png + $xml"
}

# The one tap that does not come from `candidates`. See device_a11y.py:back —
# an unlabelled chevron is invisible to a label-based guard, and a detail screen
# whose only exit is that chevron is a dead end the loop walked into itself.
# The slot's meaning is a platform convention (back/close/cancel), never a
# purchase and never a delete, and this stays a deliberate command so nothing
# reaches it by accident.
cmd_back() {
  local sid="${1:-}"
  if [[ -z "$sid" ]]; then
    echo "ERROR: usage: device_wda.sh back <sid>" >&2
    return 1
  fi
  _assert_target "$sid" || return 1
  local live target x y
  live="$(mktemp -t device_wda)"
  if ! _live_dump "$sid" "$live"; then
    rm -f "$live"
    echo "ERROR: cannot read the current screen — session dead or device gone. Stop the loop." >&2
    return 1
  fi
  target="$(python3 "$_HERE/device_a11y.py" back "$live" | sed -n 's/^INFO: back \([0-9][0-9]*\) \([0-9][0-9]*\) .*/\1 \2/p')"
  # The settle loop reads the same origin state `_prepare_tap` would have set;
  # this path skips that gate on purpose, not its bookkeeping.
  _TAP_PLANNED="$(_sig_of "$live" || true)"
  _TAP_FROM_KEY="$(_key_of "$live" || true)"
  _TAP_FROM_STATE="$(_state_of "$live" || true)"
  _TAP_BEHAVIOR="back"
  _TAP_EFFECT="none"
  rm -f "$live"
  if [[ -z "$target" ]]; then
    echo "INFO: no leading nav control on this screen — this is a tab root, or the exit is elsewhere" >&2
    return 1
  fi
  # shellcheck disable=SC2086
  set -- $target
  x="$1"; y="$2"
  local to_tree settle=0
  to_tree="$(mktemp -t device_wda)"
  _TAP_LABEL="back"
  _perform_tap_and_settle "$sid" "$x" "$y" "$to_tree" || settle=$?
  rm -f "$to_tree"
  if [[ "$settle" -ne 0 ]]; then
    echo "ERROR: back tap at $x,$y did not settle" >&2
    return 1
  fi
  local landed=""
  if ! landed="$(_landed_elsewhere "$sid")"; then
    _TAP_TO_KEY=""
    _TAP_TO_STATE=""
    _TAP_CHANGED=false
    _record_tap_transition "$x" "$y" "left_app=$landed" "evidence=foreign-app" "via=back"
    echo "ERROR: the leading nav control left the app for $landed — re-activate the target" >&2
    return 3
  fi
  _record_tap_transition "$x" "$y" "via=back"
  echo "OK: back tapped $x,$y"
  [[ "$_TAP_CHANGED" == true ]] || echo "INFO: screen did not change — that slot was not a back control"
}

cmd_swipefrac() {
  local sid="${1:-}" fx1="${2:-}" fy1="${3:-}" fx2="${4:-}" fy2="${5:-}" tree="${6:-}"
  if [[ -z "$sid" || -z "$fx1" || -z "$fy1" || -z "$fx2" || -z "$fy2" ]]; then
    echo "ERROR: usage: device_wda.sh swipefrac <sid> <fx1> <fy1> <fx2> <fy2> [tree.xml]" >&2
    echo "ERROR:   Fractions of the app frame, 0..1 — 0.5 0.36 0.5 0.95 drags from" >&2
    echo "ERROR:   just over a third down the screen to near the bottom." >&2
    return 1
  fi
  local frame live=""
  if [[ -n "$tree" && -f "$tree" ]]; then
    frame="$(_app_frame "$tree")"
  else
    live="$(mktemp -t device_wda)"
    if _live_dump "$sid" "$live"; then frame="$(_app_frame "$live")"; fi
    rm -f "$live"
  fi
  if [[ -z "$frame" ]]; then
    echo "ERROR: cannot read the app frame — capture with 'screen' first, or pass its tree" >&2
    return 1
  fi
  # shellcheck disable=SC2086
  set -- $frame
  local x="$1" y="$2" w="$3" h="$4" pts
  if ! pts="$(python3 -c "
import sys
x, y, w, h = (float(v) for v in sys.argv[1:5])
fr = [float(v) for v in sys.argv[5:9]]
if not all(0.0 <= f <= 1.0 for f in fr):
    sys.exit('ERROR: fractions must be within 0..1')
print(' '.join(str(int(round(o + s * f)))
                for o, s, f in ((x, w, fr[0]), (y, h, fr[1]), (x, w, fr[2]), (y, h, fr[3]))))
" "$x" "$y" "$w" "$h" "$fx1" "$fy1" "$fx2" "$fy2")"; then
    echo "$pts" >&2
    return 1
  fi
  echo "INFO: swipefrac $fx1,$fy1 -> $fx2,$fy2 of ${w}x${h}pt = $pts" >&2
  # shellcheck disable=SC2086
  cmd_swipe "$sid" $pts
}

# Point-space frame of the app, as `<x> <y> <w> <h>`, from a captured tree.
_app_frame() {
  python3 - "$1" <<'PY' 2>/dev/null
import sys, xml.etree.ElementTree as ET
for node in ET.parse(sys.argv[1]).getroot().iter():
    if (node.get("type") or node.tag).endswith("Application"):
        try:
            print(" ".join(str(int(float(node.get(k, 0) or 0)))
                            for k in ("x", "y", "width", "height")))
        except ValueError:
            pass
        break
PY
}

_report_geometry() {
  local xml="$1" png="$2" frame px
  frame="$(_app_frame "$xml")" || return 0
  [[ -n "$frame" ]] || return 0
  # shellcheck disable=SC2086
  set -- $frame
  px="$(python3 -c "
import struct, sys
with open(sys.argv[1], 'rb') as fh:
    head = fh.read(33)
print('%dx%d' % struct.unpack('>II', head[16:24]) if head[:8] == b'\x89PNG\r\n\x1a\n' else '')
" "$png" 2>/dev/null || true)"
  echo "INFO: bounds ${3}x${4} pt at ${1},${2}${px:+ | screenshot $px px}"
  if [[ -n "$px" && "$3" -gt 0 ]]; then
    echo "INFO: scale $(python3 -c "print(round(${px%%x*} / $3, 2))")x — screenshot px / this = points."
  fi
  echo "INFO: swipe coordinates are POINTS. Prefer 'swipefrac' (fractions of this frame) over converting from the screenshot."
}

# Cumulative taps already spent on this target, from the flow log.
_taps_spent() {
  local flow="${1:-${CLONE_FLOW_LOG:-$CLONE_STATE_DIR/flow.jsonl}}" n
  [[ -s "$flow" ]] || { echo 0; return 0; }
  # Fail CLOSED on a log this cannot read. A skipped bad line silently lowers
  # the count, which raises the real ceiling on someone's account — and
  # device_flow.py rejects the same log outright, so a run that kept tapping
  # here could not be resumed or audited anyway.
  n="$(python3 -c '
import json, sys
n = 0
for number, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    try:
        n += json.loads(line).get("type") == "tap"
    except ValueError:
        sys.exit("unreadable line %d" % number)
print(n)' "$flow" 2>/dev/null)" || n=""
  if [[ ! "$n" =~ ^[0-9]+$ ]]; then
    echo "ERROR: cannot read the flow log '$flow' — the tap budget cannot be counted." >&2
    echo "ERROR:   fix or remove it; exploring past an unreadable log is untracked." >&2
    echo "-1"
    return 0
  fi
  echo "$n"
}

# The budget is CUMULATIVE taps on someone's real account, so it has to bind
# every path that taps — not just the mechanical drainer. The skill's own loop
# uses low-level `tap`, so a budget enforced only in `explore` was a budget the
# actual /autobot:copy run never met.
_budget_allows() {
  local need="${1:-1}" budget="${CLONE_TAP_BUDGET:-25}" spent
  # A revert is not exploration, it is putting something back. Refusing it on
  # a spent budget leaves the user's switch flipped — worse than the tap the
  # budget was protecting them from.
  if [[ "${_FLOW_BROKEN:-0}" == "1" ]]; then
    echo "ERROR: a previous tap could not be logged — the budget cannot bind. Stop." >&2
    return 1
  fi
  if [[ "${_TAP_REVERTING:-0}" == "1" ]]; then
    return 0
  fi
  spent="$(_taps_spent)"
  if [[ "$spent" -lt 0 ]]; then
    return 1
  fi
  if [[ $(( spent + need )) -gt "$budget" ]]; then
    echo "ERROR: tap budget spent ($spent/$budget cumulative, this action needs $need) — stop exploring." >&2
    echo "ERROR:   raise CLONE_TAP_BUDGET, or clear the flow log to start a new target." >&2
    return 1
  fi
  return 0
}

_actions() {
  local sid="$1" payload="$2"
  if ! _curl -X POST "$APPIUM_URL/session/$sid/actions" -H 'Content-Type: application/json' \
       -d "$payload" >/dev/null 2>&1; then
    echo "ERROR: input failed — session dead, device locked, or unplugged. Stop the loop." >&2
    return 1
  fi
}

# XCUITest's active-app detection is the final target guard. A WDA session can
# outlive a permission dialog, SpringBoard, or a user switching apps, so the
# session's bundle capability alone is not enough for every subsequent action.
_session_target() {
  local sid="$1"
  _curl "$APPIUM_URL/session/$sid" | python3 -c '
import json, sys
caps = json.load(sys.stdin).get("value", {})
caps = caps.get("capabilities", caps)
print(caps.get("appium:bundleId") or caps.get("bundleId") or "")
' 2>/dev/null
}

_active_target() {
  local sid="$1"
  _curl -X POST "$APPIUM_URL/session/$sid/execute/sync" \
    -H 'Content-Type: application/json' \
    -d '{"script":"mobile: activeAppInfo","args":[]}' | python3 -c '
import json, sys
value = json.load(sys.stdin).get("value", {})
print(value.get("bundleId", "") if isinstance(value, dict) else "")
' 2>/dev/null
}

# Bring the target app back to the front. Leaving it is a normal consequence of
# tapping a link (Threads offers "Instagram으로 전환"), so it must not end a run.
_reactivate_target() {
  local sid="$1" expected
  expected="$(_cached_session_bundle "$sid" || _session_target "$sid" || true)"
  if [[ -z "$expected" ]]; then
    echo "ERROR: cannot tell which app to re-activate — stop and inspect the WDA session" >&2
    return 1
  fi
  _curl -X POST "$APPIUM_URL/session/$sid/execute/sync" \
    -H 'Content-Type: application/json' \
    -d "$(printf '{"script":"mobile: activateApp","args":[{"bundleId":"%s"}]}' "$expected")" \
    >/dev/null 2>&1 || true
  local waited=0
  while [[ "$waited" -lt "${CLONE_REACTIVATE_TRIES:-10}" ]]; do
    sleep 0.4
    waited=$((waited + 1))
    [[ "$(_active_target "$sid" || true)" == "$expected" ]] && {
      echo "INFO: re-activated $expected after leaving the app" >&2
      return 0
    }
  done
  echo "ERROR: could not bring $expected back to the foreground" >&2
  return 1
}

# Put the app back at its launch screen.
#
# Exploration walks forward and has no way back: `next-tap` routes only through
# transitions it has already OBSERVED, so from a screen deep in Settings there is
# no known route to the 37 screens that still hold candidates. Measured
# 2026-08-23 — the run stopped there with 422 of 522 targets untouched, and the
# reproduction inherited that: most of its buttons did nothing because nothing
# was ever seen to happen. Relaunching costs one app start and reopens the map.
_restart_target() {
  local sid="$1" expected
  expected="$(_cached_session_bundle "$sid" || _session_target "$sid" || true)"
  if [[ -z "$expected" ]]; then
    echo "ERROR: cannot tell which app to restart — stop and inspect the WDA session" >&2
    return 1
  fi
  _curl -X POST "$APPIUM_URL/session/$sid/execute/sync" \
    -H 'Content-Type: application/json' \
    -d "$(printf '{"script":"mobile: terminateApp","args":[{"bundleId":"%s"}]}' "$expected")" \
    >/dev/null 2>&1 || true
  sleep "${CLONE_RESTART_SETTLE:-1}"
  _reactivate_target "$sid"
}

_assert_target() {
  local sid="$1" expected actual
  expected="$(_cached_session_bundle "$sid" || true)"
  [[ -n "$expected" ]] || expected="$(_session_target "$sid" || true)"
  actual="$(_active_target "$sid" || true)"
  if [[ -z "$expected" || -z "$actual" ]]; then
    echo "ERROR: cannot prove the active Appium app (expected '$expected', active '$actual') — stop and inspect the WDA session" >&2
    return 1
  fi
  if [[ "$expected" != "$actual" ]]; then
    echo "ERROR: target app is not foreground (expected $expected, active $actual) — re-activate the target and re-capture" >&2
    return 1
  fi
  echo "INFO: active target $actual" >&2
}

# Dump the CURRENT screen's tree to $1. Callers derive sig/nodekey from it —
# one HTTP round trip for both, since the settle poll below runs it repeatedly.
_live_dump() {
  local sid="$1" out="$2"
  _curl "$APPIUM_URL/session/$sid/source" | python3 -c "
import json, sys
open(sys.argv[1], 'w', encoding='utf-8').write(json.load(sys.stdin)['value'])" "$out" 2>/dev/null
}

_key_of() { python3 "$_HERE/device_a11y.py" nodekey "$1" | sed -n 's/^INFO: nodekey //p'; }
_state_of() { python3 "$_HERE/device_a11y.py" statekey "$1" | sed -n 's/^INFO: statekey //p'; }
_sig_of() { python3 "$_HERE/device_a11y.py" sig "$1" | sed -n 's/^INFO: sig //p'; }
_identity_of() { python3 "$_HERE/device_a11y.py" identity "$1"; }

# Did anything actually MOVE between two captures? A scroll shifts the elements
# that survive it; a like counter ticking up changes text in place. Only the
# former is a screen transition worth demanding arrival evidence for.
# Exit 0 moved, 1 did not move, 2 could not tell — the caller must not fold 2
# into 1, or an unreadable tree silently becomes "the swipe did nothing".
_elements_moved() {
  python3 -c "
import sys
sys.path.insert(0, sys.argv[1])
try:
    import device_a11y
    def by_label(path):
        out = {}
        for e in device_a11y.load(path):
            if e['label'] and e['frame']['width'] > 0:
                out.setdefault(e['label'], []).append(round(e['frame']['y']))
        return out
    before, after = by_label(sys.argv[2]), by_label(sys.argv[3])
except Exception as exc:
    print(f'cannot compare captures: {exc}', file=sys.stderr)
    sys.exit(2)
shared = set(before) & set(after)
moved = [k for k in shared if sorted(before[k]) != sorted(after[k])]
# No shared labels at all means the screen was replaced outright, not scrolled.
sys.exit(0 if moved or not shared else 1)
" "$_HERE" "$1" "$2"
}

# One line per event in a FIXED location, so `device_flow.py` can read the run
# back — for the flow map, for the coverage report, and to resume exploration
# after the session dies (which, on a real phone, is the normal ending).
# Logging NEVER changes the verdict of the action it logs. A tap that physically
# happened must not report failure because the log path was unwritable — the
# exploration loop would retry it and double-tap a real phone.
_flow_event() {
  if _flow_write "$@"; then
    return 0
  fi
  # A tap that is not recorded is a tap the cumulative budget cannot see. The
  # count comes from this log, so a silent write failure means the ceiling
  # quietly stops existing — the run keeps tapping someone's real account with
  # no limit and nothing to audit or resume from. A screen capture failing to
  # log is only lost evidence; a tap failing to log is a lost guard rail.
  if [[ "${1:-}" == "tap" ]]; then
    # Do not fail the call: the tap already happened, and reporting it as a
    # failure would not undo it. Fail the NEXT one — that is the tap the budget
    # can still stop.
    echo "ERROR: could not append this tap to ${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}" >&2
    echo "ERROR:   the tap budget is counted from that log, so no further tap is allowed." >&2
    _FLOW_BROKEN=1
    return 0
  fi
  echo "WARN: could not append to the exploration log (${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}) — flow map and resume will be incomplete"
}

_flow_write() {
  CLONE_FLOW_LOG="${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}" python3 -c "
import json, os, sys
from datetime import datetime, timezone
path = os.environ['CLONE_FLOW_LOG']
event = dict(a.split('=', 1) for a in sys.argv[2:])
event['type'] = sys.argv[1]
event['at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
with open(path, 'a', encoding='utf-8') as fh:
    fh.write(json.dumps(event, ensure_ascii=False) + '\n')
" "$@"
}

# Guard rejections return 2, not 1: nothing has been tapped yet at that point, so
# the caller may re-capture and retry. Everything after the tap returns 1, which
# is fatal — retrying a tap that already landed double-taps a real phone.
_prepare_tap() {
  local sid="$1" x="$2" y="$3" tree="$4" live_tree live_state candidate_output
  _assert_target "$sid" || return 1
  # (1) Freshness: read what is on the device RIGHT NOW, once, and reuse it.
  live_tree="$(mktemp -t device_wda)"
  if ! _live_dump "$sid" "$live_tree"; then
    rm -f "$live_tree"
    echo "ERROR: cannot read the current screen — session dead or device gone. Stop the loop." >&2
    return 1
  fi
  # Identity is `statekey`, NOT `sig`. `sig` hashes the label set, so on any live
  # feed it changes within seconds without the screen moving at all — measured on
  # Threads: a like count ticked 226 -> 227 and every candidate was rejected, so
  # exploration made 0 steps. statekey held across that same churn. It is also
  # strictly safer than nodekey here: nodekey ignores modal contents, so a sheet
  # that opened between capture and tap would not register.
  _TAP_FROM_STATE="$(_state_of "$tree" 2>/dev/null || true)"
  live_state="$(_state_of "$live_tree" 2>/dev/null || true)"
  if [[ -z "$_TAP_FROM_STATE" || "$_TAP_FROM_STATE" != "$live_state" ]]; then
    rm -f "$live_tree"
    echo "ERROR: screen changed since $(basename "$tree") (planned ${_TAP_FROM_STATE:-?}, live ${live_state:-?}) — do NOT tap stale coordinates. Re-capture with 'screen' and pick from fresh candidates." >&2
    return 2
  fi
  # (2) Provenance against the LIVE tree, not the capture: the point must still be
  # a target the screen offers now. This also runs the withheld check against what
  # is actually on screen, which validating the stale capture did not.
  if ! python3 "$_HERE/device_a11y.py" verify "$live_tree" "$x" "$y"; then
    rm -f "$live_tree"
    return 2
  fi
  _TAP_PLANNED="$(_sig_of "$live_tree" || true)"
  _TAP_FROM_KEY="$(_key_of "$tree" 2>/dev/null || true)"
  candidate_output="$(python3 "$_HERE/device_a11y.py" candidates "$live_tree")"
  rm -f "$live_tree"
  _TAP_LABEL="$(awk -v k="INFO: tap $x $y " \
    'index($0, k) == 1 { sub(/^[^|]*\| [^|]*\| /, ""); print; exit }' <<<"$candidate_output")"
  _TAP_BEHAVIOR="$(awk -v k="INFO: candidate-meta $x $y " '
    index($0, k) == 1 {
      count = split($0, parts, "behavior=")
      if (count > 1) { split(parts[2], tail, " | "); print tail[1] }
      exit
    }
  ' <<<"$candidate_output")"
  _TAP_EFFECT="$(awk -v k="INFO: candidate-meta $x $y " '
    index($0, k) == 1 {
      count = split($0, parts, "effect=")
      if (count > 1) { split(parts[2], tail, " | "); print tail[1] }
      exit
    }
  ' <<<"$candidate_output")"
}

_perform_tap_and_settle() {
  local sid="$1" x="$2" y="$3" to_tree="$4"
  local require_source="${5:-0}" tries="${CLONE_TAP_SETTLE_TRIES:-10}" i=0
  [[ "$tries" =~ ^[0-9]+$ ]] || tries=10
  [[ "$require_source" != "1" || "$tries" -gt 0 ]] || tries=1
  # EVERY tap path lands here — `tap`, `step`, `back`, and explore's inner loop.
  # The budget lived on `cmd_tap` alone, so `step` walked around it, and the
  # skill's own docs said the two were interchangeable. A limit on someone's
  # real account has to bind the action, not one spelling of it.
  #
  # A toggle costs TWO: the flip and the flip back. Allowing the forward tap
  # with one left meant the revert hit the ceiling and the run ended with the
  # user's setting changed — the first version of this check did exactly that.
  local _need=1
  [[ "${_TAP_EFFECT:-}" == toggle ]] && _need=2
  _budget_allows "$_need" || return 1
  _TAP_TO_SIG="$_TAP_PLANNED"
  _TAP_TO_KEY=""
  _TAP_TO_STATE=""
  _TAP_CHANGED=false
  rm -f "$to_tree"
  if ! _actions "$sid" "$(printf '{"actions":[{"type":"pointer","id":"finger1","parameters":{"pointerType":"touch"},"actions":[{"type":"pointerMove","duration":0,"x":%s,"y":%s},{"type":"pointerDown","button":0},{"type":"pause","duration":60},{"type":"pointerUp","button":0}]}]}' "$x" "$y")"; then
    return 1
  fi

  # (3) Poll into the caller-owned file. The last successful dump is the final
  # settle source and is reused directly by `step`; there is no post-settle GET.
  #
  # Two exits, not one. "The screen changed" ends the poll early; so must "the
  # screen is the same and has stopped moving". With only the first, a tap that
  # did nothing ran every poll to the bound — ten WDA dumps, ~20s — and a run
  # has dozens of those (measured 2026-08-23: p90 26.8s against a 4.5s median,
  # all no-op taps). Three identical consecutive dumps is the same rule the
  # swipe settle already uses.
  #
  # Leaving the source screen is NOT arriving. A spinner drawn over the screen
  # you tapped is already a different statekey, and so is the destination on its
  # first paint before its content loads — breaking on the first changed dump
  # records one of those as the destination, and Step 3 then measures a screen
  # that never existed. Measured 2026-08-23 on Threads: 2 of 28 states in a
  # 60-step run were such ghosts (`auto-0035`, 4 elements, the source screen
  # plus a "진행 중" spinner; `auto-0050`, 41 elements, a profile whose settled
  # capture has 122). Both broke the pipeline downstream — one as an ambiguous
  # transition that killed codegen outright, one as a screen the clone cannot
  # reach. So quiet is measured on whichever identity the screen is currently
  # in: statekey once it has left the source, sig while it is still there.
  local identity prev_sig="" prev_state="" same=0 quiet="${CLONE_TAP_SETTLE_QUIET:-3}"
  [[ "$quiet" =~ ^[1-9][0-9]*$ ]] || quiet=3
  local settled=false
  while [[ "$i" -lt "$tries" ]]; do
    sleep 0.3
    i=$((i + 1))
    if ! _live_dump "$sid" "$to_tree"; then break; fi
    # One parse for sig, nodekey and statekey — this loop used to spawn two
    # interpreters per poll for the same dump.
    identity="$(_identity_of "$to_tree" 2>/dev/null || true)"
    _TAP_TO_SIG="$(sed -n 's/^INFO: sig //p' <<<"$identity" | head -n 1)"
    _TAP_TO_KEY="$(sed -n 's/^INFO: nodekey //p' <<<"$identity" | head -n 1)"
    # Settle on statekey, not sig: on a live feed a like counter ticks every few
    # seconds, and settling on that returns a mid-transition tree as the
    # destination evidence Step 3 then measures.
    _TAP_TO_STATE="$(sed -n 's/^INFO: statekey //p' <<<"$identity" | head -n 1)"
    if [[ -n "$_TAP_TO_STATE" && "$_TAP_TO_STATE" != "$_TAP_FROM_STATE" ]]; then
      if [[ "$_TAP_TO_STATE" == "$prev_state" ]]; then same=$((same + 1)); else same=0; fi
    elif [[ -n "$_TAP_TO_SIG" && "$_TAP_TO_SIG" == "$prev_sig" ]]; then
      same=$((same + 1))
    else
      same=0
    fi
    prev_state="$_TAP_TO_STATE"
    prev_sig="$_TAP_TO_SIG"
    if [[ "$same" -ge "$((quiet - 1))" ]]; then settled=true; break; fi
  done
  [[ -n "$_TAP_TO_STATE" && "$_TAP_TO_STATE" != "$_TAP_FROM_STATE" ]] && _TAP_CHANGED=true
  # A tap has already happened, so preserve it as an incomplete transition, but
  # never promote the last moving dump to durable destination evidence.
  if [[ "$settled" != true ]]; then
    echo "ERROR: the screen did not settle after $i poll(s) — destination evidence is unstable (raise CLONE_TAP_SETTLE_TRIES)" >&2
    return 4
  fi
  return 0
}

# Did the tap leave the target app? Both tap paths need this, and only `step`
# had it: `tap` is what the skill's own loop uses, so a tap onto an app-switch
# control wrote the OTHER app's state into this app's graph.
# Returns 0 when still on target; prints the foreign bundle otherwise.
_landed_elsewhere() {
  local sid="$1" landed expected
  landed="$(_active_target "$sid" || true)"
  expected="$(_cached_session_bundle "$sid" || _session_target "$sid" || true)"
  if [[ -z "$expected" ]]; then
    return 0            # nothing to compare against; the session gate owns this
  fi
  # An empty answer is NOT "still on target". The query fails when the session
  # is dying or another app is in front, which are exactly the cases this
  # exists to catch — reading it as success made the check fail open.
  if [[ -z "$landed" ]]; then
    printf 'unknown'
    return 1
  fi
  if [[ "$landed" != "$expected" ]]; then
    printf '%s' "$landed"
    return 1
  fi
  return 0
}

_record_tap_transition() {
  local x="$1" y="$2"
  shift 2
  _flow_event tap "from=${_TAP_FROM_KEY:-?}" "to=${_TAP_TO_KEY:-?}" \
    "from_statekey=${_TAP_FROM_STATE:-?}" "to_statekey=${_TAP_TO_STATE:-?}" \
    "behavior=${_TAP_BEHAVIOR:-?}" "label=${_TAP_LABEL:-?}" \
    "x=$x" "y=$y" "changed=${_TAP_CHANGED:-false}" "$@"
}

cmd_tap() {
  local sid="${1:-}" x="${2:-}" y="${3:-}" tree="${4:-}" to_tree
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
  _prepare_tap "$sid" "$x" "$y" "$tree" || return $?
  to_tree="$(mktemp -t device_wda)"
  local settle_status=0
  _perform_tap_and_settle "$sid" "$x" "$y" "$to_tree" || settle_status=$?
  if [[ "$settle_status" -ne 0 ]]; then
    if [[ "$settle_status" -eq 4 ]]; then
      _record_tap_transition "$x" "$y" "evidence=unstable"
    fi
    rm -f "$to_tree"
    return 1
  fi
  local landed=""
  if ! landed="$(_landed_elsewhere "$sid")"; then
    # Same reasoning as `step`: the settle loop already read the OTHER app's
    # tree into these globals, and leaving them records a destination state of
    # the target that does not exist.
    _TAP_TO_KEY=""
    _TAP_TO_STATE=""
    _TAP_CHANGED=false
    _record_tap_transition "$x" "$y" "left_app=$landed" "evidence=foreign-app"
    rm -f "$to_tree"
    echo "ERROR: '$_TAP_LABEL' left the app for $landed — re-activate the target before continuing" >&2
    return 3
  fi
  _record_tap_transition "$x" "$y"
  rm -f "$to_tree"
  echo "OK: tapped $x,$y${_TAP_LABEL:+ ($_TAP_LABEL)}"
  [[ "$_TAP_CHANGED" == true ]] || echo "INFO: screen did not change — this target is a no-op or opened nothing"
}

cmd_step() {
  local sid="${1:-}" x="${2:-}" y="${3:-}" tree="${4:-}"
  local outdir="${5:-}" name="${6:-}" via="${7:-via=step}" xml png xml_tmp png_tmp
  if [[ -z "$sid" || -z "$x" || -z "$y" || -z "$tree" || -z "$outdir" || -z "$name" ]]; then
    echo "ERROR: usage: device_wda.sh step <sid> <x> <y> <tree.xml> <outdir> <name> [via=<reason>]" >&2
    return 1
  fi
  if [[ ! -f "$tree" ]]; then
    echo "ERROR: no such tree '$tree' — capture the source screen first" >&2
    return 1
  fi
  case "$name" in
    */*|.|..)
      echo "ERROR: step name must be a single file stem, got '$name'" >&2
      return 1
      ;;
  esac
  mkdir -p "$outdir"
  xml="$outdir/$name.xml"
  png="$outdir/$name.png"
  xml_tmp="$outdir/.$name.xml.$$.part"
  png_tmp="$outdir/.$name.png.$$.part"
  rm -f "$xml_tmp" "$png_tmp"

  _prepare_tap "$sid" "$x" "$y" "$tree" || return $?
  local settle_status=0
  _perform_tap_and_settle "$sid" "$x" "$y" "$xml_tmp" 1 || settle_status=$?
  if [[ "$settle_status" -ne 0 ]]; then
    if [[ "$settle_status" -eq 4 ]]; then
      _record_tap_transition "$x" "$y" "evidence=unstable" "$via"
    fi
    rm -f "$xml_tmp" "$png_tmp"
    return 1
  fi
  # The tap may have LEFT the app — Threads' "Instagram으로 전환" does exactly
  # that. Appium's /source then describes the other app, and without this check
  # that foreign screen is written as a state of the target: measured, spec'd,
  # and mapped to a SwiftUI view as though it were a screen of the app being
  # cloned. Record the exit as a transition, keep no screen evidence for it, and
  # return 3 so the caller can re-activate the target and carry on.
  local landed=""
  if ! landed="$(_landed_elsewhere "$sid")"; then
    # The settle loop already read the OTHER app's tree into these globals. Left
    # as they are, the exit records a destination state of the target that does
    # not exist: `observed_edges` would route toward it and `capture_gaps` would
    # demand an arrival capture that can never be written — an unclosable gap.
    # The destination is `left_app`, which is not a state of this app at all.
    _TAP_TO_KEY=""
    _TAP_TO_STATE=""
    _TAP_CHANGED=false
    _record_tap_transition "$x" "$y" "left_app=$landed" "evidence=foreign-app"
    rm -f "$xml_tmp" "$png_tmp"
    echo "ERROR: '$_TAP_LABEL' left the app for $landed — not recording its screen as a state of the target" >&2
    return 3
  fi
  if [[ ! -s "$xml_tmp" ]]; then
    _record_tap_transition "$x" "$y" "evidence=missing"
    rm -f "$xml_tmp" "$png_tmp"
    echo "ERROR: tap happened but no final settle XML was available; destination evidence is incomplete" >&2
    return 1
  fi
  if ! _capture_screenshot "$sid" "$png_tmp"; then
    _record_tap_transition "$x" "$y" "evidence=missing"
    rm -f "$xml_tmp" "$png_tmp"
    echo "ERROR: tap settled but the destination screenshot failed" >&2
    return 1
  fi
  if ! mv "$xml_tmp" "$xml" || ! mv "$png_tmp" "$png"; then
    rm -f "$xml_tmp" "$png_tmp"
    echo "ERROR: destination evidence could not be persisted under $outdir" >&2
    return 1
  fi

  _record_tap_transition "$x" "$y" "tree=$xml" "png=$png" "evidence=durable" "$via"
  _flow_event screen "node=${_TAP_TO_KEY:-?}" "statekey=${_TAP_TO_STATE:-?}" "sig=${_TAP_TO_SIG:-?}" \
    "name=$name" "tree=$xml" "png=$png" "$via"
  echo "OK: tapped $x,$y${_TAP_LABEL:+ ($_TAP_LABEL)} and captured $png + $xml"
  [[ "$_TAP_CHANGED" == true ]] || echo "INFO: screen did not change — durable evidence records the no-op destination"
}

cmd_type() {
  local sid="${1:-}" accessibility_id="${2:-}" text="${3:-}" response element type_response error attempt=1
  if [[ -z "$sid" || -z "$accessibility_id" || -z "$text" ]]; then
    echo "ERROR: usage: device_wda.sh type <sid> <accessibility_id> <text>" >&2
    echo "ERROR:   use a unique accessibility id from the current Appium accessibility tree; never log secrets." >&2
    return 1
  fi
  _assert_target "$sid" || return 1
  while (( attempt <= 2 )); do
    response="$(_curl -X POST "$APPIUM_URL/session/$sid/element" \
      -H 'Content-Type: application/json' \
      -d "$(python3 -c 'import json, sys; print(json.dumps({"using":"accessibility id", "value":sys.argv[1]}))' "$accessibility_id")")" || {
        echo "ERROR: accessibility id '$accessibility_id' was not found" >&2
        return 1
      }
    element="$(python3 -c '
import json, sys
value = json.load(sys.stdin).get("value", {})
if isinstance(value, dict):
    print(value.get("element-6066-11e4-a52e-4f735466cecf") or value.get("ELEMENT") or "")
' <<<"$response")"
    if [[ -z "$element" ]]; then
      echo "ERROR: Appium returned no element for accessibility id '$accessibility_id'" >&2
      return 1
    fi

    # Finding a text field can focus or re-layout the view. XCUITest then rejects
    # the bound element as stale even though the same accessibility id is still
    # present. Keep the response body so we can retry that one recoverable error
    # once without hiding transport failures or retrying arbitrary input errors.
    type_response="$(_curl_keep_body -X POST "$APPIUM_URL/session/$sid/element/$element/value" \
      -H 'Content-Type: application/json' \
      -d "$(python3 -c 'import json, sys; print(json.dumps({"text":sys.argv[1]}))' "$text")")" || {
      echo "ERROR: Appium could not type into '$accessibility_id'" >&2
      return 1
    }
    error="$(python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get("value", {})
except ValueError:
    print("invalid response")
else:
    print(value.get("error", "") if isinstance(value, dict) else "")
' <<<"$type_response")"
    if [[ -z "$error" ]]; then
      _flow_event input "label=$accessibility_id" "length=${#text}"
      echo "OK: typed ${#text} characters into $accessibility_id"
      return 0
    fi
    if [[ "$error" == "stale element reference" && "$attempt" == "1" ]]; then
      echo "INFO: text field changed while binding; re-finding '$accessibility_id' once" >&2
      _assert_target "$sid" || return 1
      attempt=2
      continue
    fi
    echo "ERROR: Appium could not type into '$accessibility_id' ($error)" >&2
    return 1
  done
}

cmd_swipe() {
  local sid="${1:-}" x1="${2:-}" y1="${3:-}" x2="${4:-}" y2="${5:-}"
  if [[ -z "$sid" || -z "$x1" || -z "$y1" || -z "$x2" || -z "$y2" ]]; then
    echo "ERROR: usage: device_wda.sh swipe <sid> <x1> <y1> <x2> <y2>" >&2
    return 1
  fi
  _assert_target "$sid" || return 1
  local before_tree after_tree planned from_key from_state to_sig to_key to_state changed=false i=0
  before_tree="$(mktemp -t device_wda)"
  after_tree="$(mktemp -t device_wda)"
  if ! _live_dump "$sid" "$before_tree"; then
    rm -f "$before_tree" "$after_tree"
    echo "ERROR: cannot read the current screen before swipe — session dead or device gone. Stop the loop." >&2
    return 1
  fi
  planned="$(_sig_of "$before_tree" || true)"
  from_key="$(_key_of "$before_tree" || true)"
  from_state="$(_state_of "$before_tree" || true)"
  if ! _actions "$sid" "$(printf '{"actions":[{"type":"pointer","id":"finger1","parameters":{"pointerType":"touch"},"actions":[{"type":"pointerMove","duration":0,"x":%s,"y":%s},{"type":"pointerDown","button":0},{"type":"pause","duration":100},{"type":"pointerMove","duration":600,"x":%s,"y":%s},{"type":"pointerUp","button":0}]}]}' "$x1" "$y1" "$x2" "$y2")"; then
    rm -f "$before_tree" "$after_tree"
    return 1
  fi
  # A swipe is settled when two consecutive polls read the same screen — NOT when
  # the screen first differs from before. Breaking on first difference returns a
  # tree captured 0.3s into a 600ms scroll animation, and Step 3 then measures
  # that half-scrolled frame as the screen's geometry.
  local prev_sig="" settled=false
  to_sig="$planned"
  while [[ "$i" -lt "${CLONE_SWIPE_SETTLE_TRIES:-10}" ]]; do
    sleep 0.3
    i=$((i + 1))
    if ! _live_dump "$sid" "$after_tree"; then break; fi
    to_sig="$(_sig_of "$after_tree" || true)"
    if [[ -n "$to_sig" && "$to_sig" == "$prev_sig" ]]; then settled=true; break; fi
    prev_sig="$to_sig"
  done
  [[ "$settled" == true ]] || echo "INFO: the screen was still moving after $i poll(s) — destination evidence may be mid-scroll" >&2
  # `changed` decides whether device_flow.py demands a durable destination
  # capture, so a false positive becomes a coverage gap that can never be closed
  # and a false negative loses a screen. The label set (`sig`) answers neither
  # question: on a live feed it changes with no swipe at all (measured on
  # Threads, a like count 226 -> 227), and a short list scrolled under an
  # unchanged set of labels does not change it at all. A swipe is what MOVES
  # elements, so ask that directly.
  local moved_rc=0
  _elements_moved "$before_tree" "$after_tree" || moved_rc=$?
  case "$moved_rc" in
    0) changed=true ;;
    1) echo "INFO: nothing moved between the two captures — content churn, not a scroll" >&2 ;;
    # Unknown is not "no". A false `changed` leaves a gap `stats` reports; a
    # false no-op loses the screen and nothing ever says so.
    *) changed=true
       echo "WARN: could not tell whether the swipe moved anything — recorded as changed so the missing arrival capture shows up in stats" >&2 ;;
  esac
  to_key="$(_key_of "$after_tree" 2>/dev/null || true)"
  to_state="$(_state_of "$after_tree" 2>/dev/null || true)"
  _flow_event swipe "from=${from_key:-?}" "to=${to_key:-?}" \
              "from_statekey=${from_state:-?}" "to_statekey=${to_state:-?}" \
              "x1=$x1" "y1=$y1" "x2=$x2" "y2=$y2" "changed=$changed"
  rm -f "$before_tree" "$after_tree"
  echo "OK: swiped $x1,$y1 -> $x2,$y2"
  [[ "$changed" == true ]] || echo "INFO: screen did not change — this swipe is a no-op or content has not settled"
}

cmd_doctor() {
  local want="${1:-}" bundle_id="${2:-}" failures=0 version drivers developer team
  local udids=() names=() all_names=() target_udid="" target_name="" apps available_kb free_mb
  # Sized to what a run actually consumes, not to what it needs to start.
  # Measured 2026-08-23: doctor passed at 3538MB free and the run then died with
  # ENOSPC — the WDA/Xcode builds, the captures and the render cache spent all
  # of it. A gate that only samples the starting line lets that happen every
  # time; this repo has already read a full disk as a SwiftUI compile error once.
  local minimum_mb="${CLONE_MIN_DISK_MB:-6144}" needs_tunnel=0
  echo "INFO: checking Appium, Xcode/CoreDevice, signing, target device, and disk"

  if command -v appium >/dev/null 2>&1; then
    if version="$(appium --version 2>/dev/null)"; then
      echo "OK: appium ${version%%$'\n'*}"
    else
      echo "ERROR: appium binary exists but 'appium --version' failed — reinstall or repair the global package" >&2
      failures=$((failures + 1))
    fi
    if drivers="$(appium driver list --installed 2>&1)" && grep -qi xcuitest <<<"$drivers"; then
      echo "OK: Appium xcuitest driver is installed"
    else
      echo "ERROR: Appium xcuitest driver is missing or unhealthy — run 'appium driver install xcuitest'" >&2
      failures=$((failures + 1))
    fi
  else
    echo "ERROR: appium binary not found — run 'npm i -g appium'" >&2
    failures=$((failures + 1))
  fi
  if _appium_status; then
    echo "OK: Appium server is ready at $APPIUM_URL"
  else
    echo "WARN: Appium server is not ready at $APPIUM_URL — 'session' will auto-start it unless CLONE_AUTO_START_APPIUM=0"
  fi

  if command -v xcode-select >/dev/null 2>&1 && developer="$(xcode-select -p 2>/dev/null)" && [[ -d "$developer" ]]; then
    echo "OK: Xcode developer directory $developer"
  else
    echo "ERROR: Xcode command-line tools are unavailable — install/select Xcode with 'sudo xcode-select -s /Applications/Xcode.app'" >&2
    failures=$((failures + 1))
  fi
  if command -v xcrun >/dev/null 2>&1 && xcrun --find devicectl >/dev/null 2>&1; then
    echo "OK: devicectl is available"
  else
    echo "ERROR: devicectl is unavailable — open/install a current Xcode toolchain and re-run xcode-select" >&2
    failures=$((failures + 1))
  fi

  team="$(_team)"
  if [[ -n "$team" ]]; then
    echo "OK: signing team $team"
  else
    echo "ERROR: no signing team — export DEVELOPMENT_TEAM=<10-char team id> or add it to ~/.autobot/.env" >&2
    failures=$((failures + 1))
  fi

  _collect_connected_devices
  if [[ "${#udids[@]}" -eq 1 ]]; then
    target_udid="${udids[0]}"
    target_name="${names[0]}"
    echo "OK: connected target $target_udid ($target_name)"
    if ! _persist_device_profile "$target_udid" "$target_name"; then
      failures=$((failures + 1))
    elif _device_requires_tunnel "$target_udid"; then
      if _tunnel_registry_ready "$target_udid"; then
        echo "OK: RemoteXPC tunnel is ready for $target_udid"
      else
        echo "INFO: RemoteXPC tunnel is missing for iOS 18+ target $target_udid — doctor will prepare it after the remaining checks pass"
        needs_tunnel=1
      fi
    fi
  elif [[ "${#udids[@]}" -eq 0 ]]; then
    echo "ERROR: no connected physical iPhone${want:+ matching '$want'} — connect, unlock, trust, and enable Developer Mode" >&2
    failures=$((failures + 1))
  else
    echo "ERROR: ${#udids[@]} connected iPhones match${want:+ '$want'} — pass an exact UDID or unique name to doctor" >&2
    failures=$((failures + 1))
  fi

  if [[ -n "$bundle_id" ]]; then
    if [[ -z "$target_udid" ]]; then
      echo "ERROR: cannot look up bundle '$bundle_id' until one connected target is resolved" >&2
      failures=$((failures + 1))
    elif apps="$(xcrun devicectl device info apps --device "$target_udid" \
          --include-all-apps --search "$bundle_id" --json-output - 2>/dev/null)" \
      && python3 -c '
import json, sys
needle = sys.argv[1]
def contains(value):
    if isinstance(value, dict):
        return any(contains(item) for item in value.values())
    if isinstance(value, list):
        return any(contains(item) for item in value)
    return value == needle
raise SystemExit(0 if contains(json.load(sys.stdin).get("result", {})) else 1)
' "$bundle_id" <<<"$apps" 2>/dev/null; then
      echo "OK: bundle $bundle_id is installed on $target_udid"
    else
      echo "ERROR: bundle $bundle_id was not found on $target_udid — verify with devicectl --include-all-apps" >&2
      failures=$((failures + 1))
    fi
  fi

  [[ "$minimum_mb" =~ ^[0-9]+$ ]] || minimum_mb=2048
  available_kb="$(df -Pk "$PWD" 2>/dev/null | awk 'NR == 2 { print $4 }')"
  if [[ "$available_kb" =~ ^[0-9]+$ ]]; then
    free_mb=$((available_kb / 1024))
    if [[ "$free_mb" -ge "$minimum_mb" ]]; then
      echo "OK: disk free ${free_mb}MB (minimum ${minimum_mb}MB)"
    else
      echo "ERROR: disk free ${free_mb}MB is below ${minimum_mb}MB — a full run spends about 3.5GB on WDA/Xcode builds, captures and the render cache. Free space (Xcode DerivedData is usually the largest reclaimable) or adjust CLONE_MIN_DISK_MB" >&2
      failures=$((failures + 1))
    fi
  else
    echo "ERROR: could not determine disk free space for $PWD" >&2
    failures=$((failures + 1))
  fi

  if [[ "$failures" -eq 0 && "$needs_tunnel" -eq 1 ]]; then
    if _ensure_tunnel "$target_udid"; then
      echo "OK: RemoteXPC tunnel prepared for $target_udid"
    else
      failures=$((failures + 1))
    fi
  fi

  if [[ "$failures" -gt 0 ]]; then
    echo "ERROR: doctor found $failures blocking issue(s)" >&2
    return 1
  fi
  echo "OK: doctor passed"
}

# Logical size of whatever the tree describes — the application element is the
# largest frame in it. Used to place a scroll gesture without hardcoding a device.
_screen_size_of() {
  python3 -c "
import sys
sys.path.insert(0, sys.argv[1])
import device_a11y
frames = [e['frame'] for e in device_a11y.load(sys.argv[2]) if e['frame']['width'] > 0]
if not frames:
    raise SystemExit(1)
biggest = max(frames, key=lambda f: f['width'] * f['height'])
print(int(biggest['width']), int(biggest['height']))
" "$_HERE" "$1"
}

# One scroll down plus a durable capture. Returns 0 when the screen actually
# moved — that capture holds candidates no earlier one showed, and `frontier`
# unions candidates across every capture of a state, so the next `next-tap` sees
# them. Returns 1 at the end of the content (or on a screen that does not
# scroll), which is what stops the walk.
#
# Without this, exploration of a feed app ends when the first screenful is
# drained: measured on Threads, 34 of 235 targets — the rest were never on a
# capture at all. `next-tap` already says which case it is; this acts on it.
# Type into a text field the current screen shows, then capture what came up.
#
# Exploration never typed, so every search screen was a dead end — the results
# behind it exist only past the keyboard. The probe text is generic on purpose
# and is NOT logged (the `type` rule: never log what was typed). The flow event
# records the field that was typed into and where the screen went.
_type_for_more() {
  local sid="$1" outdir="$2" from_tree="$3" name="$4" typed_file="$5"
  local probe="${CLONE_EXPLORE_PROBE_TEXT:-a}" line field from_state to_state
  # SEARCH FIELDS ONLY. Typing commits with Return below, and Return in a
  # composer sends the message — which walks around the `communication` guard
  # that withholds the Send button itself. A blind probe cannot tell a search
  # box from a message box, so it does not get to choose: `inputs` classifies
  # each field and anything not marked `search` is left alone.
  line="$(python3 "$_HERE/device_a11y.py" inputs "$from_tree" 2>/dev/null \
          | sed -n 's/^INFO: input //p' | awk -F'\t' '$NF == "search" { print; exit }')"
  if [[ -z "$line" ]]; then
    return 1
  fi
  field="${line%%	*}"
  from_state="$(_state_of "$from_tree" 2>/dev/null || true)"
  # Once per field per state: typing the same probe into the same box again
  # discovers nothing and spends a capture.
  if [[ -f "$typed_file" ]] && grep -qxF "$from_state $field" "$typed_file"; then
    return 1
  fi
  printf '%s %s\n' "$from_state" "$field" >> "$typed_file"
  cmd_type "$sid" "$field" "$probe" >/dev/null 2>&1 || return 1
  # Return commits the search on most apps; harmless where it does not.
  _curl -X POST "$APPIUM_URL/session/$sid/actions" -H 'Content-Type: application/json' \
    -d '{"actions":[{"type":"key","id":"kb","actions":[{"type":"keyDown","value":"\uE007"},{"type":"keyUp","value":"\uE007"}]}]}' \
    >/dev/null 2>&1 || true
  sleep "${CLONE_TYPE_SETTLE:-1}"
  cmd_screen "$sid" "$outdir" "$name" >/dev/null || return 1
  to_state="$(_state_of "$outdir/$name.xml" 2>/dev/null || true)"
  _flow_event type "from_statekey=${from_state:-?}" "to_statekey=${to_state:-?}" \
    "field=$field" "changed=$([[ -n "$to_state" && "$to_state" != "$from_state" ]] && echo true || echo false)" \
    "tree=$outdir/$name.xml" "png=$outdir/$name.png"
  [[ -n "$to_state" && "$to_state" != "$from_state" ]]
}

_scroll_for_more() {
  local sid="$1" outdir="$2" from_tree="$3" name="$4" size width height
  if ! size="$(_screen_size_of "$from_tree")"; then
    echo "WARN: cannot size the screen from $(basename "$from_tree") — not scrolling" >&2
    return 1
  fi
  width="${size%% *}"
  height="${size##* }"
  if ! cmd_swipe "$sid" "$((width / 2))" "$((height * 3 / 4))" \
                 "$((width / 2))" "$((height / 4))" >/dev/null; then
    return 1
  fi
  cmd_screen "$sid" "$outdir" "$name" >/dev/null || return 1
  local moved_rc=0
  _elements_moved "$from_tree" "$outdir/$name.xml" || moved_rc=$?
  case "$moved_rc" in
    0) return 0 ;;
    1) echo "INFO: the screen did not move — end of content here" ;;
    *) echo "WARN: could not tell whether the scroll moved anything — treating it as the end" >&2 ;;
  esac
  return 1
}

# Highest auto-capture index in <outdir> + 1, so re-runs never clobber evidence.
_next_auto_index() {
  local dir="$1" max=0 file stem idx
  for file in "$dir"/auto-*.xml; do
    [[ -e "$file" ]] || continue
    stem="${file##*/auto-}"
    idx="${stem%.xml}"
    if [[ "$idx" =~ ^[0-9]+$ ]] && [[ "$((10#$idx))" -gt "$max" ]]; then
      max="$((10#$idx))"
    fi
  done
  echo $((max + 1))
}

# Drain safe frontier candidates mechanically — the agent only navigates BETWEEN
# frontiers, not every tap. DFS by construction: a changed tap continues on the
# arrival screen, and back buttons are candidates too, so the walk returns on
# its own. Every tap goes through the same step guards (candidate provenance,
# fresh sig, foreground bundle), and withheld/state-changing targets are never
# tapped — `device_flow.py todo` filters them out before this loop sees them.
# Stopping is normal, not exceptional: drained screen, max steps, or any guard.
cmd_explore() {
  local sid="${1:-}" outdir="${2:-}" max_steps="${3:-20}"
  if [[ -z "$sid" || -z "$outdir" ]]; then
    echo "ERROR: usage: device_wda.sh explore <sid> <outdir> [max_steps]" >&2
    return 1
  fi
  if ! [[ "$max_steps" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: max_steps must be a positive integer, got '$max_steps'" >&2
    return 1
  fi
  local flow="${CLONE_FLOW_LOG:-.autobot/clone/flow.jsonl}"
  local max_route="${CLONE_EXPLORE_MAX_ROUTE:-12}"
  local max_stale="${CLONE_EXPLORE_MAX_STALE:-5}"
  local max_scroll="${CLONE_EXPLORE_MAX_SCROLL:-6}"
  local max_left="${CLONE_EXPLORE_MAX_LEAVE_APP:-8}"
  local n name tree next_out line kind x y rc steps=0 route_hops=0 stale=0
  local max_restart="${CLONE_EXPLORE_MAX_RESTART:-8}"
  local scrolls=0 scrolled=0 left=0 restarts=0
  # The contract's budget is CUMULATIVE taps on the target, not actions per
  # run. Starting every run at zero — and telling the operator to re-run when a
  # run ends — made "누적 탭 25회" unenforceable: three runs of 20 is 60 taps on
  # someone's real account. Count what the log already spent and refuse to
  # exceed the cap, whatever `max_steps` says about THIS run.
  local budget="${CLONE_TAP_BUDGET:-25}" spent
  spent="$(_taps_spent "$flow")"
  if [[ "$spent" -lt 0 ]]; then
    return 1
  fi
  if [[ "$spent" -ge "$budget" ]]; then
    echo "OK: tap budget spent ($spent/$budget cumulative in $flow) — exploration is done." >&2
    echo "INFO: raise CLONE_TAP_BUDGET, or clear the log to start a new target." >&2
    return 0
  fi
  # A switch probe taps forward and immediately taps back, so a run allowed one
  # more step could spend two and land at 26/25. Reserve the revert.
  local remaining=$(( budget - spent ))
  [[ "$remaining" -ge 2 ]] || remaining=1
  if [[ "$max_steps" -gt "$remaining" ]]; then
    echo "INFO: $spent/$budget taps already spent — this run may make $remaining more" >&2
    max_steps="$remaining"
  fi
  n="$(_next_auto_index "$outdir")"
  name="$(printf 'auto-%04d' "$n")"
  cmd_screen "$sid" "$outdir" "$name" || return 1
  tree="$outdir/$name.xml"
  if [[ ! -s "$tree" ]]; then
    echo "ERROR: seed capture has no accessibility tree — cannot explore" >&2
    return 1
  fi
  # One query answers both halves of the walk: drain this screen, and when it is
  # drained, take the first hop of the shortest observed route to a screen that
  # is not. Routing hops are taps we already made, so they are live candidates
  # here and the stale-coordinate guard still applies to every one of them.
  while [[ "$steps" -lt "$max_steps" ]]; do
    if ! next_out="$(python3 "$_HERE/device_flow.py" next-tap "$flow" "$tree")"; then
      echo "ERROR: could not compute the next tap from $(basename "$tree") — see above" >&2
      return 1
    fi
    line="$(sed -n 's/^INFO: next-tap //p' <<<"$next_out" | head -n 1)"
    if [[ -z "$line" ]]; then
      sed -n 's/^OK: /INFO: /p;s/^WARN: /WARN: /p' <<<"$next_out"
      # A text field on screen is a door the tap walk cannot open. Try it once
      # per field before scrolling or leaving.
      n=$((n + 1))
      name="$(printf 'auto-%04d' "$n")"
      if _type_for_more "$sid" "$outdir" "$tree" "$name" "$outdir/.typed"; then
        steps=$((steps + 1))
        route_hops=0
        scrolls=0
        echo "INFO: typed into a text field and reached a new screen"
        tree="$outdir/$name.xml"
        continue
      fi
      # Nothing to tap on THIS capture is not the same as nothing left in the
      # app: a list holds targets that only another scroll position shows. Scroll
      # before giving up, bounded per screen so an endless feed cannot own the run.
      if [[ "$scrolls" -lt "$max_scroll" ]]; then
        n=$((n + 1))
        name="$(printf 'auto-%04d' "$n")"
        if _scroll_for_more "$sid" "$outdir" "$tree" "$name"; then
          scrolls=$((scrolls + 1))
          steps=$((steps + 1))   # a scroll is an action; it spends the budget
          scrolled=$((scrolled + 1))
          # A scroll that moved the screen produced a capture with candidates no
          # earlier one had — that is progress, not the ping-pong the routing cap
          # exists to stop. Leaving it counted would end the round early on a
          # feed that scrolling is actively opening up.
          route_hops=0
          echo "INFO: scrolled for more candidates ($scrolls/$max_scroll on this screen)"
          tree="$outdir/$name.xml"
          continue
        fi
      fi
      # Drained HERE is not drained everywhere. Routing only knows observed
      # transitions, so a screen deep in the app has no known way back to the
      # ones that still hold candidates — and the walk used to end there.
      if [[ "$restarts" -lt "$max_restart" ]] && ! grep -q "frontier empty" <<<"$next_out"; then
        restarts=$((restarts + 1))
        echo "INFO: no route from here — restarting the app to reach the rest ($restarts/$max_restart)"
        if _restart_target "$sid"; then
          n=$((n + 1))
          name="$(printf 'auto-%04d' "$n")"
          if cmd_screen "$sid" "$outdir" "$name"; then
            tree="$outdir/$name.xml"
            scrolls=0
            route_hops=0
            steps=$((steps + 1))
            continue
          fi
        fi
        echo "WARN: could not restart the app; ending the round here" >&2
      fi
      echo "INFO: nothing left to tap from here after $steps step(s)"
      break
    fi
    kind="$(sed -n 's/^INFO: kind //p' <<<"$next_out" | head -n 1)"
    if [[ "$kind" == route* ]]; then
      route_hops=$((route_hops + 1))
      if [[ "$route_hops" -gt "$max_route" ]]; then
        echo "INFO: $max_route consecutive routing hops reached no new work — stopping so the walk cannot ping-pong (see device_flow.py next)"
        break
      fi
    else
      route_hops=0
    fi
    x="${line%% *}"
    line="${line#* }"
    y="${line%% *}"
    n=$((n + 1))
    name="$(printf 'auto-%04d' "$n")"
    cmd_step "$sid" "$x" "$y" "$tree" "$outdir" "$name" && rc=0 || rc=$?
    if [[ "$rc" -eq 2 ]]; then
      # The screen moved between capture and tap. On a live app that is the
      # normal case, not an error: re-capture and pick from fresh candidates.
      # Nothing was tapped, so this cannot double-tap. Bounded, because a screen
      # that keeps moving would otherwise spin here forever.
      stale=$((stale + 1))
      if [[ "$stale" -gt "$max_stale" ]]; then
        echo "ERROR: the screen kept changing under $max_stale consecutive re-captures — the device is not settling; stopping after $steps step(s)" >&2
        return 1
      fi
      echo "INFO: re-capturing after a stale-screen rejection ($stale/$max_stale)"
      n=$((n + 1))
      name="$(printf 'auto-%04d' "$n")"
      cmd_screen "$sid" "$outdir" "$name" || return 1
      tree="$outdir/$name.xml"
      continue
    fi
    if [[ "$rc" -eq 3 ]]; then
      # The tap left the app. The transition is recorded, no foreign screen was
      # written, and the target can simply be brought back — ending the run here
      # would forfeit the rest of the app over one outbound link.
      left=$((left + 1))
      if [[ "$left" -gt "$max_left" ]]; then
        echo "ERROR: left the app $max_left times in a row without getting anywhere — stopping after $steps step(s)" >&2
        return 1
      fi
      _reactivate_target "$sid" || return 1
      steps=$((steps + 1))   # the tap happened; it spends the budget
      n=$((n + 1))
      name="$(printf 'auto-%04d' "$n")"
      cmd_screen "$sid" "$outdir" "$name" || return 1
      tree="$outdir/$name.xml"
      continue
    fi
    if [[ "$rc" -ne 0 ]]; then
      if [[ "$_TAP_EFFECT" == toggle ]]; then
        echo "ERROR: switch probe for '$_TAP_LABEL' failed after the tap — its setting may be changed; inspect and restore it before retrying" >&2
      fi
      echo "ERROR: explore stopped after $steps step(s) — the flow log keeps what was done; fix the condition above and re-run explore" >&2
      return 1
    fi
    stale=0
    left=0             # the cap is on being STUCK outside, not on how many
                       # outbound links a healthy long walk happens to follow
    scrolls=0          # new screen (or new position) — its own scroll budget
    tree="$outdir/$name.xml"
    steps=$((steps + 1))
    # An explicitly enabled switch probe is the one state-changing control that
    # exploration may tap. Flip it back NOW, from the capture just taken, so the
    # device never carries a changed setting into the rest of the walk — the
    # frontier would revert it eventually, but only if nothing else on the
    # flipped screen gets tapped first. The revert is a step like any other: its
    # own tap edge and arrival capture, so the functional gate can replay both
    # directions.
    if [[ "$_TAP_EFFECT" == toggle ]]; then
      local revert_state="$_TAP_FROM_STATE" revert_behavior="$_TAP_BEHAVIOR" revert_label="$_TAP_LABEL"
      n=$((n + 1))
      name="$(printf 'auto-%04d' "$n")"
      local revert_rc=0
      _TAP_REVERTING=1
      cmd_step "$sid" "$x" "$y" "$tree" "$outdir" "$name" "via=revert" || revert_rc=$?
      _TAP_REVERTING=0
      if [[ "$revert_rc" -eq 0 ]]; then
        if [[ -z "$revert_state" || "$_TAP_TO_STATE" != "$revert_state" ||
              "$_TAP_BEHAVIOR" != "$revert_behavior" || "$_TAP_LABEL" != "$revert_label" ]]; then
          echo "ERROR: revert did not prove that '$revert_label' returned to its original state — stopping with the device setting potentially changed" >&2
          return 1
        fi
        tree="$outdir/$name.xml"
        steps=$((steps + 1))
      else
        echo "ERROR: could not flip '$revert_label' back at $x,$y — the device setting may be left changed; revert it by hand" >&2
        return 1
      fi
    fi
  done
  if [[ "$steps" -ge "$max_steps" ]]; then
    echo "INFO: reached max steps ($max_steps) — re-run explore to continue"
  fi
  python3 "$_HERE/device_flow.py" stats "$flow" || true
  echo "OK: explore made $steps step(s)${scrolled:+ (${scrolled} scroll)}"
}

cmd_quit() {
  local sid="${1:-}"
  if [[ -z "$sid" ]]; then
    echo "ERROR: usage: device_wda.sh quit <sid>" >&2
    return 1
  fi
  _curl -X DELETE "$APPIUM_URL/session/$sid" >/dev/null 2>&1 || true
  _remove_session_descriptor "$sid"
  echo "OK: session ended"
}

# Does this device still need a RemoteXPC tunnel started?
#
#   exit 0 — ready, or this device does not need one
#   exit 1 — a tunnel has to be created, which needs root
#
# Its own subcommand so a caller can ask BEFORE committing to a run. The tunnel
# is created several minutes in, at `doctor`, and that is a bad place to
# discover that nobody can authenticate.
cmd_tunnel_status() {
  local udid="${1:-}"
  if [[ -z "$udid" ]]; then
    echo "ERROR: usage: device_wda.sh tunnel-status <udid>" >&2
    return 2
  fi
  # "The profile does not describe this device" is not "no tunnel needed".
  # Conflating them made this gate answer OK for a device on iOS 26 — it was
  # handed the CoreDevice identifier while the profile records the hardware one,
  # and a gate that passes on a mismatch is the silent pass this repo keeps
  # paying for.
  if [[ ! -r "$CLONE_DEVICE_PROFILE_FILE" ]]; then
    echo "ERROR: no device profile at $CLONE_DEVICE_PROFILE_FILE — run 'device_wda.sh device' first" >&2
    return 2
  fi
  local profiled
  profiled="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("udid") or "")' \
    "$CLONE_DEVICE_PROFILE_FILE" 2>/dev/null || true)"
  if [[ "$profiled" != "$udid" ]]; then
    echo "ERROR: the device profile describes '$profiled', not '$udid' — pass the UDID 'device_wda.sh device' prints" >&2
    return 2
  fi
  if ! _device_requires_tunnel "$udid"; then
    echo "OK: $udid does not need a RemoteXPC tunnel"
    return 0
  fi
  if _tunnel_registry_ready "$udid"; then
    echo "OK: RemoteXPC tunnel is ready for $udid"
    return 0
  fi
  echo "INFO: $udid needs a RemoteXPC tunnel and none is registered" >&2
  return 1
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    device)     cmd_device "$@" ;;
    session)    cmd_session "$@" ;;
    screen)     cmd_screen "$@" ;;
    step)       cmd_step "$@" ;;
    explore)    cmd_explore "$@" ;;
    candidates) python3 "$_HERE/device_a11y.py" candidates "$@" ;;
    sig)        python3 "$_HERE/device_a11y.py" sig "$@" ;;
    tap)        cmd_tap "$@" ;;
    type)       cmd_type "$@" ;;
    swipe)      cmd_swipe "$@" ;;
    swipefrac)  cmd_swipefrac "$@" ;;
    back)       cmd_back "$@" ;;
    quit)       cmd_quit "$@" ;;
    stop-server) cmd_stop_server "$@" ;;
    doctor)     cmd_doctor "$@" ;;
    tunnel-status) cmd_tunnel_status "$@" ;;
    tunnel-start)  _ensure_tunnel "${1:-}" ;;
    *) echo "ERROR: unknown subcommand '${sub:-}'. Use: device | session | screen | step | explore | candidates | sig | tap | type | swipe | quit | stop-server | doctor | tunnel-status | tunnel-start" >&2; return 1 ;;
  esac
}

main "$@"
