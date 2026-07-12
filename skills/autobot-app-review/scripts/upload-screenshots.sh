#!/bin/bash
# Upload App Store screenshots via `fastlane deliver --skip_binary_upload --skip_metadata`.
# Single responsibility: ASC screenshot upload. No generation, no metadata, no binary.
#
# Required env (ASC API Key):
#   ASC_API_KEY_ID
#   ASC_API_ISSUER_ID
#   ASC_API_KEY_PATH
#
# Status output (optional, atomic):
#   AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE
#
# Exit codes:
#   0  uploaded (or dry-run passed)
#   1  usage / input validation
#   2  screenshots dir missing or empty / ASC creds missing / .p8 unreadable
#   3  fastlane install failed
#   4  fastlane deliver failed (see status.reason)
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

BUNDLE_ID=""
TEAM_ID=""
SCREENSHOTS_PATH="fastlane/screenshots"
PLATFORM="ios"
OVERWRITE=1
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: upload-screenshots.sh --bundle-id <id> [--team-id <id>]
                             [--screenshots-path <dir>] [--platform <p>]
                             [--no-overwrite] [--dry-run]

Required:
  --bundle-id         Reverse-DNS App ID. App must already be registered on ASC.

Optional:
  --team-id           Apple Developer Team ID (10 alphanumeric uppercase).
                      Precedence: --team-id > $DEVELOPMENT_TEAM > config.json.
  --screenshots-path  Path to fastlane/screenshots. Default: fastlane/screenshots
  --platform          ios | appletvos | xros. Default: ios
  --no-overwrite      Do NOT replace existing ASC screenshots. Default: overwrite.
  --dry-run           Print resolved fastlane invocation; do not call it.

Layout expected:
  <screenshots-path>/<locale>/*.png
    e.g. fastlane/screenshots/ko/01_hero.png
         fastlane/screenshots/ko/02_feature.png
  Fastlane auto-detects display family (e.g. 6.9", 6.5", 6.3", 6.1") by image
  pixel dimensions. Filename order = ASC slot order — use numeric prefixes.
USAGE
}

require_value() {
  if [ -z "${2:-}" ] || [[ "${2:-}" == --* ]]; then
    log_error "$1 requires a value"
    usage >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --bundle-id)        require_value "$1" "${2:-}"; BUNDLE_ID="$2";        shift 2;;
    --team-id)          require_value "$1" "${2:-}"; TEAM_ID="$2";          shift 2;;
    --screenshots-path) require_value "$1" "${2:-}"; SCREENSHOTS_PATH="$2"; shift 2;;
    --platform)         require_value "$1" "${2:-}"; PLATFORM="$2";         shift 2;;
    --no-overwrite)     OVERWRITE=0;                                         shift 1;;
    --dry-run)          DRY_RUN=1;                                            shift 1;;
    -h|--help)          usage; exit 0;;
    *) log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$BUNDLE_ID" ]; then
  log_error "--bundle-id is required"
  usage >&2
  exit 1
fi

# Normalize bundle id (lowercase prefix, preserve last segment) — same policy
# as autobot-upload-metadata so callers can pass the canonical form.
if [[ "$BUNDLE_ID" == *.* ]]; then
  BID_LAST="${BUNDLE_ID##*.}"
  BID_PREFIX="${BUNDLE_ID%.*}"
  BID_PREFIX="$(printf '%s' "$BID_PREFIX" | tr '[:upper:]' '[:lower:]')"
  BUNDLE_ID="${BID_PREFIX}.${BID_LAST}"
fi

if ! printf '%s' "$BUNDLE_ID" | grep -Eq '^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*\.[A-Za-z0-9][A-Za-z0-9-]*$'; then
  log_error "bundle ID '$BUNDLE_ID' is not valid reverse-DNS"
  exit 1
fi

case "$PLATFORM" in
  ios|appletvos|xros) ;;
  *) log_error "--platform must be ios | appletvos | xros (got: $PLATFORM)"; exit 1;;
esac

if ! command -v python3 &>/dev/null; then
  log_error "python3 not found"
  exit 1
fi

# Team ID precedence
if [ -z "$TEAM_ID" ] && [ -n "${DEVELOPMENT_TEAM:-}" ]; then
  TEAM_ID="$DEVELOPMENT_TEAM"
fi
if [ -z "$TEAM_ID" ]; then
  resolve_symlink() {
    local target="$1"
    while [ -L "$target" ]; do
      local link
      link="$(readlink "$target")"
      case "$link" in
        /*) target="$link";;
         *) target="$(cd "$(dirname "$target")" && pwd)/$link";;
      esac
    done
    printf '%s' "$target"
  }
  REAL_SOURCE="$(resolve_symlink "${BASH_SOURCE[0]}")"
  SCRIPT_DIR="$(cd "$(dirname "$REAL_SOURCE")" && pwd)"
  PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
  CONFIG_SH="$PLUGIN_ROOT/skills/autobot-setup/scripts/config.sh"
  if [ -f "$CONFIG_SH" ]; then
    TEAM_ID="$(bash "$CONFIG_SH" get-or developmentTeam '' 2>/dev/null || echo '')"
  fi
fi

if [ -n "$TEAM_ID" ] && ! printf '%s' "$TEAM_ID" | grep -Eq '^[A-Z0-9]{10}$'; then
  log_error "team ID '$TEAM_ID' is not 10 uppercase alphanumeric characters"
  exit 1
fi

# Screenshots path validation
if [ ! -d "$SCREENSHOTS_PATH" ]; then
  log_error "screenshots path not found: $SCREENSHOTS_PATH"
  log_info  "expected layout: $SCREENSHOTS_PATH/<locale>/*.png"
  exit 2
fi

SHOT_COUNT=$(find "$SCREENSHOTS_PATH" -mindepth 2 -name "*.png" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$SHOT_COUNT" -eq 0 ]; then
  log_error "no .png files found under $SCREENSHOTS_PATH/<locale>/"
  exit 2
fi

LOCALE_COUNT=$(find "$SCREENSHOTS_PATH" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

# ASC credentials check
MISSING=()
[ -z "${ASC_API_KEY_ID:-}" ]    && MISSING+=("ASC_API_KEY_ID")
[ -z "${ASC_API_ISSUER_ID:-}" ] && MISSING+=("ASC_API_ISSUER_ID")
[ -z "${ASC_API_KEY_PATH:-}" ]  && MISSING+=("ASC_API_KEY_PATH")
if [ ${#MISSING[@]} -gt 0 ]; then
  log_error "missing ASC API credentials: ${MISSING[*]}"
  exit 2
fi

ASC_API_KEY_PATH_EXPANDED="${ASC_API_KEY_PATH/#\~/$HOME}"
if [ ! -r "$ASC_API_KEY_PATH_EXPANDED" ]; then
  log_error "ASC_API_KEY_PATH not readable: $ASC_API_KEY_PATH"
  exit 2
fi
ASC_API_KEY_PATH="$ASC_API_KEY_PATH_EXPANDED"

# fastlane install (skipped in dry-run)
if [ "$DRY_RUN" -eq 0 ] && ! command -v fastlane &>/dev/null; then
  if ! command -v brew &>/dev/null; then
    log_error "fastlane is missing and Homebrew is not installed"
    log_info  "install Homebrew first: https://brew.sh"
    log_info  "or: sudo gem install fastlane -NV"
    exit 3
  fi
  log_info "installing fastlane via Homebrew"
  if ! brew install fastlane; then
    log_error "fastlane install via brew failed"
    exit 3
  fi
fi

WORK_DIR="$(mktemp -d -t autobot-shots-upload.XXXXXX)"
cleanup() {
  local rc=$?
  if [ -n "${WORK_DIR:-}" ] && [ -d "$WORK_DIR" ]; then
    find "$WORK_DIR" -type f -exec chmod 600 {} \; 2>/dev/null || true
    rm -rf "$WORK_DIR"
  fi
  if [ -n "${AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

emit_json() {
  python3 -c '
import json, sys
data = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    data[k] = v
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
' "$@"
}

API_KEY_JSON="$WORK_DIR/fastlane_api_key.json"
# fastlane's Spaceship::ConnectAPI::Token.from_json_file requires the .p8 PEM
# CONTENT under `key` — it does not recognize a `key_filepath` field and fails
# with "API key JSON is missing field(s): key". Embed the file contents.
ASC_API_KEY_CONTENT="$(cat "$ASC_API_KEY_PATH")"
( umask 077
  emit_json \
    "key_id=$ASC_API_KEY_ID" \
    "issuer_id=$ASC_API_ISSUER_ID" \
    "key=$ASC_API_KEY_CONTENT" \
    > "$API_KEY_JSON"
)
chmod 600 "$API_KEY_JSON"

write_status() {
  local result="$1"
  local reason="${2:-}"
  local target="${AUTOBOT_SCREENSHOT_UPLOAD_STATUS_FILE:-}"
  [ -z "$target" ] && return 0
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "bundle_id=$BUNDLE_ID" \
    "team_id=$TEAM_ID" \
    "screenshots_path=$SCREENSHOTS_PATH" \
    "screenshot_count=$SHOT_COUNT" \
    "locale_count=$LOCALE_COUNT" \
    "platform=$PLATFORM" \
    "overwrite=$OVERWRITE" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

log_info "bundle:       $BUNDLE_ID"
log_info "screenshots:  $SCREENSHOTS_PATH ($SHOT_COUNT files across $LOCALE_COUNT locales)"
log_info "platform:     $PLATFORM"
log_info "overwrite:    $OVERWRITE"
[ -n "$TEAM_ID" ] && log_info "team:         $TEAM_ID"

OVERWRITE_FLAG=""
[ "$OVERWRITE" -eq 1 ] && OVERWRITE_FLAG="--overwrite_screenshots"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — would invoke:"
  python3 - "$BUNDLE_ID" "$SCREENSHOTS_PATH" "$PLATFORM" "$TEAM_ID" "$OVERWRITE_FLAG" <<'PY'
import shlex, sys
bid, sp, plat, team, ow = sys.argv[1:6]
parts = [
    "fastlane deliver",
    f"  --app_identifier {shlex.quote(bid)}",
    f"  --screenshots_path {shlex.quote(sp)}",
    f"  --platform {shlex.quote(plat)}",
    "  --skip_binary_upload",
    "  --skip_metadata",
    "  --skip_app_version_update",
    "  --force",
    "  --precheck_include_in_app_purchases false",
    "  --api_key_path <tempdir>/fastlane_api_key.json",
]
if ow:
    parts.append(f"  {ow}")
if team:
    parts.append(f"  --team_id {shlex.quote(team)}")
print(" \\\n".join(parts))
PY
  log_ok "dry-run validation passed"
  write_status "dry_run"
  exit 0
fi

export FASTLANE_SKIP_UPDATE_CHECK=1
export FASTLANE_HIDE_CHANGELOG=1
export FASTLANE_HIDE_PLUGINS_TABLE=1
export FASTLANE_DISABLE_COLORS=1
export FASTLANE_OPT_OUT_USAGE=1
export FASTLANE_SKIP_2FA_UPGRADE=1

set +e
DELIVER_OUTPUT="$(
  fastlane deliver \
    --app_identifier "$BUNDLE_ID" \
    --screenshots_path "$SCREENSHOTS_PATH" \
    --platform "$PLATFORM" \
    --skip_binary_upload \
    --skip_metadata \
    --skip_app_version_update \
    --force \
    --precheck_include_in_app_purchases false \
    ${OVERWRITE_FLAG} \
    ${TEAM_ID:+--team_id "$TEAM_ID"} \
    --api_key_path "$API_KEY_JSON" \
    </dev/null \
    2>&1
)"
DELIVER_EXIT=$?
set -e

printf '%s\n' "$DELIVER_OUTPUT"

error_lines() {
  printf '%s' "$1" | grep -Ei '^\[!\]|error|warning|could not|not found|not authorized|invalid|unsupported|wrong size' || true
}

if [ $DELIVER_EXIT -eq 0 ]; then
  log_ok "screenshots uploaded to App Store Connect"
  write_status "uploaded"
  exit 0
fi

REASON="fastlane_exit_${DELIVER_EXIT}"
if error_lines "$DELIVER_OUTPUT" | grep -Eiq 'could not find app|application not found|app not found'; then
  REASON="app_not_registered"
  log_info "app is not registered on ASC — run /autobot:testflight first"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'wrong size|invalid size|unsupported display family|screenshot dimensions'; then
  REASON="screenshot_size_invalid"
  log_info "one or more screenshots do not match a recognized ASC display family — regenerate at supported sizes (6.9\"/6.5\"/6.3\"/6.1\")"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'authentication failed|not authorized|invalid api key'; then
  REASON="auth_failed"
  log_info "verify ASC_API_KEY_ID / ISSUER_ID / .p8 path and key role (App Manager+)"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'could not edit app store information|app store information.*locked|screenshots cannot be uploaded'; then
  REASON="asc_state_locked"
  log_info "an existing version may be in review — check ASC web for current version state"
fi

log_error "fastlane deliver failed (screenshots): $REASON"
write_status "failed" "$REASON"
exit 4
