#!/bin/bash
# Pre-flight check: is an app title already taken in a given country's App Store?
#
# WHY: `autobot-register-app` fails with `name_collision` when another developer
# has already published an app under the same name. This script queries the
# PUBLIC iTunes Search API per country BEFORE registration so the collision is
# caught early and the name can be changed cheaply.
#
# DATA SOURCE / CEILING (read this): the iTunes Search API only sees apps that
# are LIVE on the store. A name that is merely RESERVED-but-unpublished on App
# Store Connect will NOT appear here, and search only returns the top ~200 hits
# per term. So a "clear" result is a best-effort advisory, NOT a guarantee that
# `produce` will accept the name — the authoritative verdict is still
# register-app's `name_collision`. A "taken" result, however, is reliable.
#
# Exit codes:
#   0  no exact-name collision in any checked country
#   1  usage / input validation error, or a network fetch failed
#   2  the exact name is already taken in at least one checked country
#
# Optional env:
#   AUTOBOT_CHECKNAME_STATUS_FILE  — JSON result output path (atomic temp+rename)
#   AUTOBOT_CHECKNAME_FIXTURE_DIR  — test hook: read <dir>/<cc>.json as the raw
#                                    API response instead of hitting the network
#                                    (absent file ⇒ empty result set ⇒ available)
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

NAME=""
COUNTRIES="kr"
EXACT=0

usage() {
  cat <<'USAGE'
Usage: check-name.sh --name <app title> [--country <cc[,cc...]>] [--exact]

Required:
  --name       App title to check (1..100 characters).

Optional:
  --country    Comma-separated ISO 3166-1 alpha-2 store codes. Default: kr
               Examples: kr | us,jp | kr,us,gb,jp
  --exact      Only an exact (case/whitespace-normalized) name match counts.
               Suppresses the "similar names" advisory. Default: off — similar
               live apps are listed as advisory but do not fail the check.

Exit: 0 clear · 1 usage/network error · 2 exact name taken somewhere.

Note: uses the public iTunes Search API (live apps only, top ~200 per term).
A "taken" verdict is reliable; a "clear" verdict is best-effort — the final
word on registrability is autobot-register-app's `name_collision`.
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
    --name)    require_value "$1" "${2:-}"; NAME="$2";      shift 2;;
    --country) require_value "$1" "${2:-}"; COUNTRIES="$2"; shift 2;;
    --exact)   EXACT=1;                                     shift 1;;
    -h|--help) usage; exit 0;;
    *)         log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$NAME" ]; then
  log_error "--name is required"
  usage >&2
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for safe JSON parsing and output"
  log_info  "install via: brew install python3"
  exit 1
fi

# Name length in CHARACTERS (locale-stable via python3, not bash ${#var} which
# byte-counts under LANG=C and would mis-reject Korean/Japanese/Chinese titles).
NAME_LEN="$(python3 -c 'import sys; print(len(sys.argv[1]))' "$NAME")"
if [ "$NAME_LEN" -lt 1 ] || [ "$NAME_LEN" -gt 100 ]; then
  log_error "name length $NAME_LEN chars out of range (1..100)"
  exit 1
fi

# Normalize country list: lowercase, split on commas, dedupe, validate alpha-2.
# No `declare -A` — macOS ships bash 3.2, so dedupe via a space-padded string.
IFS=',' read -r -a _RAW_CC <<< "$COUNTRIES"
declare -a CC_LIST=()
_SEEN=" "
for cc in "${_RAW_CC[@]}"; do
  cc="$(printf '%s' "$cc" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  [ -z "$cc" ] && continue
  if ! printf '%s' "$cc" | grep -Eq '^[a-z]{2}$'; then
    log_error "country '$cc' is not an ISO 3166-1 alpha-2 code (e.g. kr, us, jp)"
    exit 1
  fi
  case "$_SEEN" in *" $cc "*) continue;; esac
  _SEEN="$_SEEN$cc "
  CC_LIST+=("$cc")
done
if [ "${#CC_LIST[@]}" -eq 0 ]; then
  log_error "no valid country codes given"
  exit 1
fi

if [ -z "${AUTOBOT_CHECKNAME_FIXTURE_DIR:-}" ] && ! command -v curl &>/dev/null; then
  log_error "curl not found — required to reach the iTunes Search API"
  exit 1
fi

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/autobot-checkname.XXXXXX")"
cleanup() {
  local rc=$?
  rm -rf "$WORKDIR" 2>/dev/null || true
  if [ -n "${AUTOBOT_CHECKNAME_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_CHECKNAME_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

log_info "checking \"$NAME\" in ${CC_LIST[*]}"

# Fetch each country's raw response into $WORKDIR/<cc>.json.
# A missing file downstream = fetch error; empty results = available.
declare -a MANIFEST=()
for cc in "${CC_LIST[@]}"; do
  out="$WORKDIR/$cc.json"
  if [ -n "${AUTOBOT_CHECKNAME_FIXTURE_DIR:-}" ]; then
    if [ -f "$AUTOBOT_CHECKNAME_FIXTURE_DIR/$cc.json" ]; then
      cp "$AUTOBOT_CHECKNAME_FIXTURE_DIR/$cc.json" "$out"
    else
      printf '{"resultCount":0,"results":[]}' > "$out"   # fixture absent ⇒ available
    fi
  else
    if curl -sS -G "https://itunes.apple.com/search" \
         --data-urlencode "term=$NAME" \
         --data "media=software" \
         --data "entity=software" \
         --data "limit=200" \
         --data "country=$cc" \
         --max-time 20 --retry 2 --retry-delay 1 \
         -o "$out" 2>/dev/null; then
      :
    else
      rm -f "$out"          # absent file signals a fetch error to the classifier
    fi
  fi
  MANIFEST+=("$cc:$out")
done

# Classify + print + write status in one python3 pass (owns all JSON so hostile
# app titles in responses can never inject fields or corrupt the status file).
set +e
python3 - "$NAME" "$EXACT" "${AUTOBOT_CHECKNAME_STATUS_FILE:-}" "${MANIFEST[@]}" <<'PY'
import json, os, re, sys, tempfile
from datetime import datetime, timezone

name = sys.argv[1]
exact_only = sys.argv[2] == "1"
status_file = sys.argv[3]
manifest = sys.argv[4:]

def norm(s):
    # casefold + collapse whitespace; punctuation preserved so "Bear: Notes"
    # and "Bear Notes" stay distinct titles.
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()

def tokens(s):
    return set(re.findall(r"\w+", norm(s), flags=re.UNICODE))

qn = norm(name)
qtok = tokens(name)

countries = {}
any_taken = False
any_error = False

for entry in manifest:
    cc, _, path = entry.partition(":")
    if not os.path.isfile(path):
        countries[cc] = {"status": "error", "reason": "fetch_failed"}
        any_error = True
        print(f"ERROR: {cc} — could not reach the App Store search API", file=sys.stderr)
        continue
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        results = data.get("results", []) or []
    except (ValueError, OSError):
        countries[cc] = {"status": "error", "reason": "bad_response"}
        any_error = True
        print(f"ERROR: {cc} — unparseable response from the search API", file=sys.stderr)
        continue

    exact_hit = None
    similar = []
    for app in results:
        tn = app.get("trackName", "")
        if norm(tn) == qn:
            if exact_hit is None:
                exact_hit = app
        elif not exact_only and qtok and (
            qn in norm(tn) or norm(tn) in qn or tokens(tn) >= qtok
        ):
            similar.append(tn)

    if exact_hit is not None:
        any_taken = True
        seller = exact_hit.get("sellerName", "unknown seller")
        tid = exact_hit.get("trackId", "?")
        countries[cc] = {
            "status": "taken",
            "match": exact_hit.get("trackName", ""),
            "track_id": tid,
            "seller": seller,
            "similar": len(similar),
        }
        print(f'FAIL: {cc} — TAKEN by "{exact_hit.get("trackName","")}" '
              f'(id {tid}, {seller})')
    else:
        countries[cc] = {"status": "available", "similar": len(similar)}
        if similar and not exact_only:
            preview = ", ".join(similar[:3])
            print(f"PASS: {cc} — available (no exact match; "
                  f"{len(similar)} similar: {preview})")
        else:
            print(f"PASS: {cc} — available (no exact match)")

overall = "taken" if any_taken else ("error" if any_error else "clear")

if status_file:
    payload = {
        "name": name,
        "exact": exact_only,
        "overall": overall,
        "countries": countries,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    os.makedirs(os.path.dirname(status_file) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(status_file) or ".",
                               prefix=os.path.basename(status_file) + ".tmp.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
    os.replace(tmp, status_file)

# exit: 2 taken (actionable) dominates 1 fetch-error dominates 0 clear
sys.exit(2 if any_taken else (1 if any_error else 0))
PY
PY_EXIT=$?
set -e

if [ "$PY_EXIT" -eq 0 ]; then
  log_ok "no exact-name collision in ${CC_LIST[*]}"
fi
exit "$PY_EXIT"
