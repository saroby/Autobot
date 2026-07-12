#!/bin/bash
# Register a new iOS app on App Store Connect via `fastlane produce`.
# Idempotent on bundle-ID collisions for the SAME team. App-name collisions
# (different developer using the same name) are reported as registration
# failures, not silent successes.
#
# AUTH MODEL (important — different from every other deploy step):
#   App-record creation goes through Apple's PRIVATE iris API
#   (Spaceship::ConnectAPI.login) — the public App Store Connect API has no
#   app-creation endpoint, so ASC API keys CANNOT authenticate this step.
#   (`--api_key_path` was never a valid `produce` option.) The only
#   non-interactive auth is a cached spaceship web session:
#     fastlane spaceauth -u <apple-id>    # interactive 2FA once, ~30 days valid
#   or FASTLANE_SESSION exported from that command's output.
#
# Apple ID precedence:
#   1) --apple-id flag
#   2) FASTLANE_USER env var
#   3) APPLE_ID env var
#   4) ~/.autobot/config.json:appleId (via skills/autobot-setup/scripts/config.sh)
#
# Team ID precedence (matches autobot-setup convention):
#   1) --team-id flag
#   2) DEVELOPMENT_TEAM env var
#   3) ~/.autobot/config.json:developmentTeam (via skills/autobot-setup/scripts/config.sh)
#
# Optional env:
#   AUTOBOT_REGISTER_STATUS_FILE  — JSON status output path (atomic write via temp+rename)
#   FASTLANE_SESSION              — spaceship session (alternative to the cookie cache)
#
# Exit codes:
#   0  ok (registered or already exists on YOUR team)
#   1  usage / input validation error
#   2  missing Apple ID or no ASC session (run `fastlane spaceauth`)
#   3  fastlane install failed
#   4  registration failed (fastlane error — see status reason)
set -euo pipefail

# ── Logging helpers (CONVENTIONS.md output-prefix policy) ──
# ── Load ASC secrets from .env WITHOUT clobbering already-set vars ──
# Precedence: inherited env > project ./.env > global ~/.autobot/.env. Secrets
# live in .env only (never config.json); /autobot:setup writes the global one so
# one setup serves every project. Lines are KEY='value' (config.sh set-env), so
# eval honours their quoting. An explicitly-exported var always wins.
for _ef in ".env" "${AUTOBOT_CONFIG_DIR:-$HOME/.autobot}/.env"; do
  [ -f "$_ef" ] || continue
  while IFS= read -r _line || [ -n "$_line" ]; do
    _line="${_line#"${_line%%[![:space:]]*}"}"   # strip leading whitespace
    case "$_line" in ''|\#*) continue;; esac
    _line="${_line#export }"                      # tolerate `export KEY=val`
    _k="${_line%%=*}"
    case "$_k" in *[!A-Za-z0-9_]*|'') continue;; esac
    [ -n "${!_k:-}" ] && continue
    eval "export ${_line}"
  done < "$_ef"
done

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }
log_fatal() { printf 'FATAL: %s\n' "$*" >&2; }

BUNDLE_ID=""
DISPLAY_NAME=""
TEAM_ID=""
APPLE_ID_ARG=""
SKU=""
LANGUAGE="ko"
APP_VERSION="1.0.0"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: register-app.sh --bundle-id <id> --display-name <name> [--team-id <id>]
                       [--sku <sku>] [--language <code>] [--app-version <ver>]

Required:
  --bundle-id      Reverse-DNS App ID. Prefix is normalized to lowercase, but
                   the last segment (app name) preserves the case you supply,
                   so PascalCase like `com.axi.MyApp` round-trips intact.
                   Example: com.axi.MyApp
  --display-name   App Store display name (2..30 characters).

Optional:
  --apple-id       Apple ID used for the App Store Connect web session.
                   Precedence: --apple-id > $FASTLANE_USER > $APPLE_ID
                   > config.json:appleId.
  --team-id        Apple Developer Team ID (10 alphanumeric uppercase).
                   Precedence: --team-id > $DEVELOPMENT_TEAM > config.json.
  --sku            Unique SKU. Defaults to bundle-id.
  --language       Primary language code. Default: ko
  --app-version    Initial version string. Default: 1.0.0
  --dry-run        Validate inputs and print the resolved fastlane invocation,
                   but do not call fastlane. Exits 0 if everything checks out.

Auth (app creation uses Apple's private API — ASC API keys do not work here):
  cached spaceship session (`fastlane spaceauth -u <apple-id>`, ~30 days)
  or FASTLANE_SESSION env var.

Environment:
  FASTLANE_SESSION (optional, alternative to the cookie cache)
  AUTOBOT_REGISTER_STATUS_FILE (optional, JSON output)
USAGE
}

# Flag parser with missing-value guards
require_value() {
  # require_value <flag> <value-or-empty>
  if [ -z "${2:-}" ] || [[ "${2:-}" == --* ]]; then
    log_error "$1 requires a value"
    usage >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --bundle-id)    require_value "$1" "${2:-}"; BUNDLE_ID="$2";    shift 2;;
    --display-name) require_value "$1" "${2:-}"; DISPLAY_NAME="$2"; shift 2;;
    --apple-id)     require_value "$1" "${2:-}"; APPLE_ID_ARG="$2"; shift 2;;
    --team-id)      require_value "$1" "${2:-}"; TEAM_ID="$2";      shift 2;;
    --sku)          require_value "$1" "${2:-}"; SKU="$2";          shift 2;;
    --language)     require_value "$1" "${2:-}"; LANGUAGE="$2";     shift 2;;
    --app-version)  require_value "$1" "${2:-}"; APP_VERSION="$2";  shift 2;;
    --dry-run)      DRY_RUN=1;                                       shift 1;;
    -h|--help)      usage; exit 0;;
    *)              log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$BUNDLE_ID" ] || [ -z "$DISPLAY_NAME" ]; then
  log_error "--bundle-id and --display-name are required"
  usage >&2
  exit 1
fi

# Bundle ID case policy: reverse-DNS prefix is lowercased (community convention
# + ASC uniqueness is case-insensitive there), but the LAST segment — the app
# name — preserves user-supplied case so PascalCase apps (e.g. `com.axi.MyApp`)
# survive the round-trip. Apple's spec permits A-Z throughout; we only enforce
# convention on the prefix.
if [[ "$BUNDLE_ID" == *.* ]]; then
  BID_LAST="${BUNDLE_ID##*.}"
  BID_PREFIX="${BUNDLE_ID%.*}"
  BID_PREFIX="$(printf '%s' "$BID_PREFIX" | tr '[:upper:]' '[:lower:]')"
  BUNDLE_ID="${BID_PREFIX}.${BID_LAST}"
fi

# python3 is needed for safe JSON emission and locale-stable string length
if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for safe JSON output and length validation"
  log_info  "install via: brew install python3"
  exit 1
fi

# Reverse-DNS validation. Prefix segments must be lowercase (enforced by the
# normalization above); the LAST segment may be PascalCase / mixed case for
# the app-name portion (e.g. `com.axi.MyApp`). Rejects leading digits/hyphens
# in any segment and requires at least one dot.
if ! printf '%s' "$BUNDLE_ID" | grep -Eq '^[a-z][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*\.[A-Za-z0-9][A-Za-z0-9-]*$'; then
  log_error "bundle ID '$BUNDLE_ID' is not valid reverse-DNS (e.g. com.axi.MyApp)"
  exit 1
fi

# Display name: App Store accepts 2..30 characters (CHARACTER count, not bytes).
# ${#var} in bash is locale-dependent — under LANG=C it counts bytes, which
# would mis-reject any Korean/Japanese/Chinese name (e.g. "앱이름" = 9 bytes).
# Use python3 for stable character count.
NAME_LEN="$(python3 -c 'import sys; print(len(sys.argv[1]))' "$DISPLAY_NAME")"
if [ "$NAME_LEN" -lt 2 ] || [ "$NAME_LEN" -gt 30 ]; then
  log_error "display name length $NAME_LEN chars out of range (App Store requires 2..30)"
  exit 1
fi

# Resolve config.sh from CLAUDE_PLUGIN_ROOT or this script's true location.
# Plugins are commonly symlinked from ~/.claude/plugins/cache/... so we
# must follow symlinks before walking up to the plugin root.
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

config_get_or() {
  # config_get_or <key> — empty string when config.sh or the key is absent
  [ -f "$CONFIG_SH" ] || { echo ''; return 0; }
  bash "$CONFIG_SH" get-or "$1" '' 2>/dev/null || echo ''
}

# Team ID precedence: arg → env → config.json
if [ -z "$TEAM_ID" ] && [ -n "${DEVELOPMENT_TEAM:-}" ]; then
  TEAM_ID="$DEVELOPMENT_TEAM"
fi
if [ -z "$TEAM_ID" ]; then
  TEAM_ID="$(config_get_or developmentTeam)"
fi

if [ -n "$TEAM_ID" ] && ! printf '%s' "$TEAM_ID" | grep -Eq '^[A-Z0-9]{10}$'; then
  log_error "team ID '$TEAM_ID' is not 10 uppercase alphanumeric characters"
  exit 1
fi

[ -z "$SKU" ] && SKU="$BUNDLE_ID"

# SKU constraints (ASC): ASCII letters/digits/`.-_`, no spaces, length 1..100.
# Bundle IDs always satisfy this; explicit --sku values might not.
if ! printf '%s' "$SKU" | grep -Eq '^[A-Za-z0-9._-]{1,100}$'; then
  log_error "SKU '$SKU' is invalid (allowed: A-Z a-z 0-9 . _ -, 1..100 chars, no spaces)"
  exit 1
fi

# Language: BCP-47 / ISO 639-1 short form (e.g. ko, en-US). Lightweight check.
if ! printf '%s' "$LANGUAGE" | grep -Eq '^[a-z]{2,3}(-[A-Z]{2})?$'; then
  log_error "language code '$LANGUAGE' is not a valid BCP-47 short form (e.g. ko, en-US)"
  exit 1
fi

# App version: dotted numeric (e.g. 1.0.0, 1.2)
if ! printf '%s' "$APP_VERSION" | grep -Eq '^[0-9]+(\.[0-9]+){0,2}$'; then
  log_error "app version '$APP_VERSION' is not dotted numeric (e.g. 1.0 or 1.0.0)"
  exit 1
fi

# ── Apple ID + ASC web session check ──
# App-record creation uses Apple's private iris API — ASC API keys cannot
# authenticate it (see AUTH MODEL in the header). We need an Apple ID plus a
# cached spaceship session (or FASTLANE_SESSION).
# Capture the inherited env var before the local assignment shadows it.
_APPLE_ID_FROM_ENV="${APPLE_ID:-}"
APPLE_ID="$APPLE_ID_ARG"
[ -z "$APPLE_ID" ] && APPLE_ID="${FASTLANE_USER:-}"
[ -z "$APPLE_ID" ] && APPLE_ID="$_APPLE_ID_FROM_ENV"
[ -z "$APPLE_ID" ] && APPLE_ID="$(config_get_or appleId)"
if [ -z "$APPLE_ID" ]; then
  log_error "missing Apple ID for App Store Connect login"
  log_info  "pass --apple-id, export FASTLANE_USER, or run /autobot:setup to store appleId"
  exit 2
fi

# Session check (skipped in --dry-run — fastlane is never invoked there).
# A cookie's presence doesn't guarantee validity (~30-day TTL); an expired
# session is classified at fastlane time as asc_session_expired.
if [ "$DRY_RUN" -eq 0 ] && [ -z "${FASTLANE_SESSION:-}" ] \
   && [ ! -f "$HOME/.fastlane/spaceship/$APPLE_ID/cookie" ]; then
  log_error "no App Store Connect session for $APPLE_ID"
  log_info  "run once (interactive 2FA, session lasts ~30 days):"
  log_info  "  fastlane spaceauth -u $APPLE_ID"
  log_info  "app creation uses Apple's private API — ASC API keys cannot replace this step"
  exit 2
fi

# Ensure fastlane is available (skipped in --dry-run — we never invoke it)
if [ "$DRY_RUN" -eq 0 ] && ! command -v fastlane &>/dev/null; then
  if ! command -v brew &>/dev/null; then
    log_error "fastlane is missing and Homebrew is not installed"
    log_info  "install Homebrew first: https://brew.sh"
    log_info  "or install fastlane via gem: sudo gem install fastlane -NV"
    log_info  "or register manually at https://appstoreconnect.apple.com → My Apps → +"
    log_info  "  Bundle ID: $BUNDLE_ID"
    log_info  "  App Name:  $DISPLAY_NAME"
    exit 3
  fi
  log_info "fastlane not found — installing via Homebrew"
  if ! brew install fastlane; then
    log_error "fastlane install via brew failed"
    log_info  "try: sudo gem install fastlane -NV"
    log_info  "or register manually at https://appstoreconnect.apple.com → My Apps → +"
    log_info  "  Bundle ID: $BUNDLE_ID"
    log_info  "  App Name:  $DISPLAY_NAME"
    exit 3
  fi
fi

cleanup() {
  local rc=$?
  # If a status write was in flight when we got killed, clean the orphan tmp.
  if [ -n "${AUTOBOT_REGISTER_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_REGISTER_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

# Safe JSON emission via python3 — never interpolates user strings into JSON
emit_json() {
  # emit_json [k=v ...]
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
  # write_status <result> [reason]  — atomic temp+rename
  local result="$1"
  local reason="${2:-}"
  local target="${AUTOBOT_REGISTER_STATUS_FILE:-}"
  [ -z "$target" ] && return 0

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "bundle_id=$BUNDLE_ID" \
    "display_name=$DISPLAY_NAME" \
    "team_id=$TEAM_ID" \
    "sku=$SKU" \
    "language=$LANGUAGE" \
    "app_version=$APP_VERSION" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

log_info "registering: $BUNDLE_ID ($DISPLAY_NAME)"
[ -n "$TEAM_ID" ] && log_info "team:        $TEAM_ID"
log_info "sku:         $SKU"
log_info "language:    $LANGUAGE"
log_info "version:     $APP_VERSION"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — would invoke:"
  # Use python3 shlex for safe shell quoting that survives multi-byte chars
  # (bash 3.2 %q on macOS mangles non-ASCII into broken byte escapes).
  python3 - "$BUNDLE_ID" "$DISPLAY_NAME" "$LANGUAGE" "$APP_VERSION" "$SKU" "$TEAM_ID" "$APPLE_ID" <<'PY'
import shlex, sys
bid, name, lang, ver, sku, team, apple_id = sys.argv[1:8]
parts = [
    "fastlane produce create",
    f"  --username {shlex.quote(apple_id)}",
    f"  --app_identifier {shlex.quote(bid)}",
    f"  --app_name {shlex.quote(name)}",
    f"  --language {shlex.quote(lang)}",
    f"  --app_version {shlex.quote(ver)}",
    f"  --sku {shlex.quote(sku)}",
]
if team:
    parts.append(f"  --team_id {shlex.quote(team)}")
print(" \\\n".join(parts))
PY
  log_ok "dry-run validation passed"
  write_status "dry_run"
  exit 0
fi

# Silence fastlane update banner & changelog — both pollute logs and can
# inject "already" / "is not available" tokens into PRODUCE_OUTPUT, which
# would corrupt the error-pattern classifier below.
export FASTLANE_SKIP_UPDATE_CHECK=1
export FASTLANE_HIDE_CHANGELOG=1
export FASTLANE_HIDE_PLUGINS_TABLE=1
export FASTLANE_DISABLE_COLORS=1
export FASTLANE_OPT_OUT_USAGE=1
# On error fastlane appends matching GitHub issue TITLES — arbitrary text that
# can contain "already being used" etc. and poison the classifier. Hide them.
export FASTLANE_HIDE_GITHUB_ISSUES=1
# Non-interactive: fastlane occasionally prompts for a 2FA upgrade or team
# selection. In CI / Claude Code there is no human; deny stdin entirely.
export FASTLANE_SKIP_2FA_UPGRADE=1

set +e
PRODUCE_OUTPUT="$(
  fastlane produce create \
    --username "$APPLE_ID" \
    --app_identifier "$BUNDLE_ID" \
    --app_name "$DISPLAY_NAME" \
    --language "$LANGUAGE" \
    --app_version "$APP_VERSION" \
    --sku "$SKU" \
    ${TEAM_ID:+--team_id "$TEAM_ID"} \
    </dev/null \
    2>&1
)"
PRODUCE_EXIT=$?
set -e

printf '%s\n' "$PRODUCE_OUTPUT"

# ── Result classification ──
#
# fastlane produce create messages we map specifically:
#
#   "...App ID ... already exists..."             → bundle ID already on YOUR team → idempotent success
#   "...The bundle ID has already been used..."   → same as above (ASC wording)
#   "...App Name ... already being used..."       → app-name collision (someone else) → FAIL, exit 4
#   "...Identifier ... is not available..."       → bundle ID taken by ANOTHER team    → FAIL, exit 4
#   "...Could not create application..."          → API key role insufficient         → FAIL, exit 4
#
# Bundle-ID idempotency vs. name collision must be classified separately —
# they share the word "already" but mean opposite things for our pipeline.

# Restrict pattern matching to error/diagnostic lines so unrelated banner
# text (changelogs, progress noise) cannot trip the classifier even if a
# future fastlane release re-introduces the update banner under our flags.
error_lines() {
  printf '%s' "$1" | grep -Ei '^\[!\]|error|warning|already|not available|could not|not authorized|unauthorized|insufficient' || true
}

is_bundle_already_exists() {
  error_lines "$1" | grep -Eiq \
    'app id .* already exists|already exists, please skip|bundle (id|identifier) has already been used|already registered to your account'
}

is_name_collision() {
  error_lines "$1" | grep -Eiq \
    'app name .* already being used|name you entered is already being used|name you tried to use is already taken'
}

is_bundle_id_taken() {
  error_lines "$1" | grep -Eiq \
    'identifier .* is not available|app id .* not available'
}

is_session_expired() {
  # Expired/missing spaceship session with stdin closed: fastlane tries an
  # interactive login and dies on EOF, or Apple rejects the stale cookie.
  error_lines "$1" | grep -Eiq \
    'invalid username and password|could not login|unable to log ?in|session.*(expired|invalid)|not logged in|two.?(step|factor)|login failed|unauthorized access'
}

is_permission_denied() {
  error_lines "$1" | grep -Eiq \
    'could not create application|insufficient (privileges|permissions)|not authorized'
}

if [ $PRODUCE_EXIT -eq 0 ]; then
  log_ok "app registered"
  write_status "created"
  exit 0
fi

if is_bundle_already_exists "$PRODUCE_OUTPUT"; then
  log_ok "app already registered on this team — nothing to do"
  write_status "already_exists"
  exit 0
fi

# Below this point: registration genuinely failed
log_error "app registration failed (fastlane exit $PRODUCE_EXIT)"

REASON="fastlane_exit_${PRODUCE_EXIT}"
if is_name_collision "$PRODUCE_OUTPUT"; then
  REASON="name_collision"
  log_info "the display name is already used by another developer — choose a unique name (try a brand prefix)"
elif is_bundle_id_taken "$PRODUCE_OUTPUT"; then
  REASON="bundle_id_taken"
  log_info "the bundle ID is owned by another Apple Developer team — change the last segment or your prefix"
elif is_session_expired "$PRODUCE_OUTPUT"; then
  REASON="asc_session_expired"
  log_info "the App Store Connect session for $APPLE_ID is expired or invalid"
  log_info "refresh it once (interactive 2FA, ~30 days valid): fastlane spaceauth -u $APPLE_ID"
elif is_permission_denied "$PRODUCE_OUTPUT"; then
  REASON="asc_permission_denied"
  log_info "the Apple ID's ASC role is too low — promote it to 'App Manager' or 'Admin' and retry"
fi

write_status "failed" "$REASON"
exit 4
