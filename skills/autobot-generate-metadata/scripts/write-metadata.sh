#!/bin/bash
# Validate JSON metadata input against ASC limits and write to fastlane/metadata/.
# Single responsibility: validate + atomic write. No fastlane invocation, no upload.
#
# Status output (optional, atomic):
#   AUTOBOT_METADATA_STATUS_FILE
#
# Exit codes:
#   0  all fields validated and written (or dry-run)
#   1  usage / JSON parse error
#   2  python3 missing
#   3  length limit violation (status.reason has details)
#   4  unknown field or locale
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

METADATA_JSON=""
OUTPUT_DIR="fastlane/metadata"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: write-metadata.sh --metadata-json <path> [--output-dir <dir>] [--dry-run]

Required:
  --metadata-json   Path to JSON input file. Schema:
                    {
                      "locales": { "ko": { "name": "...", ... } },
                      "root":    { "copyright": "...", "primary_category": "..." }
                    }

Optional:
  --output-dir      Output directory. Default: fastlane/metadata
  --dry-run         Validate only, do not write files.

Environment:
  AUTOBOT_METADATA_STATUS_FILE (optional, JSON output, atomic write)
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
    --metadata-json) require_value "$1" "${2:-}"; METADATA_JSON="$2"; shift 2;;
    --output-dir)    require_value "$1" "${2:-}"; OUTPUT_DIR="$2";    shift 2;;
    --dry-run)       DRY_RUN=1;                                        shift 1;;
    -h|--help)       usage; exit 0;;
    *) log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$METADATA_JSON" ]; then
  log_error "--metadata-json is required"
  usage >&2
  exit 1
fi
if [ ! -f "$METADATA_JSON" ]; then
  log_error "metadata JSON file not found: $METADATA_JSON"
  exit 1
fi
if ! command -v python3 &>/dev/null; then
  log_error "python3 not found — required for JSON parsing + length validation"
  exit 2
fi

# Run the entire validation + write in one python3 process. This guarantees
# that NO file is written until every field has passed validation.
#
# Disable set -e around the command sub so we can capture python3's exit code
# and surface its error JSON via log_error/status file. Without this, set -e
# would kill the shell on python's exit 3/4 before we report anything.
set +e
RESULT_JSON="$(python3 - "$METADATA_JSON" "$OUTPUT_DIR" "$DRY_RUN" <<'PY'
import json, os, re, sys, tempfile

input_path, output_dir, dry_run = sys.argv[1], sys.argv[2], sys.argv[3] == "1"

# ASC character limits (chars, not bytes)
LIMITS = {
    "name": 30,
    "subtitle": 30,
    "description": 4000,
    "keywords": 100,
    "promotional_text": 170,
    "release_notes": 4000,
}

URL_FIELDS = {"marketing_url", "privacy_url", "support_url"}
LOCALE_FIELDS = set(LIMITS.keys()) | URL_FIELDS

ROOT_FIELDS = {
    "copyright",
    "primary_category",
    "secondary_category",
    "primary_first_sub_category",
    "primary_second_sub_category",
    "secondary_first_sub_category",
    "secondary_second_sub_category",
}

LOCALE_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
URL_RE = re.compile(r"^https?://")

def fail(code, message, **extra):
    out = {"result": "failed", "reason": message, **extra}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)

try:
    with open(input_path) as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    fail(1, f"JSON parse error: {e}")

if not isinstance(data, dict):
    fail(1, "top-level JSON must be an object")

locales_in = data.get("locales", {})
root_in = data.get("root", {})

if not isinstance(locales_in, dict) or not isinstance(root_in, dict):
    fail(1, "'locales' and 'root' must be objects")

# ── Phase 1: validate everything BEFORE any write ─────────────────────────
to_write = []  # list of (path, content)
fields_seen = []

# Locale fields
for locale, fields in locales_in.items():
    if not LOCALE_RE.match(locale):
        fail(4, f"invalid locale code: {locale}")
    if not isinstance(fields, dict):
        fail(1, f"locales.{locale} must be an object")
    for field, value in fields.items():
        if field not in LOCALE_FIELDS:
            fail(4, f"unknown locale field: {field} (allowed: {sorted(LOCALE_FIELDS)})")
        if not isinstance(value, str):
            fail(1, f"locales.{locale}.{field} must be a string")
        if not value:
            fail(4, f"locales.{locale}.{field} is empty — omit it instead")
        if field in URL_FIELDS:
            if not URL_RE.match(value):
                fail(4, f"locales.{locale}.{field} must start with http(s)://")
        else:
            limit = LIMITS[field]
            n = len(value)
            if n > limit:
                fail(3, f"field={field} locale={locale} len={n} max={limit}")
        path = os.path.join(output_dir, locale, f"{field}.txt")
        to_write.append((path, value))
        fields_seen.append(f"{locale}/{field}")

# Root fields
for field, value in root_in.items():
    if field not in ROOT_FIELDS:
        fail(4, f"unknown root field: {field} (allowed: {sorted(ROOT_FIELDS)})")
    if not isinstance(value, str) or not value:
        fail(1, f"root.{field} must be a non-empty string")
    path = os.path.join(output_dir, f"{field}.txt")
    to_write.append((path, value))
    fields_seen.append(field)

if not to_write:
    fail(1, "no fields supplied — input is empty")

# ── Phase 2: write (or dry-run report) ────────────────────────────────────
if dry_run:
    result = {
        "result": "dry_run",
        "fields_written": [],
        "fields_validated": fields_seen,
        "locales": sorted(locales_in.keys()),
        "output_dir": output_dir,
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)

# Atomic per-file write: temp in same dir + rename
written = []
for path, content in to_write:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        os.replace(tmp, path)
        written.append(path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

result = {
    "result": "generated",
    "fields_written": [os.path.relpath(p, output_dir) for p in written],
    "locales": sorted(locales_in.keys()),
    "output_dir": output_dir,
}
print(json.dumps(result, ensure_ascii=False))
PY
)"
PYTHON_EXIT=$?
set -e

if [ $PYTHON_EXIT -ne 0 ]; then
  # python3 already printed JSON with reason; surface it for caller logs
  REASON="$(printf '%s' "$RESULT_JSON" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin); print(d.get("reason",""))
except Exception:
    pass' 2>/dev/null)"
  [ -n "$REASON" ] && log_error "$REASON"
fi

# Write status file (atomic temp + rename) — always, even on failure
write_status() {
  local target="${AUTOBOT_METADATA_STATUS_FILE:-}"
  [ -z "$target" ] && return 0
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  printf '%s' "$RESULT_JSON" | python3 -c '
import json, sys, os
data = json.load(sys.stdin)
data["timestamp"] = os.environ["TS"]
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
' > "$tmp" 2>/dev/null || { rm -f "$tmp"; return 0; }
  mv -f "$tmp" "$target"
}
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)" write_status

cleanup() {
  local rc=$?
  if [ -n "${AUTOBOT_METADATA_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_METADATA_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

if [ $PYTHON_EXIT -eq 0 ]; then
  COUNT=$(printf '%s' "$RESULT_JSON" | python3 -c 'import json,sys
d = json.load(sys.stdin)
print(len(d.get("fields_written") or d.get("fields_validated") or []))')
  if [ "$DRY_RUN" -eq 1 ]; then
    log_ok "dry-run validation passed — $COUNT fields would be written to $OUTPUT_DIR"
  else
    log_ok "wrote $COUNT metadata files under $OUTPUT_DIR"
  fi
fi

exit $PYTHON_EXIT
