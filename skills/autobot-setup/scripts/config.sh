#!/bin/bash
# Autobot global config manager.
# Stores user-wide defaults at ~/.autobot/config.json.
#
# Subcommands:
#   path                        # Print config file path
#   exists                      # Exit 0 if config exists, 1 otherwise
#   init                        # Create config from $AUTOBOT_SETUP_* env vars (idempotent)
#   get <key>                   # Print value for key, exit 1 if missing
#   get-or <key> <fallback>     # Print value or fallback if missing/empty
#   set <key> <value>           # Set scalar value
#   set-json <key> <json>       # Set raw JSON value (for arrays/objects)
#   validate [--require k1,k2]  # Check required keys exist and are non-empty
#   show                        # Pretty-print config
#   bundle-id <AppName>         # Compose <prefix>.<lowercase AppName>
#
# Keys (schema v1):
#   bundleIdPrefix      string  e.g. "com.axi"
#   developmentTeam     string  Apple Developer Team ID (10 chars)
#   companyName         string  Display/copyright name
#   deploymentTarget    string  e.g. "26.0"
#   testerEmails        array<string>
#   gitRemotePrefix     string  e.g. "github.com/saroby"
set -euo pipefail

CONFIG_DIR="${AUTOBOT_CONFIG_DIR:-$HOME/.autobot}"
CONFIG_FILE="${AUTOBOT_CONFIG_FILE:-$CONFIG_DIR/config.json}"
SCHEMA_VERSION=1

REQUIRED_KEYS_DEFAULT="bundleIdPrefix,deploymentTarget"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

ensure_python3() {
  command -v python3 >/dev/null 2>&1 || die "python3 not found"
}

ensure_config_dir() {
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR" 2>/dev/null || true
}

read_json() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo '{}'
    return
  fi
  cat "$CONFIG_FILE"
}

py_get() {
  local key="$1"
  ensure_python3
  python3 - "$CONFIG_FILE" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        data = json.load(f)
except FileNotFoundError:
    sys.exit(1)
v = data.get(key)
if v is None or v == "" or v == []:
    sys.exit(1)
if isinstance(v, (list, dict)):
    print(json.dumps(v))
else:
    print(v)
PY
}

py_set() {
  local key="$1"
  local value="$2"
  local as_json="${3:-no}"
  ensure_python3
  ensure_config_dir
  AUTOBOT_KEY="$key" AUTOBOT_VALUE="$value" AUTOBOT_AS_JSON="$as_json" \
    python3 - "$CONFIG_FILE" "$SCHEMA_VERSION" <<'PY'
import json, os, sys
path, version = sys.argv[1], int(sys.argv[2])
key = os.environ["AUTOBOT_KEY"]
raw = os.environ["AUTOBOT_VALUE"]
as_json = os.environ["AUTOBOT_AS_JSON"] == "yes"
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
data.setdefault("version", version)
if as_json:
    data[key] = json.loads(raw)
else:
    data[key] = raw
with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
}

cmd_path() {
  echo "$CONFIG_FILE"
}

cmd_exists() {
  [[ -f "$CONFIG_FILE" ]]
}

cmd_get() {
  [[ $# -ge 1 ]] || die "usage: config.sh get <key>"
  py_get "$1"
}

cmd_get_or() {
  [[ $# -ge 2 ]] || die "usage: config.sh get-or <key> <fallback>"
  py_get "$1" 2>/dev/null || echo "$2"
}

cmd_set() {
  [[ $# -ge 2 ]] || die "usage: config.sh set <key> <value>"
  py_set "$1" "$2" no
}

cmd_set_json() {
  [[ $# -ge 2 ]] || die "usage: config.sh set-json <key> <json>"
  py_set "$1" "$2" yes
}

cmd_show() {
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "(no config at $CONFIG_FILE)"
    return
  fi
  ensure_python3
  python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1])), indent=2, ensure_ascii=False))" "$CONFIG_FILE"
}

cmd_validate() {
  local required="$REQUIRED_KEYS_DEFAULT"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --require)
        required="$2"
        shift 2
        ;;
      *)
        die "unknown validate arg: $1"
        ;;
    esac
  done
  if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "MISSING_CONFIG: $CONFIG_FILE" >&2
    echo "  Run /autobot:setup to create it." >&2
    return 2
  fi
  ensure_python3
  AUTOBOT_REQUIRED="$required" python3 - "$CONFIG_FILE" <<'PY' || return $?
import json, os, sys
path = sys.argv[1]
required = [k.strip() for k in os.environ["AUTOBOT_REQUIRED"].split(",") if k.strip()]
with open(path) as f:
    data = json.load(f)
missing = []
for k in required:
    v = data.get(k)
    if v is None or v == "" or v == []:
        missing.append(k)
if missing:
    print("MISSING_KEYS: " + ",".join(missing), file=sys.stderr)
    print("  Run /autobot:setup to fill them.", file=sys.stderr)
    sys.exit(3)
print("OK")
PY
}

cmd_bundle_id() {
  [[ $# -ge 1 ]] || die "usage: config.sh bundle-id <AppName>"
  local app_name="$1"
  local prefix
  prefix="$(py_get bundleIdPrefix)" || die "bundleIdPrefix not set. Run /autobot:setup."
  local lower
  lower="$(LC_ALL=C echo "$app_name" | LC_ALL=C tr '[:upper:]' '[:lower:]' | LC_ALL=C tr -cd 'a-z0-9')"
  [[ -n "$lower" ]] || die "AppName produced empty bundle suffix (non-ASCII?): $app_name"
  echo "${prefix}.${lower}"
}

cmd_init() {
  # Non-interactive init from AUTOBOT_SETUP_* env vars.
  # Required: AUTOBOT_SETUP_BUNDLE_PREFIX
  # Optional: AUTOBOT_SETUP_COMPANY, AUTOBOT_SETUP_DEPLOYMENT_TARGET,
  #           AUTOBOT_SETUP_TESTER_EMAILS (comma-separated), AUTOBOT_SETUP_GIT_REMOTE
  local force="no"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) force="yes"; shift ;;
      *) die "unknown init arg: $1" ;;
    esac
  done
  if [[ -f "$CONFIG_FILE" && "$force" != "yes" ]]; then
    die "config already exists at $CONFIG_FILE. Use --force or 'set' to update."
  fi
  : "${AUTOBOT_SETUP_BUNDLE_PREFIX:?AUTOBOT_SETUP_BUNDLE_PREFIX required}"
  ensure_config_dir
  # Seed empty file so py_set can update it.
  ensure_python3
  python3 - "$CONFIG_FILE" "$SCHEMA_VERSION" <<'PY'
import json, sys
path, version = sys.argv[1], int(sys.argv[2])
with open(path, "w") as f:
    json.dump({"version": version}, f, indent=2)
    f.write("\n")
PY
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true

  py_set bundleIdPrefix "$AUTOBOT_SETUP_BUNDLE_PREFIX" no
  [[ -n "${AUTOBOT_SETUP_TEAM_ID:-}" ]] && py_set developmentTeam "$AUTOBOT_SETUP_TEAM_ID" no
  [[ -n "${AUTOBOT_SETUP_COMPANY:-}" ]] && py_set companyName "$AUTOBOT_SETUP_COMPANY" no
  py_set deploymentTarget "${AUTOBOT_SETUP_DEPLOYMENT_TARGET:-26.0}" no
  [[ -n "${AUTOBOT_SETUP_GIT_REMOTE:-}" ]] && py_set gitRemotePrefix "$AUTOBOT_SETUP_GIT_REMOTE" no
  if [[ -n "${AUTOBOT_SETUP_TESTER_EMAILS:-}" ]]; then
    ensure_python3
    emails_json="$(AUTOBOT_RAW="$AUTOBOT_SETUP_TESTER_EMAILS" python3 -c '
import json, os
items = [e.strip() for e in os.environ["AUTOBOT_RAW"].split(",") if e.strip()]
print(json.dumps(items))
')"
    py_set testerEmails "$emails_json" yes
  fi
  echo "Wrote $CONFIG_FILE"
}

main() {
  local cmd="${1:-}"
  [[ -n "$cmd" ]] || die "usage: config.sh <path|exists|init|get|get-or|set|set-json|validate|show|bundle-id>"
  shift
  case "$cmd" in
    path)       cmd_path "$@" ;;
    exists)     cmd_exists "$@" ;;
    init)       cmd_init "$@" ;;
    get)        cmd_get "$@" ;;
    get-or)     cmd_get_or "$@" ;;
    set)        cmd_set "$@" ;;
    set-json)   cmd_set_json "$@" ;;
    validate)   cmd_validate "$@" ;;
    show)       cmd_show "$@" ;;
    bundle-id)  cmd_bundle_id "$@" ;;
    *)          die "unknown command: $cmd" ;;
  esac
}

main "$@"
