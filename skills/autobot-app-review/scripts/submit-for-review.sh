#!/bin/bash
# Submit current ASC draft version for App Store review.
#
# Two phases:
#   1. Poll until the latest uploaded build leaves PROCESSING state (via
#      `fastlane pilot builds`). Default timeout: 30 minutes, 60s interval.
#   2. Invoke `fastlane deliver --submit_for_review` with non-interactive
#      submission information defaults that match the Autobot scaffold
#      (no encryption, no IDFA, has rights, no 3rd-party content).
#
# Required env (ASC API Key):
#   ASC_API_KEY_ID
#   ASC_API_ISSUER_ID
#   ASC_API_KEY_PATH
#
# Status output (optional, atomic):
#   AUTOBOT_REVIEW_SUBMIT_STATUS_FILE
#
# Exit codes:
#   0  submitted (or dry-run passed, or already_in_review)
#   1  usage / input validation
#   2  ASC creds missing / .p8 unreadable
#   3  fastlane install failed
#   4  build processing timeout — retry later
#   5  fastlane deliver failed (see status.reason)
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

BUNDLE_ID=""
TEAM_ID=""
PLATFORM="ios"
AUTOMATIC_RELEASE=1
USES_ENCRYPTION=0
USES_IDFA=0
HAS_THIRD_PARTY=0
HAS_RIGHTS=1
WAIT_TIMEOUT=1800   # 30 minutes
WAIT_INTERVAL=60    # 60 seconds
SKIP_WAIT=0
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: submit-for-review.sh --bundle-id <id> [--team-id <id>] [--platform <p>]
                            [--no-auto-release] [--uses-encryption]
                            [--uses-idfa] [--has-third-party-content]
                            [--no-rights] [--wait-timeout <sec>]
                            [--wait-interval <sec>] [--skip-wait] [--dry-run]

Required:
  --bundle-id         Reverse-DNS App ID. App must already be registered on ASC.

Optional:
  --team-id           Apple Developer Team ID (10 alphanumeric uppercase).
  --platform          ios | appletvos | xros. Default: ios
  --no-auto-release   Hold for manual release after approval. Default: auto-release.

Submission information (defaults match Autobot's standard scaffold):
  --uses-encryption           Set if the app uses non-exempt encryption. Default: false.
  --uses-idfa                 Set if AdSupport / IDFA is in use. Default: false.
  --has-third-party-content   Set if content rights include third-party content. Default: false.
  --no-rights                 Set if you do NOT own/have rights to content. Default: has rights.

Build processing wait:
  --wait-timeout <sec>   Max seconds to wait for build to leave PROCESSING. Default: 1800.
  --wait-interval <sec>  Poll interval. Default: 60.
  --skip-wait            Do not poll — assume the build is already processed.

  --dry-run              Print resolved fastlane invocation; do not call it.
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
    --bundle-id)                require_value "$1" "${2:-}"; BUNDLE_ID="$2";     shift 2;;
    --team-id)                  require_value "$1" "${2:-}"; TEAM_ID="$2";       shift 2;;
    --platform)                 require_value "$1" "${2:-}"; PLATFORM="$2";      shift 2;;
    --no-auto-release)          AUTOMATIC_RELEASE=0;                              shift 1;;
    --uses-encryption)          USES_ENCRYPTION=1;                                shift 1;;
    --uses-idfa)                USES_IDFA=1;                                      shift 1;;
    --has-third-party-content)  HAS_THIRD_PARTY=1;                                shift 1;;
    --no-rights)                HAS_RIGHTS=0;                                     shift 1;;
    --wait-timeout)             require_value "$1" "${2:-}"; WAIT_TIMEOUT="$2";  shift 2;;
    --wait-interval)            require_value "$1" "${2:-}"; WAIT_INTERVAL="$2"; shift 2;;
    --skip-wait)                SKIP_WAIT=1;                                      shift 1;;
    --dry-run)                  DRY_RUN=1;                                        shift 1;;
    -h|--help)                  usage; exit 0;;
    *) log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$BUNDLE_ID" ]; then
  log_error "--bundle-id is required"
  usage >&2
  exit 1
fi

# Normalize bundle id (lowercase prefix, preserve last segment).
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

WORK_DIR="$(mktemp -d -t autobot-review-submit.XXXXXX)"
cleanup() {
  local rc=$?
  if [ -n "${WORK_DIR:-}" ] && [ -d "$WORK_DIR" ]; then
    find "$WORK_DIR" -type f -exec chmod 600 {} \; 2>/dev/null || true
    rm -rf "$WORK_DIR"
  fi
  if [ -n "${AUTOBOT_REVIEW_SUBMIT_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_REVIEW_SUBMIT_STATUS_FILE}.tmp.$$" 2>/dev/null || true
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
( umask 077
  emit_json \
    "key_id=$ASC_API_KEY_ID" \
    "issuer_id=$ASC_API_ISSUER_ID" \
    "key_filepath=$ASC_API_KEY_PATH" \
    > "$API_KEY_JSON"
)
chmod 600 "$API_KEY_JSON"

# Submission information JSON — covers ASC review questions that block
# non-interactive submit. All four fields are required by Apple as of 2024.
SUBMISSION_JSON="$WORK_DIR/submission_information.json"
python3 - "$USES_ENCRYPTION" "$USES_IDFA" "$HAS_THIRD_PARTY" "$HAS_RIGHTS" > "$SUBMISSION_JSON" <<'PY'
import json, sys
ue, ui, htp, hr = (v == "1" for v in sys.argv[1:5])
payload = {
    "export_compliance_uses_encryption": ue,
    "export_compliance_encryption_updated": False,
    "content_rights_contains_third_party_content": htp,
    "content_rights_has_rights": hr,
    "add_id_info_uses_idfa": ui,
}
if ui:
    payload.update({
        "add_id_info_serves_ads": False,
        "add_id_info_tracks_install": True,
        "add_id_info_tracks_action": False,
        "add_id_info_limits_tracking": True,
    })
print(json.dumps(payload, sort_keys=True))
PY
SUBMISSION_INFO="$(cat "$SUBMISSION_JSON")"

write_status() {
  local result="$1"
  local reason="${2:-}"
  local target="${AUTOBOT_REVIEW_SUBMIT_STATUS_FILE:-}"
  [ -z "$target" ] && return 0
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "bundle_id=$BUNDLE_ID" \
    "team_id=$TEAM_ID" \
    "platform=$PLATFORM" \
    "automatic_release=$AUTOMATIC_RELEASE" \
    "uses_encryption=$USES_ENCRYPTION" \
    "uses_idfa=$USES_IDFA" \
    "has_third_party_content=$HAS_THIRD_PARTY" \
    "has_rights=$HAS_RIGHTS" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

log_info "bundle:           $BUNDLE_ID"
log_info "platform:         $PLATFORM"
log_info "automatic_release:$AUTOMATIC_RELEASE"
log_info "submission_info:  $SUBMISSION_INFO"
[ -n "$TEAM_ID" ] && log_info "team:             $TEAM_ID"

# Phase 1: wait for build to leave PROCESSING (unless skipped or dry-run).
if [ "$DRY_RUN" -eq 0 ] && [ "$SKIP_WAIT" -eq 0 ]; then
  export FASTLANE_SKIP_UPDATE_CHECK=1
  export FASTLANE_HIDE_CHANGELOG=1
  export FASTLANE_HIDE_PLUGINS_TABLE=1
  export FASTLANE_DISABLE_COLORS=1
  export FASTLANE_OPT_OUT_USAGE=1
  export FASTLANE_SKIP_2FA_UPGRADE=1

  log_info "polling latest build state (timeout=${WAIT_TIMEOUT}s, interval=${WAIT_INTERVAL}s)"
  WAIT_DEADLINE=$(( $(date +%s) + WAIT_TIMEOUT ))
  LAST_STATE=""
  CONSECUTIVE_POLL_ERRORS=0
  POLL_ERROR_LIMIT=5   # tolerate transient ASC / network hiccups before bailing
  while :; do
    set +e
    PILOT_OUTPUT="$(
      fastlane pilot builds \
        --app_identifier "$BUNDLE_ID" \
        ${TEAM_ID:+--team_id "$TEAM_ID"} \
        --api_key_path "$API_KEY_JSON" \
        </dev/null 2>&1
    )"
    PILOT_EXIT=$?
    set -e

    # pilot prints a table. Pull the first non-header row's "Build State"
    # column. Accept variations across fastlane versions (older "Processing"
    # vs newer "PROCESSING" / "VALID" / "INVALID").
    LAST_STATE="$(printf '%s\n' "$PILOT_OUTPUT" \
      | grep -Ei 'processing|valid|invalid|expired' \
      | head -n 1 \
      | tr -d '|' \
      | awk '{
          for (i = NF; i >= 1; i--) {
            v = tolower($i)
            if (v == "processing" || v == "valid" || v == "invalid" || v == "expired") {
              print v; exit
            }
          }
        }' \
    )"

    if [ -z "$LAST_STATE" ] && [ $PILOT_EXIT -ne 0 ]; then
      CONSECUTIVE_POLL_ERRORS=$((CONSECUTIVE_POLL_ERRORS + 1))
      log_warn "pilot builds returned exit $PILOT_EXIT (transient ${CONSECUTIVE_POLL_ERRORS}/${POLL_ERROR_LIMIT})"
      if [ "$CONSECUTIVE_POLL_ERRORS" -ge "$POLL_ERROR_LIMIT" ]; then
        log_error "pilot builds failed ${POLL_ERROR_LIMIT} times in a row — cannot determine build state, aborting submit"
        write_status "failed" "pilot_unreachable"
        exit 4
      fi
      NOW=$(date +%s)
      if [ "$NOW" -ge "$WAIT_DEADLINE" ]; then
        log_error "timed out while pilot builds was failing (${WAIT_TIMEOUT}s)"
        write_status "failed" "build_processing_timeout"
        exit 4
      fi
      sleep "$WAIT_INTERVAL"
      continue
    fi
    CONSECUTIVE_POLL_ERRORS=0

    log_info "build state: ${LAST_STATE:-unknown}"
    case "$LAST_STATE" in
      valid)
        log_ok "build is VALID — ready for submission"
        break
        ;;
      invalid|expired)
        log_error "build state is $LAST_STATE — submission cannot proceed"
        write_status "failed" "build_${LAST_STATE}"
        exit 5
        ;;
    esac

    NOW=$(date +%s)
    if [ "$NOW" -ge "$WAIT_DEADLINE" ]; then
      log_error "timed out waiting for build to leave PROCESSING (${WAIT_TIMEOUT}s)"
      log_info  "retry: bash submit-for-review.sh --bundle-id $BUNDLE_ID --skip-wait"
      write_status "failed" "build_processing_timeout"
      exit 4
    fi
    sleep "$WAIT_INTERVAL"
  done
fi

# Phase 2: fastlane deliver --submit_for_review
AUTO_RELEASE_FLAG=""
[ "$AUTOMATIC_RELEASE" -eq 1 ] && AUTO_RELEASE_FLAG="--automatic_release true"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — would invoke:"
  python3 - "$BUNDLE_ID" "$PLATFORM" "$TEAM_ID" "$AUTO_RELEASE_FLAG" "$SUBMISSION_INFO" <<'PY'
import shlex, sys
bid, plat, team, ar, si = sys.argv[1:6]
parts = [
    "fastlane deliver",
    f"  --app_identifier {shlex.quote(bid)}",
    f"  --platform {shlex.quote(plat)}",
    "  --skip_binary_upload",
    "  --skip_metadata",
    "  --skip_screenshots",
    "  --skip_app_version_update",
    "  --force",
    "  --submit_for_review",
    "  --precheck_include_in_app_purchases false",
    f"  --submission_information {shlex.quote(si)}",
    "  --api_key_path <tempdir>/fastlane_api_key.json",
]
if ar:
    parts.append(f"  {ar}")
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
    --platform "$PLATFORM" \
    --skip_binary_upload \
    --skip_metadata \
    --skip_screenshots \
    --skip_app_version_update \
    --force \
    --submit_for_review \
    --precheck_include_in_app_purchases false \
    --submission_information "$SUBMISSION_INFO" \
    ${AUTO_RELEASE_FLAG} \
    ${TEAM_ID:+--team_id "$TEAM_ID"} \
    --api_key_path "$API_KEY_JSON" \
    </dev/null \
    2>&1
)"
DELIVER_EXIT=$?
set -e

printf '%s\n' "$DELIVER_OUTPUT"

error_lines() {
  printf '%s' "$1" | grep -Ei '^\[!\]|error|warning|could not|not found|not authorized|invalid|already|processing|missing' || true
}

if [ $DELIVER_EXIT -eq 0 ]; then
  log_ok "submitted for App Store review"
  write_status "submitted"
  exit 0
fi

REASON="fastlane_exit_${DELIVER_EXIT}"
if error_lines "$DELIVER_OUTPUT" | grep -Eiq 'already (been )?submitted|already in review|waiting for review'; then
  REASON="already_in_review"
  log_info "version is already submitted / waiting for review — treating as success"
  write_status "already_in_review"
  exit 0
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'could not find app|application not found|app not found'; then
  REASON="app_not_registered"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'build .* still processing|no build attached|missing build|build not yet available'; then
  REASON="build_not_ready"
  log_info "build is still processing on ASC — retry in a few minutes"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'authentication failed|not authorized|invalid api key'; then
  REASON="auth_failed"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'missing metadata|description.*required|keywords.*required|screenshot.*required|missing screenshot'; then
  REASON="missing_metadata_or_screenshots"
  log_info "ASC requires complete metadata + screenshots before submission — re-run upload steps"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'export compliance|encryption'; then
  REASON="export_compliance_question"
  log_info "review questions about encryption — verify --uses-encryption flag matches the binary's ITSAppUsesNonExemptEncryption"
elif error_lines "$DELIVER_OUTPUT" | grep -Eiq 'age rating|content rating'; then
  REASON="age_rating_missing"
  log_info "ASC age rating questionnaire must be answered manually in the web UI before re-running"
fi

log_error "fastlane deliver --submit_for_review failed: $REASON"
write_status "failed" "$REASON"
exit 5
