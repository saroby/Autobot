#!/bin/bash
# Export an .xcarchive to .ipa and upload to App Store Connect in one step.
# Single responsibility: export+upload. No registration, no archive, no testers.
#
# Auth: API Key if ASC_API_KEY_ID + ASC_API_ISSUER_ID + ASC_API_KEY_PATH all set.
#       Otherwise falls back to Xcode-stored credentials.
#
# Status output (optional, atomic):
#   AUTOBOT_UPLOAD_STATUS_FILE  — JSON path; written via temp+rename
#
# Exit codes:
#   0  uploaded, exported-only (--no-upload), or dry-run passed
#   1  usage / input validation error
#   2  archive missing or xcodebuild unavailable
#   4  export failed (no IPA produced)
#   5  export ok but upload failed (IPA exists for manual upload)
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

ARCHIVE_PATH=""
EXPORT_PATH=""
METHOD="app-store-connect"
INTERNAL_ONLY=1
NO_UPLOAD=0
DRY_RUN=0
TEAM_ID=""

usage() {
  cat <<'USAGE'
Usage: upload.sh --archive-path <path> [--export-path <dir>] [--method <m>]
                 [--no-internal-only] [--no-upload] [--team-id <id>] [--dry-run]

Required:
  --archive-path     Path to the .xcarchive (output of autobot-archive-build).

Optional:
  --export-path      IPA output directory. Default: <archive-dir>/export
  --method           ExportOptions method (app-store-connect | release-testing | development).
                     Default: app-store-connect
  --no-internal-only Allow external TestFlight distribution. Default: internal-only.
  --no-upload        Export to IPA but skip upload (destination: export).
  --team-id          Apple Developer Team ID (passed to xcodebuild if signing needs it).
  --dry-run          Validate inputs and print resolved xcodebuild invocation; do not run.

Environment:
  ASC_API_KEY_ID, ASC_API_ISSUER_ID, ASC_API_KEY_PATH (optional — auth via API Key)
  AUTOBOT_UPLOAD_STATUS_FILE (optional, JSON output)
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
    --archive-path)      require_value "$1" "${2:-}"; ARCHIVE_PATH="$2"; shift 2;;
    --export-path)       require_value "$1" "${2:-}"; EXPORT_PATH="$2";  shift 2;;
    --method)            require_value "$1" "${2:-}"; METHOD="$2";       shift 2;;
    --team-id)           require_value "$1" "${2:-}"; TEAM_ID="$2";      shift 2;;
    --no-internal-only)  INTERNAL_ONLY=0;                                 shift 1;;
    --no-upload)         NO_UPLOAD=1;                                     shift 1;;
    --dry-run)           DRY_RUN=1;                                       shift 1;;
    -h|--help)           usage; exit 0;;
    *)                   log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$ARCHIVE_PATH" ]; then
  log_error "--archive-path is required"
  usage >&2
  exit 1
fi

if [ ! -d "$ARCHIVE_PATH" ]; then
  log_error "archive not found: $ARCHIVE_PATH"
  log_info  "run autobot-archive-build first to produce the .xcarchive"
  exit 2
fi

# Normalize to absolute path
ARCHIVE_PATH="$(cd "$ARCHIVE_PATH" && pwd)"

case "$METHOD" in
  app-store-connect|release-testing|development) ;;
  *) log_error "--method must be app-store-connect | release-testing | development (got: $METHOD)"; exit 1;;
esac

if [ -n "$TEAM_ID" ] && ! printf '%s' "$TEAM_ID" | grep -Eq '^[A-Z0-9]{10}$'; then
  log_error "team ID '$TEAM_ID' is not 10 uppercase alphanumeric characters"
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for safe JSON output"
  exit 1
fi

# Default export path: sibling of archive
if [ -z "$EXPORT_PATH" ]; then
  EXPORT_PATH="$(dirname "$ARCHIVE_PATH")/export"
fi

# Auth selection
AUTH_METHOD="none"
ASC_API_KEY_PATH_EXPANDED=""
if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ]; then
  ASC_API_KEY_PATH_EXPANDED="${ASC_API_KEY_PATH/#\~/$HOME}"
  if [ ! -r "$ASC_API_KEY_PATH_EXPANDED" ]; then
    log_error "ASC_API_KEY_PATH not readable: $ASC_API_KEY_PATH"
    exit 2
  fi
  AUTH_METHOD="api_key"
elif [ "$NO_UPLOAD" -eq 0 ]; then
  AUTH_METHOD="xcode_account"
  log_warn "no ASC API Key found — falling back to Xcode-stored credentials"
  log_info "ensure Apple ID is signed in at Xcode → Settings → Accounts"
fi

if [ "$DRY_RUN" -eq 0 ] && ! command -v xcodebuild &>/dev/null; then
  log_error "xcodebuild not found — install Xcode Command Line Tools"
  exit 2
fi

# Working directory for ExportOptions.plist (auto-cleaned)
WORK_DIR="$(mktemp -d -t autobot-upload.XXXXXX)"
cleanup() {
  local rc=$?
  [ -n "${WORK_DIR:-}" ] && [ -d "$WORK_DIR" ] && rm -rf "$WORK_DIR"
  if [ -n "${AUTOBOT_UPLOAD_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_UPLOAD_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

EXPORT_OPTIONS="$WORK_DIR/ExportOptions.plist"
DESTINATION="upload"
[ "$NO_UPLOAD" -eq 1 ] && DESTINATION="export"

# Build ExportOptions.plist via python3 (safe quoting)
python3 - "$EXPORT_OPTIONS" "$METHOD" "$DESTINATION" "$INTERNAL_ONLY" <<'PY'
import sys
out, method, destination, internal_only = sys.argv[1:5]
internal_only = internal_only == "1"
keys = [
    ("method", method),
    ("destination", destination),
    ("signingStyle", "automatic"),
    ("uploadSymbols", True),
    ("manageAppVersionAndBuildNumber", True),
]
if internal_only:
    keys.append(("testFlightInternalTestingOnly", True))

def render(v):
    if isinstance(v, bool):
        return "<true/>" if v else "<false/>"
    return f"<string>{v}</string>"

body = "\n".join(f"    <key>{k}</key>\n    {render(v)}" for k, v in keys)
content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
{body}
</dict>
</plist>
'''
with open(out, "w") as f:
    f.write(content)
PY

emit_json() {
  python3 -c '
import json, sys
data = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    if v in ("true", "false"):
        data[k] = (v == "true")
    else:
        data[k] = v
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
' "$@"
}

write_status() {
  local result="$1"
  local upload_success="$2"
  local ipa_path="${3:-}"
  local reason="${4:-}"
  local target="${AUTOBOT_UPLOAD_STATUS_FILE:-}"
  [ -z "$target" ] && return 0

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "archive_path=$ARCHIVE_PATH" \
    "export_path=$EXPORT_PATH" \
    "ipa_path=$ipa_path" \
    "method=$METHOD" \
    "auth_method=$AUTH_METHOD" \
    "upload_success=$upload_success" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

log_info "archive:     $ARCHIVE_PATH"
log_info "export:      $EXPORT_PATH"
log_info "method:      $METHOD"
log_info "destination: $DESTINATION"
log_info "auth:        $AUTH_METHOD"
[ -n "$TEAM_ID" ] && log_info "team:        $TEAM_ID"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — would invoke:"
  python3 - "$ARCHIVE_PATH" "$EXPORT_PATH" "$EXPORT_OPTIONS" "$AUTH_METHOD" \
    "${ASC_API_KEY_PATH_EXPANDED:-}" "${ASC_API_KEY_ID:-}" "${ASC_API_ISSUER_ID:-}" "$TEAM_ID" <<'PY'
import shlex, sys
ap, ep, opt, auth, kp, kid, iid, team = sys.argv[1:9]
parts = [
    "xcodebuild -exportArchive",
    f"  -archivePath {shlex.quote(ap)}",
    f"  -exportOptionsPlist {shlex.quote(opt)}",
    f"  -exportPath {shlex.quote(ep)}",
    "  -allowProvisioningUpdates",
]
if auth == "api_key":
    parts += [
        f"  -authenticationKeyPath {shlex.quote(kp)}",
        f"  -authenticationKeyID {shlex.quote(kid)}",
        f"  -authenticationKeyIssuerID {shlex.quote(iid)}",
    ]
if team:
    parts.append(f"  DEVELOPMENT_TEAM={shlex.quote(team)}")
print(" \\\n".join(parts))
PY
  log_ok "dry-run validation passed"
  write_status "dry_run" "false"
  exit 0
fi

mkdir -p "$EXPORT_PATH"

EXPORT_CMD=(
  xcodebuild -exportArchive
  -archivePath "$ARCHIVE_PATH"
  -exportOptionsPlist "$EXPORT_OPTIONS"
  -exportPath "$EXPORT_PATH"
  -allowProvisioningUpdates
)
if [ "$AUTH_METHOD" = "api_key" ]; then
  EXPORT_CMD+=(
    -authenticationKeyPath "$ASC_API_KEY_PATH_EXPANDED"
    -authenticationKeyID "$ASC_API_KEY_ID"
    -authenticationKeyIssuerID "$ASC_API_ISSUER_ID"
  )
fi
[ -n "$TEAM_ID" ] && EXPORT_CMD+=("DEVELOPMENT_TEAM=$TEAM_ID")

set +e
"${EXPORT_CMD[@]}"
EXPORT_EXIT=$?
set -e

# Find IPA regardless of exit code — Apple sometimes returns nonzero for upload
# failures after IPA was already exported.
IPA_FILE="$(ls "$EXPORT_PATH"/*.ipa 2>/dev/null | head -1 || true)"

if [ $EXPORT_EXIT -eq 0 ]; then
  if [ "$NO_UPLOAD" -eq 1 ]; then
    log_ok "exported (no upload requested): ${IPA_FILE:-$EXPORT_PATH}"
    write_status "exported_only" "false" "${IPA_FILE:-}"
    exit 0
  fi
  log_ok "uploaded to App Store Connect"
  write_status "uploaded" "true" "${IPA_FILE:-}"
  exit 0
fi

if [ -n "$IPA_FILE" ] && [ "$NO_UPLOAD" -eq 0 ]; then
  log_warn "export succeeded but upload failed (xcodebuild exit $EXPORT_EXIT)"
  log_info "IPA at: $IPA_FILE"
  log_info "manual upload: Xcode Organizer → Distribute App, or Apple Transporter (Mac App Store)"
  write_status "upload_failed" "false" "$IPA_FILE" "xcodebuild_exit_${EXPORT_EXIT}"
  exit 5
fi

log_error "export failed (xcodebuild exit $EXPORT_EXIT)"
write_status "export_failed" "false" "" "xcodebuild_exit_${EXPORT_EXIT}"
exit 4
