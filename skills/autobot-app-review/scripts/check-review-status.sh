#!/bin/bash
# Fetch the current App Review verdict state from App Store Connect.
# Single responsibility: read-only status retrieval after Phase G submission.
# On-demand command — NOT a controller phase (verdicts arrive hours~days after
# submit; a synchronous phase would leave the pipeline forever incomplete).
#
# Retrieves appStoreVersions.appVersionState + reviewSubmissions.items state
# via the ASC API (API Key auth — no web session needed). The written
# rejection rationale (Resolution Center) is NOT exposed by the public API:
# guidelineNumbers stays empty unless a future source provides it, and the
# details remain an IRREDUCIBLE human step (ASC web / email).
#
# Output (atomic): .autobot/review-verdict.json
#   {"fetchedAt","appVersionState","reviewSubmissionState","guidelineNumbers":[],"notes"}
#
# Exit codes:
#   0  verdict fetched (or dry-run passed)
#   1  usage / input validation
#   2  credentials missing / required tool missing
#   3  app not found for bundle-id
#   4  ASC API error
set -euo pipefail

RELEASE_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../scripts" && pwd)/release_env.sh"
. "$RELEASE_ENV"
autobot_load_release_env "${CLAUDE_PROJECT_DIR:-.}"

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

BUNDLE_ID=""
OUTPUT_PATH=".autobot/review-verdict.json"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: check-review-status.sh --bundle-id <id> [--output <path>] [--dry-run]

Required:
  --bundle-id   Reverse-DNS App ID (must already exist on ASC).

Optional:
  --output      Verdict JSON path. Default: .autobot/review-verdict.json
  --dry-run     Generate the JWT but skip all API calls; write nothing.

Environment:
  APP_STORE_CONNECT_API_KEY_KEY_ID, APP_STORE_CONNECT_API_KEY_ISSUER_ID, APP_STORE_CONNECT_API_KEY_KEY_FILEPATH (required)
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
    --bundle-id) require_value "$1" "${2:-}"; BUNDLE_ID="$2";   shift 2;;
    --output)    require_value "$1" "${2:-}"; OUTPUT_PATH="$2"; shift 2;;
    --dry-run)   DRY_RUN=1;                                      shift 1;;
    -h|--help)   usage; exit 0;;
    *)           log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$BUNDLE_ID" ]; then
  log_error "--bundle-id is required"
  usage >&2
  exit 1
fi

# Required tools
for tool in python3 curl openssl; do
  if ! command -v "$tool" &>/dev/null; then
    log_error "$tool not found — required"
    exit 2
  fi
done

# Credentials
MISSING=()
[ -z "${APP_STORE_CONNECT_API_KEY_KEY_ID:-}" ]    && MISSING+=("APP_STORE_CONNECT_API_KEY_KEY_ID")
[ -z "${APP_STORE_CONNECT_API_KEY_ISSUER_ID:-}" ] && MISSING+=("APP_STORE_CONNECT_API_KEY_ISSUER_ID")
[ -z "${APP_STORE_CONNECT_API_KEY_KEY_FILEPATH:-}" ]  && MISSING+=("APP_STORE_CONNECT_API_KEY_KEY_FILEPATH")
if [ ${#MISSING[@]} -gt 0 ]; then
  log_error "missing ASC API credentials: ${MISSING[*]}"
  exit 2
fi

APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED="${APP_STORE_CONNECT_API_KEY_KEY_FILEPATH/#\~/$HOME}"
if [ ! -r "$APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED" ]; then
  log_error "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH not readable: $APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"
  exit 2
fi

# JWT generation (ES256) — same helper as autobot-invite-testers/scripts/invite.sh
make_jwt() {
  python3 - "$APP_STORE_CONNECT_API_KEY_KEY_ID" "$APP_STORE_CONNECT_API_KEY_ISSUER_ID" "$APP_STORE_CONNECT_API_KEY_KEY_FILEPATH_EXPANDED" <<'PY'
import base64, json, os, subprocess, sys, time, tempfile
key_id, issuer_id, key_path = sys.argv[1:4]

def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

header = b64url(json.dumps({"alg":"ES256","kid":key_id,"typ":"JWT"}, separators=(",",":")).encode())
now = int(time.time())
payload = b64url(json.dumps({"iss":issuer_id,"iat":now,"exp":now+1200,"aud":"appstoreconnect-v1"}, separators=(",",":")).encode())
signing_input = f"{header}.{payload}".encode()

# openssl emits DER; convert to JOSE concatenated R||S (64 bytes for P-256)
with tempfile.NamedTemporaryFile(delete=False) as f:
    f.write(signing_input)
    si = f.name
try:
    der = subprocess.check_output(
        ["openssl", "dgst", "-sha256", "-sign", key_path, si],
        stderr=subprocess.DEVNULL,
    )
finally:
    os.unlink(si)

# Parse DER ECDSA-Sig-Value SEQUENCE { INTEGER r, INTEGER s }
def parse_der(d):
    assert d[0] == 0x30
    # length
    i = 2 if d[1] < 0x80 else 2 + (d[1] & 0x7f)
    # r
    assert d[i] == 0x02
    rlen = d[i+1]; r = d[i+2:i+2+rlen]; i = i+2+rlen
    # s
    assert d[i] == 0x02
    slen = d[i+1]; s = d[i+2:i+2+slen]
    # strip leading zeros, pad to 32
    r = r.lstrip(b"\x00").rjust(32, b"\x00")
    s = s.lstrip(b"\x00").rjust(32, b"\x00")
    return r + s

sig = b64url(parse_der(der))
print(f"{header}.{payload}.{sig}")
PY
}

# Guard the command substitution: under `set -e` a bare `JWT="$(make_jwt)"`
# aborts the script with make_jwt's exit code before the documented exit 2 can
# run. `if ! ...` keeps the classification.
if ! JWT="$(make_jwt)"; then
  log_error "JWT generation failed"
  exit 2
fi
if [ -z "$JWT" ]; then
  log_error "JWT generation produced an empty token"
  exit 2
fi

API="https://api.appstoreconnect.apple.com"

log_info "bundle:  $BUNDLE_ID"
log_info "output:  $OUTPUT_PATH"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — JWT generated (${#JWT} bytes), API calls skipped"
  log_ok "dry-run validation passed"
  exit 0
fi

# Pass the bearer token via a mode-600 curl config file (-K), never on argv:
# `-H "Authorization: Bearer <jwt>"` would expose the token in `ps` / process
# listings. Created under a strict umask and removed on exit.
CURL_CONFIG="$(mktemp -t autobot-review-curl.XXXXXX)"
cleanup() {
  [ -n "${CURL_CONFIG:-}" ] && rm -f "$CURL_CONFIG" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP
( umask 077; printf 'header = "Authorization: Bearer %s"\n' "$JWT" > "$CURL_CONFIG" )
chmod 600 "$CURL_CONFIG"

# URL-encode a single query value (RFC 3986 unreserved kept as-is)
urlenc() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

# Helper: curl that returns body + status code. `-g` disables URL globbing so
# square brackets in ASC filter paths (e.g. ?filter[bundleId]=...) aren't
# interpreted as glob ranges and rejected before the request is sent.
# Bounded, connection-timed, and self-guarding: always returns 0 (prints the
# body + trailing http_code line) so the caller's HTTP-code check owns the
# exit-code decision instead of `set -e` aborting on a transient curl failure.
# Transient failures (curl network/timeout, or ASC 429/5xx) are retried up to
# twice; 401/403 fall through as a non-200 body → caller exits 4.
api_call() {
  # api_call METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  local attempt=0 max_retries=2 resp curl_rc code
  while :; do
    local args=(-sS -g --connect-timeout 15 --max-time 60
      -X "$method" "$API$path"
      -K "$CURL_CONFIG"
      -H "Content-Type: application/json"
      -w "\n%{http_code}")
    if [ -n "$body" ]; then
      args+=(-d "$body")
    fi
    set +e
    resp="$(curl "${args[@]}")"
    curl_rc=$?
    set -e
    code="$(printf '%s' "$resp" | tail -1)"
    if [ "$attempt" -lt "$max_retries" ] \
      && { [ "$curl_rc" -ne 0 ] || printf '%s' "$code" | grep -Eq '^(429|5[0-9][0-9])$'; }; then
      attempt=$((attempt + 1))
      log_warn "ASC request $method $path transient failure (curl_rc=$curl_rc, http=${code:-none}) — retry $attempt/$max_retries"
      sleep "$attempt"
      continue
    fi
    printf '%s' "$resp"
    return 0
  done
}

# Step 1: Find app ID
BUNDLE_ID_ENC="$(urlenc "$BUNDLE_ID")"
RESP="$(api_call GET "/v1/apps?filter%5BbundleId%5D=$BUNDLE_ID_ENC&fields%5Bapps%5D=name,bundleId")"
CODE="$(printf '%s' "$RESP" | tail -1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"
if [ "$CODE" != "200" ]; then
  log_error "ASC API failed to look up app (HTTP $CODE)"
  printf '%s\n' "$BODY" >&2
  exit 4
fi

APP_ID="$(printf '%s' "$BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
print(items[0]["id"] if items else "")')"
if [ -z "$APP_ID" ]; then
  log_error "no app found on ASC for bundle-id: $BUNDLE_ID"
  log_info  "run autobot-register-app first"
  exit 3
fi
log_info "app_id:  $APP_ID"

# Step 2: Latest App Store version state
RESP="$(api_call GET "/v1/apps/$APP_ID/appStoreVersions?limit=1&fields%5BappStoreVersions%5D=appVersionState,versionString")"
CODE="$(printf '%s' "$RESP" | tail -1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"
if [ "$CODE" != "200" ]; then
  log_error "ASC API failed to fetch appStoreVersions (HTTP $CODE)"
  printf '%s\n' "$BODY" >&2
  exit 4
fi
APP_VERSION_STATE="$(printf '%s' "$BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
attrs = (items[0].get("attributes") or {}) if items else {}
print(attrs.get("appVersionState") or "")')"

# Step 3: Latest review submission state
RESP="$(api_call GET "/v1/reviewSubmissions?filter%5Bapp%5D=$APP_ID&limit=1&fields%5BreviewSubmissions%5D=state")"
CODE="$(printf '%s' "$RESP" | tail -1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"
REVIEW_SUBMISSION_STATE=""
if [ "$CODE" = "200" ]; then
  REVIEW_SUBMISSION_STATE="$(printf '%s' "$BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
attrs = (items[0].get("attributes") or {}) if items else {}
print(attrs.get("state") or "")')"
else
  log_warn "reviewSubmissions lookup failed (HTTP $CODE) — recording appVersionState only"
fi

if [ -z "$APP_VERSION_STATE" ] && [ -z "$REVIEW_SUBMISSION_STATE" ]; then
  log_error "no App Store version or review submission found — nothing submitted yet?"
  exit 4
fi

NOTES="States fetched via ASC API. Rejection rationale (Resolution Center) is not exposed by the public API — check ASC web/email for details."

mkdir -p "$(dirname "$OUTPUT_PATH")"
TMP="${OUTPUT_PATH}.tmp.$$"
python3 - "$APP_VERSION_STATE" "$REVIEW_SUBMISSION_STATE" "$NOTES" > "$TMP" <<'PY'
import datetime, json, sys
print(json.dumps({
    "fetchedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "appVersionState": sys.argv[1],
    "reviewSubmissionState": sys.argv[2],
    "guidelineNumbers": [],
    "notes": sys.argv[3],
}, ensure_ascii=False, sort_keys=True, indent=2))
PY
mv -f "$TMP" "$OUTPUT_PATH"

log_info "appVersionState:       ${APP_VERSION_STATE:-unknown}"
log_info "reviewSubmissionState: ${REVIEW_SUBMISSION_STATE:-unknown}"
case "$APP_VERSION_STATE" in
  REJECTED|DEVELOPER_REJECTED|METADATA_REJECTED|INVALID_BINARY)
    log_warn "version was rejected — read the rationale in ASC web (Resolution Center), then re-run Phase B/E and resubmit (Phase G)"
    ;;
esac
log_ok "verdict written: $OUTPUT_PATH"
exit 0
