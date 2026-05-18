#!/bin/bash
# Create a TestFlight internal beta group and invite testers via ASC API.
# Single responsibility: groups + invitations. No registration, no upload.
#
# Required env (ASC API Key):
#   ASC_API_KEY_ID
#   ASC_API_ISSUER_ID
#   ASC_API_KEY_PATH       — path to AuthKey_*.p8
#
# Status output (optional, atomic):
#   AUTOBOT_INVITE_STATUS_FILE
#
# Exit codes:
#   0  group ready + all emails handled (invited or already members)
#   1  usage / input validation
#   2  credentials missing / required tool missing
#   3  app not found for bundle-id
#   4  group creation failed
#   5  one or more invitations failed (partial)
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

BUNDLE_ID=""
EMAILS=""
GROUP_NAME="내부"
INTERNAL=1
FIRST_NAME="Tester"
LAST_NAME="User"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: invite.sh --bundle-id <id> --emails <comma-separated>
                 [--group-name <name>] [--no-internal]
                 [--first-name <name>] [--last-name <name>] [--dry-run]

Required:
  --bundle-id     Reverse-DNS App ID (must already exist on ASC).
  --emails        Comma-separated email list.

Optional:
  --group-name    TestFlight group name. Default: "내부" (reused if exists).
  --no-internal   External group (isInternalGroup: false). Default: internal.
  --first-name    Default first name for new testers. Default: Tester
  --last-name     Default last name for new testers. Default: User
  --dry-run       Generate the JWT but skip all API calls.

Environment:
  ASC_API_KEY_ID, ASC_API_ISSUER_ID, ASC_API_KEY_PATH (required)
  AUTOBOT_INVITE_STATUS_FILE (optional, JSON output)
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
    --bundle-id)   require_value "$1" "${2:-}"; BUNDLE_ID="$2";   shift 2;;
    --emails)      require_value "$1" "${2:-}"; EMAILS="$2";      shift 2;;
    --group-name)  require_value "$1" "${2:-}"; GROUP_NAME="$2";  shift 2;;
    --first-name)  require_value "$1" "${2:-}"; FIRST_NAME="$2";  shift 2;;
    --last-name)   require_value "$1" "${2:-}"; LAST_NAME="$2";   shift 2;;
    --no-internal) INTERNAL=0;                                     shift 1;;
    --dry-run)     DRY_RUN=1;                                      shift 1;;
    -h|--help)     usage; exit 0;;
    *)             log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$BUNDLE_ID" ] || [ -z "$EMAILS" ]; then
  log_error "--bundle-id and --emails are required"
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

# Parse emails — strict validation, no empty / no duplicates
EMAILS_JSON="$(python3 - "$EMAILS" <<'PY'
import json, re, sys
raw = sys.argv[1]
items = [e.strip() for e in raw.split(",") if e.strip()]
emailre = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
seen = []
for e in items:
    if not emailre.match(e):
        print(json.dumps({"error": f"invalid email: {e}"}))
        sys.exit(0)
    if e.lower() not in [s.lower() for s in seen]:
        seen.append(e)
print(json.dumps({"emails": seen}))
PY
)"

ERR="$(printf '%s' "$EMAILS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("error",""))')"
if [ -n "$ERR" ]; then
  log_error "$ERR"
  exit 1
fi

# JWT generation (ES256)
make_jwt() {
  python3 - "$ASC_API_KEY_ID" "$ASC_API_ISSUER_ID" "$ASC_API_KEY_PATH_EXPANDED" <<'PY'
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

JWT="$(make_jwt)"
if [ -z "$JWT" ]; then
  log_error "JWT generation failed"
  exit 2
fi

API="https://api.appstoreconnect.apple.com"

emit_json() {
  python3 -c '
import json, sys
data = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    if v in ("true", "false"):
        data[k] = (v == "true")
    elif v.startswith("["):
        try:
            data[k] = json.loads(v)
        except Exception:
            data[k] = v
    else:
        data[k] = v
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
' "$@"
}

# Status accumulator
APP_ID=""
GROUP_ID=""
GROUP_RESULT=""
INVITED='[]'
SKIPPED='[]'
FAILED='[]'

write_status() {
  local result="$1"
  local reason="${2:-}"
  local target="${AUTOBOT_INVITE_STATUS_FILE:-}"
  [ -z "$target" ] && return 0

  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "bundle_id=$BUNDLE_ID" \
    "app_id=$APP_ID" \
    "group_name=$GROUP_NAME" \
    "group_id=$GROUP_ID" \
    "group_result=$GROUP_RESULT" \
    "emails_invited=$INVITED" \
    "emails_skipped=$SKIPPED" \
    "emails_failed=$FAILED" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

cleanup() {
  local rc=$?
  if [ -n "${AUTOBOT_INVITE_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_INVITE_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

log_info "bundle:     $BUNDLE_ID"
log_info "group:      $GROUP_NAME"
log_info "internal:   $([ "$INTERNAL" -eq 1 ] && echo true || echo false)"
log_info "emails:     $(printf '%s' "$EMAILS_JSON" | python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin)["emails"]))')"

if [ "$DRY_RUN" -eq 1 ]; then
  log_info "DRY RUN — JWT generated (${#JWT} bytes), API calls skipped"
  log_ok "dry-run validation passed"
  write_status "dry_run"
  exit 0
fi

# URL-encode a single query value (RFC 3986 unreserved kept as-is)
urlenc() {
  python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$1"
}

# Helper: curl that returns body + status code. `-g` disables URL globbing so
# square brackets in ASC filter paths (e.g. ?filter[bundleId]=...) aren't
# interpreted as glob ranges and rejected before the request is sent.
api_call() {
  # api_call METHOD PATH [JSON_BODY]
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS -g -X "$method" "$API$path"
    -H "Authorization: Bearer $JWT"
    -H "Content-Type: application/json"
    -w "\n%{http_code}")
  if [ -n "$body" ]; then
    args+=(-d "$body")
  fi
  curl "${args[@]}"
}

# Step 1: Find app ID
BUNDLE_ID_ENC="$(urlenc "$BUNDLE_ID")"
GROUP_NAME_ENC="$(urlenc "$GROUP_NAME")"
RESP="$(api_call GET "/v1/apps?filter%5BbundleId%5D=$BUNDLE_ID_ENC&fields%5Bapps%5D=name,bundleId")"
CODE="$(printf '%s' "$RESP" | tail -1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"
if [ "$CODE" != "200" ]; then
  log_error "ASC API failed to look up app (HTTP $CODE)"
  printf '%s\n' "$BODY" >&2
  write_status "failed" "app_lookup_http_${CODE}"
  exit 3
fi

APP_ID="$(printf '%s' "$BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
print(items[0]["id"] if items else "")')"
if [ -z "$APP_ID" ]; then
  log_error "no app found on ASC for bundle-id: $BUNDLE_ID"
  log_info  "run autobot-register-app first"
  write_status "failed" "app_not_found"
  exit 3
fi
log_info "app_id:     $APP_ID"

# Step 2: Find or create group
RESP="$(api_call GET "/v1/apps/$APP_ID/betaGroups?filter%5Bname%5D=$GROUP_NAME_ENC")"
CODE="$(printf '%s' "$RESP" | tail -1)"
BODY="$(printf '%s' "$RESP" | sed '$d')"

if [ "$CODE" = "200" ]; then
  GROUP_ID="$(printf '%s' "$BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
print(items[0]["id"] if items else "")')"
fi

if [ -n "$GROUP_ID" ]; then
  GROUP_RESULT="reused"
  log_ok "reusing existing group: $GROUP_NAME ($GROUP_ID)"
else
  INTERNAL_BOOL="$([ "$INTERNAL" -eq 1 ] && echo true || echo false)"
  GROUP_BODY="$(python3 - "$GROUP_NAME" "$INTERNAL_BOOL" "$APP_ID" <<'PY'
import json, sys
name, internal, app_id = sys.argv[1:4]
body = {
    "data": {
        "type": "betaGroups",
        "attributes": {
            "name": name,
            "isInternalGroup": internal == "true",
            "hasAccessToAllBuilds": internal == "true",
        },
        "relationships": {
            "app": {"data": {"type": "apps", "id": app_id}}
        },
    }
}
print(json.dumps(body))
PY
)"
  RESP="$(api_call POST "/v1/betaGroups" "$GROUP_BODY")"
  CODE="$(printf '%s' "$RESP" | tail -1)"
  BODY="$(printf '%s' "$RESP" | sed '$d')"
  if [ "$CODE" != "201" ]; then
    log_error "group creation failed (HTTP $CODE)"
    printf '%s\n' "$BODY" >&2
    GROUP_RESULT="failed"
    write_status "failed" "group_http_${CODE}"
    exit 4
  fi
  GROUP_ID="$(printf '%s' "$BODY" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["id"])')"
  GROUP_RESULT="created"
  log_ok "group created: $GROUP_NAME ($GROUP_ID)"
fi

# Step 3: Invite emails
EMAIL_LIST="$(printf '%s' "$EMAILS_JSON" | python3 -c 'import json,sys
for e in json.load(sys.stdin)["emails"]: print(e)')"

invited=()
skipped=()
failed=()

while IFS= read -r email; do
  [ -z "$email" ] && continue
  INVITE_BODY="$(python3 - "$email" "$FIRST_NAME" "$LAST_NAME" "$GROUP_ID" <<'PY'
import json, sys
email, fn, ln, gid = sys.argv[1:5]
body = {
    "data": {
        "type": "betaTesters",
        "attributes": {"email": email, "firstName": fn, "lastName": ln},
        "relationships": {
            "betaGroups": {"data": [{"type": "betaGroups", "id": gid}]}
        },
    }
}
print(json.dumps(body))
PY
)"
  RESP="$(api_call POST "/v1/betaTesters" "$INVITE_BODY")"
  CODE="$(printf '%s' "$RESP" | tail -1)"
  BODY="$(printf '%s' "$RESP" | sed '$d')"
  case "$CODE" in
    201)
      invited+=("$email")
      log_ok "invited: $email"
      ;;
    409)
      # ASC 409 means the tester exists globally — NOT that they're a member
      # of THIS group. We must explicitly add them to the group via the
      # relationships endpoint, otherwise they'll never see this build.
      EMAIL_ENC="$(urlenc "$email")"
      TID_RESP="$(api_call GET "/v1/betaTesters?filter%5Bemail%5D=$EMAIL_ENC&fields%5BbetaTesters%5D=email")"
      TID_CODE="$(printf '%s' "$TID_RESP" | tail -1)"
      TID_BODY="$(printf '%s' "$TID_RESP" | sed '$d')"
      TESTER_ID=""
      if [ "$TID_CODE" = "200" ]; then
        TESTER_ID="$(printf '%s' "$TID_BODY" | python3 -c 'import json,sys
d = json.load(sys.stdin)
items = d.get("data", [])
print(items[0]["id"] if items else "")')"
      fi
      if [ -z "$TESTER_ID" ]; then
        failed+=("$email")
        log_warn "tester exists but lookup failed for $email (HTTP $TID_CODE)"
        printf '%s\n' "$TID_BODY" >&2
        continue
      fi
      REL_BODY="$(python3 - "$TESTER_ID" <<'PY'
import json, sys
print(json.dumps({"data": [{"type": "betaTesters", "id": sys.argv[1]}]}))
PY
)"
      REL_RESP="$(api_call POST "/v1/betaGroups/$GROUP_ID/relationships/betaTesters" "$REL_BODY")"
      REL_CODE="$(printf '%s' "$REL_RESP" | tail -1)"
      REL_BODY_RESP="$(printf '%s' "$REL_RESP" | sed '$d')"
      case "$REL_CODE" in
        204|201)
          invited+=("$email")
          log_ok "added existing tester to group: $email"
          ;;
        409)
          skipped+=("$email")
          log_info "already in group: $email"
          ;;
        *)
          failed+=("$email")
          log_warn "group-add failed for $email (HTTP $REL_CODE)"
          printf '%s\n' "$REL_BODY_RESP" >&2
          ;;
      esac
      ;;
    *)
      failed+=("$email")
      log_warn "invite failed for $email (HTTP $CODE)"
      printf '%s\n' "$BODY" >&2
      ;;
  esac
done <<< "$EMAIL_LIST"

# Re-serialize email arrays as JSON
INVITED="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${invited[@]:-}")"
SKIPPED="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${skipped[@]:-}")"
FAILED="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${failed[@]:-}")"

if [ ${#failed[@]} -gt 0 ]; then
  write_status "partial" "${#failed[@]}_email(s)_failed"
  exit 5
fi

write_status "invited"
log_ok "all emails handled (${#invited[@]} new, ${#skipped[@]} already members)"
exit 0
