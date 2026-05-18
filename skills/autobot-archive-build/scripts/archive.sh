#!/bin/bash
# Archive an iOS app via `xcodebuild archive`.
# Single responsibility: produces an .xcarchive. No registration, no upload.
#
# Status output (optional, atomic):
#   AUTOBOT_ARCHIVE_STATUS_FILE  — JSON path; written via temp+rename
#
# Exit codes:
#   0  archive succeeded (or dry-run passed)
#   1  usage / input validation error
#   2  project/scheme missing or xcodebuild unavailable
#   4  xcodebuild archive failed
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

PROJECT_PATH=""
SCHEME=""
TEAM_ID=""
ARCHIVE_PATH=""
CONFIGURATION="Release"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: archive.sh --project-path <dir> --scheme <name> [--team-id <id>]
                  [--archive-path <path>] [--configuration <cfg>] [--dry-run]

Required:
  --project-path   Directory containing the .xcodeproj or .xcworkspace.
  --scheme         Xcode scheme name to archive.

Optional:
  --team-id        Apple Developer Team ID (10 alphanumeric uppercase).
                   Precedence: --team-id > $DEVELOPMENT_TEAM > pbxproj > config.json.
  --archive-path   Output .xcarchive path. Default: <project>/build/<scheme>.xcarchive.
  --configuration  Release (default) or Debug.
  --dry-run        Validate inputs and print the resolved xcodebuild invocation,
                   but do not call xcodebuild. Exits 0 if everything checks out.

Environment:
  AUTOBOT_ARCHIVE_STATUS_FILE (optional, JSON output, atomic write)
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
    --project-path)   require_value "$1" "${2:-}"; PROJECT_PATH="$2";   shift 2;;
    --scheme)         require_value "$1" "${2:-}"; SCHEME="$2";         shift 2;;
    --team-id)        require_value "$1" "${2:-}"; TEAM_ID="$2";        shift 2;;
    --archive-path)   require_value "$1" "${2:-}"; ARCHIVE_PATH="$2";   shift 2;;
    --configuration)  require_value "$1" "${2:-}"; CONFIGURATION="$2";  shift 2;;
    --dry-run)        DRY_RUN=1;                                         shift 1;;
    -h|--help)        usage; exit 0;;
    *)                log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$PROJECT_PATH" ] || [ -z "$SCHEME" ]; then
  log_error "--project-path and --scheme are required"
  usage >&2
  exit 1
fi

if [ ! -d "$PROJECT_PATH" ]; then
  log_error "--project-path is not a directory: $PROJECT_PATH"
  exit 2
fi

PROJECT_PATH="$(cd "$PROJECT_PATH" && pwd)"

# Locate .xcodeproj or .xcworkspace (workspace wins if both exist)
XCWORKSPACE="$(ls -d "$PROJECT_PATH"/*.xcworkspace 2>/dev/null | head -1 || true)"
XCODEPROJ="$(ls -d "$PROJECT_PATH"/*.xcodeproj 2>/dev/null | head -1 || true)"
if [ -z "$XCWORKSPACE" ] && [ -z "$XCODEPROJ" ]; then
  log_error "no .xcodeproj or .xcworkspace found in: $PROJECT_PATH"
  exit 2
fi

# python3 is needed for safe JSON emission
if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for safe JSON output"
  exit 1
fi

# Scheme validation — keep simple, Xcode allows fairly broad chars but we lock down
if ! printf '%s' "$SCHEME" | grep -Eq '^[A-Za-z0-9._ -]{1,100}$'; then
  log_error "scheme name invalid (allowed: A-Z a-z 0-9 . _ - space, 1..100 chars)"
  exit 1
fi

# Configuration must be Release or Debug
case "$CONFIGURATION" in
  Release|Debug) ;;
  *) log_error "--configuration must be Release or Debug (got: $CONFIGURATION)"; exit 1;;
esac

# Team ID precedence: arg → env → pbxproj → config.json
if [ -z "$TEAM_ID" ] && [ -n "${DEVELOPMENT_TEAM:-}" ]; then
  TEAM_ID="$DEVELOPMENT_TEAM"
fi
if [ -z "$TEAM_ID" ] && [ -n "$XCODEPROJ" ] && [ -f "$XCODEPROJ/project.pbxproj" ]; then
  # Extract the value AFTER `DEVELOPMENT_TEAM =`, not the variable name itself —
  # a naive `[A-Z0-9]{10}` on the whole line catches "DEVELOPMEN" from the keyword.
  TEAM_ID="$(sed -nE 's/.*DEVELOPMENT_TEAM[[:space:]]*=[[:space:]]*"?([A-Z0-9]{10})"?.*/\1/p' \
    "$XCODEPROJ/project.pbxproj" 2>/dev/null | head -1 || true)"
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
  CONFIG_SH="$PLUGIN_ROOT/skills/setup/scripts/config.sh"
  if [ -f "$CONFIG_SH" ]; then
    TEAM_ID="$(bash "$CONFIG_SH" get-or developmentTeam '' 2>/dev/null || echo '')"
  fi
fi

if [ -n "$TEAM_ID" ] && ! printf '%s' "$TEAM_ID" | grep -Eq '^[A-Z0-9]{10}$'; then
  log_error "team ID '$TEAM_ID' is not 10 uppercase alphanumeric characters"
  exit 1
fi

# Default archive path: <project>/build/<scheme>.xcarchive
if [ -z "$ARCHIVE_PATH" ]; then
  ARCHIVE_PATH="$PROJECT_PATH/build/${SCHEME}.xcarchive"
fi

# Ensure xcodebuild is available (skipped in --dry-run)
if [ "$DRY_RUN" -eq 0 ] && ! command -v xcodebuild &>/dev/null; then
  log_error "xcodebuild not found — install Xcode Command Line Tools"
  log_info  "run: xcode-select --install"
  exit 2
fi

# Safe JSON emission via python3
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

write_status() {
  local result="$1"
  local reason="${2:-}"
  local target="${AUTOBOT_ARCHIVE_STATUS_FILE:-}"
  [ -z "$target" ] && return 0

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "scheme=$SCHEME" \
    "archive_path=$ARCHIVE_PATH" \
    "configuration=$CONFIGURATION" \
    "team_id=$TEAM_ID" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

cleanup() {
  local rc=$?
  if [ -n "${AUTOBOT_ARCHIVE_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_ARCHIVE_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

# Resolve project target for xcodebuild
PROJECT_FLAG=()
if [ -n "$XCWORKSPACE" ]; then
  PROJECT_FLAG=(-workspace "$XCWORKSPACE")
else
  PROJECT_FLAG=(-project "$XCODEPROJ")
fi

log_info "project:       ${XCWORKSPACE:-$XCODEPROJ}"
log_info "scheme:        $SCHEME"
log_info "configuration: $CONFIGURATION"
log_info "archive path:  $ARCHIVE_PATH"
[ -n "$TEAM_ID" ] && log_info "team:          $TEAM_ID"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — would invoke:"
  python3 - "${PROJECT_FLAG[@]}" "$SCHEME" "$ARCHIVE_PATH" "$CONFIGURATION" "$TEAM_ID" <<'PY'
import shlex, sys
# argv: project_flag_name, project_path, scheme, archive_path, configuration, team_id
pflag, ppath, scheme, archive, config, team = sys.argv[1:7]
parts = [
    "xcodebuild archive",
    f"  {pflag} {shlex.quote(ppath)}",
    f"  -scheme {shlex.quote(scheme)}",
    f"  -archivePath {shlex.quote(archive)}",
    f"  -configuration {shlex.quote(config)}",
    "  -destination 'generic/platform=iOS'",
    "  -allowProvisioningUpdates",
    "  CODE_SIGN_STYLE=Automatic",
]
if team:
    parts.append(f"  DEVELOPMENT_TEAM={shlex.quote(team)}")
print(" \\\n".join(parts))
PY
  log_ok "dry-run validation passed"
  write_status "dry_run"
  exit 0
fi

# Build xcodebuild command
mkdir -p "$(dirname "$ARCHIVE_PATH")"

ARCHIVE_CMD=(
  xcodebuild archive
  "${PROJECT_FLAG[@]}"
  -scheme "$SCHEME"
  -archivePath "$ARCHIVE_PATH"
  -configuration "$CONFIGURATION"
  -destination "generic/platform=iOS"
  -allowProvisioningUpdates
  CODE_SIGN_STYLE=Automatic
)
[ -n "$TEAM_ID" ] && ARCHIVE_CMD+=("DEVELOPMENT_TEAM=$TEAM_ID")

set +e
"${ARCHIVE_CMD[@]}"
ARCHIVE_EXIT=$?
set -e

# xcodebuild can return 0 but fail to produce the archive; verify both.
if [ $ARCHIVE_EXIT -ne 0 ] || [ ! -d "$ARCHIVE_PATH" ]; then
  log_error "archive failed (xcodebuild exit $ARCHIVE_EXIT)"
  [ ! -d "$ARCHIVE_PATH" ] && log_info "archive directory was not created: $ARCHIVE_PATH"
  write_status "failed" "xcodebuild_exit_${ARCHIVE_EXIT}"
  exit 4
fi

log_ok "archive created: $ARCHIVE_PATH"
write_status "archived"
exit 0
