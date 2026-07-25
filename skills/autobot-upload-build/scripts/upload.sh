#!/bin/bash
# Export an .xcarchive to .ipa and upload to App Store Connect in one step.
# Single responsibility: export+upload. No registration, no archive, no testers.
#
# Auth: API Key if APP_STORE_CONNECT_API_KEY_KEY_ID + APP_STORE_CONNECT_API_KEY_ISSUER_ID + APP_STORE_CONNECT_API_KEY_KEY_FILEPATH all set.
#       Otherwise falls back to Xcode-stored credentials.
#
# Status output (optional, atomic):
#   AUTOBOT_UPLOAD_STATUS_FILE  — JSON path; written via temp+rename
#
# Exit codes:
#   0  uploaded, already_uploaded (a duplicate rejection AFTER this run's own
#      upload attempt initiated — our binary landed), exported-only
#      (--no-upload), or dry-run passed
#   1  usage / input validation error
#   2  archive missing or xcodebuild unavailable
#   4  export failed (no IPA produced)
#   5  export ok but upload failed (IPA exists for manual upload) — only after
#      --retries (default 2) bounded auto-retries of the transient upload class
#   6  build number conflict: on the FIRST attempt ASC already has this bundle
#      version (from a prior run), so nothing was uploaded and the ASC binary is
#      not this build — bump the build number and re-archive
set -euo pipefail

RELEASE_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../scripts" && pwd)/release_env.sh"
. "$RELEASE_ENV"
autobot_load_release_env "${CLAUDE_PROJECT_DIR:-.}"

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
RETRIES=2
ARCHIVE_APP_PATH=""
ARCHIVE_BUNDLE_ID=""
ARCHIVE_VERSION=""
ARCHIVE_BUILD=""
ARCHIVE_DIGEST=""
ARCHIVE_CODESIGN_STATUS=""
IPA_BUNDLE_ID=""
IPA_VERSION=""
IPA_BUILD=""
IPA_DIGEST=""
STATUS_BUILD_ID=""
STATUS_INPUT_MANIFEST_HASH=""
STATUS_BUNDLE_ID=""
BUILD_STATE_PATH=""
ARCHIVE_STATUS_PATH=""

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
SELF_DIR="$(cd "$(dirname "$REAL_SOURCE")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$SELF_DIR/../../.." && pwd)}"

usage() {
  cat <<'USAGE'
Usage: upload.sh --archive-path <path> [--export-path <dir>] [--method <m>]
                 --build-state <path> [--archive-status <path>]
                 [--no-internal-only] [--no-upload] [--team-id <id>]
                 [--retries <n>] [--dry-run]

Required:
  --archive-path     Path to the .xcarchive (output of autobot-archive-build).

Optional:
  --build-state      Explicit Autobot build-state.json owning this archive.
                     Required for every export/upload operation.
  --archive-status   Explicit archive-status.json proving buildId and archive digest.
                     Required unless --no-upload is used.
  --export-path      IPA output directory. Default: <archive-dir>/export
  --method           ExportOptions method (app-store-connect | release-testing | development).
                     Default: app-store-connect
  --no-internal-only Allow external TestFlight distribution. Default: internal-only.
  --no-upload        Export to IPA but skip upload (destination: export).
  --team-id          Apple Developer Team ID (passed to xcodebuild if signing needs it).
  --retries          Bounded auto-retries for transient upload failures (export OK,
                     upload failed — ASC 5xx / network). Linear backoff 30s/60s/...
                     Export/signing failures are never retried. Default: 2.
  --dry-run          Validate inputs and print resolved xcodebuild invocation; do not run.

Environment:
  APP_STORE_CONNECT_API_KEY_KEY_ID, APP_STORE_CONNECT_API_KEY_ISSUER_ID, APP_STORE_CONNECT_API_KEY_KEY_FILEPATH (optional — auth via API Key)
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
    --build-state)       require_value "$1" "${2:-}"; BUILD_STATE_PATH="$2"; shift 2;;
    --archive-status)    require_value "$1" "${2:-}"; ARCHIVE_STATUS_PATH="$2"; shift 2;;
    --export-path)       require_value "$1" "${2:-}"; EXPORT_PATH="$2";  shift 2;;
    --method)            require_value "$1" "${2:-}"; METHOD="$2";       shift 2;;
    --team-id)           require_value "$1" "${2:-}"; TEAM_ID="$2";      shift 2;;
    --retries)           require_value "$1" "${2:-}"; RETRIES="$2";      shift 2;;
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

if [ -z "$BUILD_STATE_PATH" ] || [ ! -r "$BUILD_STATE_PATH" ]; then
  log_error "--build-state must name a readable build-state.json"
  exit 1
fi
BUILD_STATE_PATH="$(cd "$(dirname "$BUILD_STATE_PATH")" && pwd)/$(basename "$BUILD_STATE_PATH")"
if [ "$NO_UPLOAD" -eq 0 ] && { [ -z "$ARCHIVE_STATUS_PATH" ] || [ ! -r "$ARCHIVE_STATUS_PATH" ]; }; then
  log_error "--archive-status must name a readable archive-status.json for upload"
  exit 1
fi
if [ -n "$ARCHIVE_STATUS_PATH" ]; then
  ARCHIVE_STATUS_PATH="$(cd "$(dirname "$ARCHIVE_STATUS_PATH")" && pwd)/$(basename "$ARCHIVE_STATUS_PATH")"
fi

if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for artifact verification and safe JSON output"
  exit 1
fi

# Bind release status to the explicitly selected Autobot build. Never infer
# identity from cwd or a nearby checkout: ambient paths are not provenance.
IFS=$'\t' read -r STATUS_BUILD_ID STATUS_BUNDLE_ID STATUS_INPUT_MANIFEST_HASH < <(
  python3 - "$BUILD_STATE_PATH" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    state = json.load(handle)
print("\t".join(str(value or "") for value in (
    state.get("buildId"),
    state.get("bundleId"),
    (((state.get("phases") or {}).get("5") or {}).get("inputHash")),
)))
PY
)
if [ -z "$STATUS_BUILD_ID" ] || [ -z "$STATUS_BUNDLE_ID" ]; then
  log_error "build-state.json must contain buildId and bundleId"
  exit 1
fi

# Validate the archive's exact embedded identity before export. This also
# rejects empty/multi-app archives and bad executables/signatures.
set +e
ARCHIVE_JSON="$(python3 "$PLUGIN_ROOT/scripts/artifact_provenance.py" \
  inspect-archive --archive-path "$ARCHIVE_PATH" 2>&1)"
ARCHIVE_VERIFY_EXIT=$?
set -e
if [ $ARCHIVE_VERIFY_EXIT -ne 0 ]; then
  log_error "archive artifact verification failed: $ARCHIVE_JSON"
  exit 2
fi
json_field() {
  python3 -c 'import json,sys; value=json.loads(sys.argv[1]).get(sys.argv[2], ""); print(value)' "$1" "$2"
}
ARCHIVE_APP_PATH="$(json_field "$ARCHIVE_JSON" appPath)"
ARCHIVE_BUNDLE_ID="$(json_field "$ARCHIVE_JSON" bundleId)"
ARCHIVE_VERSION="$(json_field "$ARCHIVE_JSON" version)"
ARCHIVE_BUILD="$(json_field "$ARCHIVE_JSON" build)"
ARCHIVE_DIGEST="$(json_field "$ARCHIVE_JSON" archiveDigest)"
ARCHIVE_CODESIGN_STATUS="$(json_field "$ARCHIVE_JSON" codesignStatus)"

if [ "$ARCHIVE_BUNDLE_ID" != "$STATUS_BUNDLE_ID" ]; then
  log_error "archive bundleId does not match build-state.json"
  exit 2
fi
if [ -n "$ARCHIVE_STATUS_PATH" ]; then
  IFS=$'\t' read -r EXPECTED_BUILD_ID EXPECTED_ARCHIVE_DIGEST < <(
    python3 - "$ARCHIVE_STATUS_PATH" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    status = json.load(handle)
print("\t".join(str(value or "") for value in (
    status.get("buildId"), status.get("archiveSha256") or status.get("archive_digest")
)))
PY
  )
  if [ "$EXPECTED_BUILD_ID" != "$STATUS_BUILD_ID" ]; then
    log_error "archive-status buildId does not match build-state.json"
    exit 2
  fi
  if [ "$EXPECTED_ARCHIVE_DIGEST" != "$ARCHIVE_DIGEST" ]; then
    log_error "archive digest does not match archive-status.json"
    exit 2
  fi
fi

# Export Compliance: reject archives whose embedded Info.plist is missing
# ITSAppUsesNonExemptEncryption. Such uploads land on ASC as "Missing Compliance"
# ("수출 규정 관련 문서 누락") and block TestFlight installs until manually answered.
# autobot-archive-build always injects this; this check defends against externally
# produced .xcarchive bundles passed in via --archive-path.
if ! plutil -extract ITSAppUsesNonExemptEncryption raw "$ARCHIVE_APP_PATH/Info.plist" &>/dev/null; then
  log_error "archive Info.plist missing ITSAppUsesNonExemptEncryption — would trigger '수출 규정 관련 문서 누락' on ASC"
  log_info  "re-archive with autobot-archive-build, or set INFOPLIST_KEY_ITSAppUsesNonExemptEncryption=NO in the target"
  exit 2
fi

case "$METHOD" in
  app-store-connect|release-testing|development) ;;
  *) log_error "--method must be app-store-connect | release-testing | development (got: $METHOD)"; exit 1;;
esac

if [ -n "$TEAM_ID" ] && ! printf '%s' "$TEAM_ID" | grep -Eq '^[A-Z0-9]{10}$'; then
  log_error "team ID '$TEAM_ID' is not 10 uppercase alphanumeric characters"
  exit 1
fi

if ! printf '%s' "$RETRIES" | grep -Eq '^[0-9]+$'; then
  log_error "--retries must be a non-negative integer (got: $RETRIES)"
  exit 1
fi

# Linear backoff base for transient upload retries. Overridable so tests can
# exercise the retry path without a real 30s sleep.
BACKOFF_BASE="${AUTOBOT_UPLOAD_BACKOFF_SECONDS:-30}"
if ! printf '%s' "$BACKOFF_BASE" | grep -Eq '^[0-9]+$'; then
  BACKOFF_BASE=30
fi

# Default export path: sibling of archive
if [ -z "$EXPORT_PATH" ]; then
  EXPORT_PATH="$(dirname "$ARCHIVE_PATH")/export"
fi

# Auth selection
AUTH_METHOD="none"
APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED=""
if [ -n "${APP_STORE_CONNECT_API_KEY_KEY_ID:-}" ] && [ -n "${APP_STORE_CONNECT_API_KEY_ISSUER_ID:-}" ] && [ -n "${APP_STORE_CONNECT_API_KEY_KEY_FILEPATH:-}" ]; then
  APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED="${APP_STORE_CONNECT_API_KEY_KEY_FILEPATH/#\~/$HOME}"
  if [ ! -r "$APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED" ]; then
    log_error "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH not readable: $APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"
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
    if k == "schemaVersion":
        data[k] = int(v)
    elif v in ("true", "false"):
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
  local canonical_bundle_id="${IPA_BUNDLE_ID:-$ARCHIVE_BUNDLE_ID}"
  local canonical_version="${IPA_VERSION:-$ARCHIVE_VERSION}"
  local canonical_build="${IPA_BUILD:-$ARCHIVE_BUILD}"
  local canonical_artifact_digest="${IPA_DIGEST:-$ARCHIVE_DIGEST}"

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "schemaVersion=1" \
    "result=$result" \
    "buildId=$STATUS_BUILD_ID" \
    "bundleId=$canonical_bundle_id" \
    "version=$canonical_version" \
    "buildNumber=$canonical_build" \
    "artifactSha256=$canonical_artifact_digest" \
    "archiveSha256=$ARCHIVE_DIGEST" \
    "ipaSha256=$IPA_DIGEST" \
    "inputManifestHash=$STATUS_INPUT_MANIFEST_HASH" \
    "archive_path=$ARCHIVE_PATH" \
    "export_path=$EXPORT_PATH" \
    "ipa_path=$ipa_path" \
    "method=$METHOD" \
    "auth_method=$AUTH_METHOD" \
    "upload_success=$upload_success" \
    "reason=$reason" \
    "archive_app_path=$ARCHIVE_APP_PATH" \
    "archive_bundle_id=$ARCHIVE_BUNDLE_ID" \
    "archive_version=$ARCHIVE_VERSION" \
    "archive_build=$ARCHIVE_BUILD" \
    "archive_digest=$ARCHIVE_DIGEST" \
    "archive_codesign_status=$ARCHIVE_CODESIGN_STATUS" \
    "ipa_bundle_id=$IPA_BUNDLE_ID" \
    "ipa_version=$IPA_VERSION" \
    "ipa_build=$IPA_BUILD" \
    "ipa_digest=$IPA_DIGEST" \
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
    "${APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED:-}" "${APP_STORE_CONNECT_API_KEY_KEY_ID:-}" "${APP_STORE_CONNECT_API_KEY_ISSUER_ID:-}" "$TEAM_ID" <<'PY'
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
# The export directory is an output workspace, not evidence storage. Remove
# prior IPAs so a successful xcodebuild invocation cannot be paired with a
# stale package from an earlier run.
shopt -s nullglob
STALE_IPAS=("$EXPORT_PATH"/*.ipa)
shopt -u nullglob
if [ ${#STALE_IPAS[@]} -gt 0 ]; then
  rm -f -- "${STALE_IPAS[@]}"
fi

EXPORT_CMD=(
  xcodebuild -exportArchive
  -archivePath "$ARCHIVE_PATH"
  -exportOptionsPlist "$EXPORT_OPTIONS"
  -exportPath "$EXPORT_PATH"
  -allowProvisioningUpdates
)
if [ "$AUTH_METHOD" = "api_key" ]; then
  EXPORT_CMD+=(
    -authenticationKeyPath "$APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED"
    -authenticationKeyID "$APP_STORE_CONNECT_API_KEY_KEY_ID"
    -authenticationKeyIssuerID "$APP_STORE_CONNECT_API_KEY_ISSUER_ID"
  )
fi
[ -n "$TEAM_ID" ] && EXPORT_CMD+=("DEVELOPMENT_TEAM=$TEAM_ID")

# Transient upload failures (IPA exported, ASC rejected/network — 5xx class) are
# retried in place up to --retries times. Export/signing failures are NOT retried:
# they are deterministic, not transient.
# ponytail: retry re-runs -exportArchive (re-export from the same .xcarchive is
# cheap vs. archive); switch to an IPA-only uploader if re-export time ever matters.
ATTEMPT=0
while :; do
  ATTEMPT_LOG="$WORK_DIR/export-attempt-${ATTEMPT}.log"
  set +e
  "${EXPORT_CMD[@]}" 2>&1 | tee "$ATTEMPT_LOG"
  EXPORT_EXIT=${PIPESTATUS[0]}
  set -e

  # Find IPA regardless of exit code — Apple sometimes returns nonzero for upload
  # failures after IPA was already exported.
  shopt -s nullglob
  IPA_FILES=("$EXPORT_PATH"/*.ipa)
  shopt -u nullglob
  IPA_FILE="${IPA_FILES[0]:-}"
  IPA_COUNT=${#IPA_FILES[@]}

  [ $EXPORT_EXIT -eq 0 ] && break
  # ASC rejecting the binary as a duplicate. Interpretation depends on whether
  # THIS run has already initiated an upload:
  #   - ATTEMPT >= 1: a prior attempt this run started the upload then failed
  #     ambiguously (transient 5xx/network) and actually landed the binary; the
  #     redundant response confirms our own upload. Treat as success.
  #   - ATTEMPT == 0 (first attempt): this run uploaded nothing yet, so the
  #     binary already on ASC belongs to a PREVIOUS run. Shipping it as
  #     "already uploaded" would send an OLD binary to review — hard-fail and
  #     require a build-number bump.
  # Classified BEFORE the transient check so retries never re-upload the build.
  if [ "$IPA_COUNT" -eq 1 ] && [ "$NO_UPLOAD" -eq 0 ] \
    && grep -Eiq 'redundant binary|already been used|bundle version must be higher|previously uploaded' "$ATTEMPT_LOG"; then
    if [ "$ATTEMPT" -ge 1 ]; then
      log_warn "ASC reports this bundle version already exists after an earlier upload attempt this run (content match unverified)"
      log_warn "if the code changed mid-run, bump the build number and re-archive"
      log_ok "binary already on App Store Connect from an earlier attempt this run — treating as uploaded"
      write_status "already_uploaded" "true" "$IPA_FILE"
      exit 0
    fi
    log_error "ASC already has bundle version ${ARCHIVE_VERSION} (build ${ARCHIVE_BUILD}) from a prior run — build number conflict"
    log_error "this run has uploaded nothing yet, so the binary on ASC is NOT this build; shipping it would send an old binary to review"
    log_info  "bump CFBundleVersion (build number) and re-run autobot-archive-build, then upload again"
    write_status "build_number_conflict" "false" "$IPA_FILE" "build_number_conflict"
    exit 6
  fi
  TRANSIENT_UPLOAD_FAILURE=0
  if grep -Eiq 'HTTP[^0-9]*5[0-9][0-9]|timed? out|network|connection (reset|refused)|temporar(il)?y unavailable|service unavailable|NSURLError' "$ATTEMPT_LOG"; then
    TRANSIENT_UPLOAD_FAILURE=1
  fi
  if [ "$IPA_COUNT" -eq 1 ] && [ "$NO_UPLOAD" -eq 0 ] \
    && [ "$TRANSIENT_UPLOAD_FAILURE" -eq 1 ] && [ "$ATTEMPT" -lt "$RETRIES" ]; then
    ATTEMPT=$((ATTEMPT + 1))
    BACKOFF=$((BACKOFF_BASE * ATTEMPT))
    log_warn "upload failed (xcodebuild exit $EXPORT_EXIT) — auto-retry $ATTEMPT/$RETRIES in ${BACKOFF}s"
    sleep "$BACKOFF"
    continue
  fi
  if [ "$IPA_COUNT" -eq 1 ] && [ "$NO_UPLOAD" -eq 0 ] \
    && [ "$TRANSIENT_UPLOAD_FAILURE" -eq 0 ]; then
    log_warn "upload failure is not classified as transient — refusing automatic retry"
  fi
  break
done

if [ $EXPORT_EXIT -eq 0 ] && [ "$IPA_COUNT" -ne 1 ]; then
  if [ "$IPA_COUNT" -eq 0 ]; then
    REASON="ipa_artifact_missing"
  else
    REASON="multiple_ipa_artifacts"
  fi
  log_error "export returned success but expected exactly one IPA; found $IPA_COUNT"
  write_status "export_failed" "false" "" "$REASON"
  exit 4
fi

if [ $EXPORT_EXIT -eq 0 ]; then
  set +e
  IPA_JSON="$(python3 "$PLUGIN_ROOT/scripts/artifact_provenance.py" \
    inspect-ipa --ipa-path "$IPA_FILE" 2>&1)"
  IPA_VERIFY_EXIT=$?
  set -e
  if [ $IPA_VERIFY_EXIT -ne 0 ]; then
    log_error "IPA artifact verification failed: $IPA_JSON"
    write_status "export_failed" "false" "$IPA_FILE" "invalid_ipa_artifact"
    exit 4
  fi
  IPA_BUNDLE_ID="$(json_field "$IPA_JSON" bundleId)"
  IPA_VERSION="$(json_field "$IPA_JSON" version)"
  IPA_BUILD="$(json_field "$IPA_JSON" build)"
  IPA_DIGEST="$(json_field "$IPA_JSON" artifactDigest)"
  if [ "$IPA_BUNDLE_ID" != "$ARCHIVE_BUNDLE_ID" ] \
    || [ "$IPA_VERSION" != "$ARCHIVE_VERSION" ] \
    || [ "$IPA_BUILD" != "$ARCHIVE_BUILD" ]; then
    log_error "IPA identity does not match archive (bundle/version/build)"
    write_status "export_failed" "false" "$IPA_FILE" "ipa_identity_mismatch"
    exit 4
  fi
  if [ "$NO_UPLOAD" -eq 1 ]; then
    log_ok "exported (no upload requested): $IPA_FILE"
    write_status "exported_only" "false" "$IPA_FILE"
    exit 0
  fi
  log_ok "uploaded to App Store Connect"
  write_status "uploaded" "true" "${IPA_FILE:-}"
  exit 0
fi

if [ -n "$IPA_FILE" ] && [ "$NO_UPLOAD" -eq 0 ]; then
  log_warn "export succeeded but upload failed (xcodebuild exit $EXPORT_EXIT, after $ATTEMPT auto-retries)"
  log_info "IPA at: $IPA_FILE"
  log_info "manual upload: Xcode Organizer → Distribute App, or Apple Transporter (Mac App Store)"
  write_status "upload_failed" "false" "$IPA_FILE" "xcodebuild_exit_${EXPORT_EXIT}"
  exit 5
fi

log_error "export failed (xcodebuild exit $EXPORT_EXIT)"
write_status "export_failed" "false" "" "xcodebuild_exit_${EXPORT_EXIT}"
exit 4
