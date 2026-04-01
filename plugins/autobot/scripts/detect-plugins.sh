#!/bin/bash
# Detect available plugins and tools for Autobot to leverage.
# Intended for explicit, on-demand environment checks rather than SessionStart.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
STITCH_AVAILABLE="${AUTOBOT_STITCH_TOOL_AVAILABLE:-}"
if [[ -n "$STITCH_AVAILABLE" ]]; then
  STITCH_SOURCE="tool-env"
else
  STITCH_SOURCE=""
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --stitch-tool-available)
      STITCH_AVAILABLE="$2"
      STITCH_SOURCE="tool-arg"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# ── Detect CLI tools ──
XCODEGEN_AVAILABLE="false"
if command -v xcodegen &>/dev/null; then
  XCODEGEN_AVAILABLE="true"
fi

FASTLANE_AVAILABLE="false"
if command -v fastlane &>/dev/null; then
  FASTLANE_AVAILABLE="true"
fi

# ── Locate .env file for credential detection ──
ENV_FILE=""
if [ -f "${PROJECT_DIR}/.env" ]; then
  ENV_FILE="${PROJECT_DIR}/.env"
elif [ -f "${HOME}/.config/autobot/.env" ]; then
  ENV_FILE="${HOME}/.config/autobot/.env"
fi

env_has_key() {
  local key="$1"

  if [ -n "${!key:-}" ]; then
    return 0
  fi

  if [ -n "$ENV_FILE" ] && grep -Eq "^[[:space:]]*${key}=" "$ENV_FILE"; then
    return 0
  fi

  return 1
}

# ── Check for ASC credentials ──
ASC_CONFIGURED="false"
if env_has_key "ASC_API_KEY_ID" && env_has_key "ASC_API_ISSUER_ID" && env_has_key "ASC_API_KEY_PATH"; then
  ASC_CONFIGURED="true"
elif env_has_key "APPLE_ID" && env_has_key "APP_SPECIFIC_PASSWORD"; then
  ASC_CONFIGURED="true"
fi

# ── Plugin detection via settings files (best-effort) ──
# Claude Code stores plugin state in ~/.claude/ — structure may change across versions.
# We check multiple known locations and degrade gracefully if none exist.
detect_plugin() {
  local pattern="$1"

  # Strategy 1: Check ~/.claude/settings.json (enabledPlugins map)
  local settings="${HOME}/.claude/settings.json"
  if [ -f "$settings" ]; then
    if python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    enabled = d.get('enabledPlugins', {})
    print('true' if any(sys.argv[2] in str(k) and v for k, v in enabled.items()) else 'false')
except:
    print('false')
" "$settings" "$pattern" 2>/dev/null | grep -q "true"; then
      echo "true"
      return
    fi
  fi

  # Strategy 2: Check ~/.claude/plugins/ directory for matching plugin dirs
  if ls -d "${HOME}/.claude/plugins/"*"$pattern"* &>/dev/null 2>&1; then
    echo "true"
    return
  fi

  # Strategy 3: No detection possible — report unknown (let runtime check)
  echo "unknown"
}

AXIOM_AVAILABLE=$(detect_plugin "axiom")
SERENA_AVAILABLE=$(detect_plugin "serena")
CONTEXT7_AVAILABLE=$(detect_plugin "context7")

# ── Detect Google Stitch MCP ──
# Primary signal should come from the caller/tooling layer because shell scripts
# cannot directly inspect the live MCP tool registry.
if [[ -z "$STITCH_AVAILABLE" ]]; then
  STITCH_SOURCE="cli"
  if command -v stitch-mcp &>/dev/null; then
    STITCH_AVAILABLE="true"
  elif npx @_davideast/stitch-mcp doctor &>/dev/null 2>&1; then
    STITCH_AVAILABLE="true"
    STITCH_SOURCE="doctor-fallback"
  else
    STITCH_AVAILABLE="false"
  fi
fi

cat << EOF
{
  "systemMessage": "[Autobot Environment] axiom=${AXIOM_AVAILABLE}, serena=${SERENA_AVAILABLE}, context7=${CONTEXT7_AVAILABLE}, stitch=${STITCH_AVAILABLE}, stitch_source=${STITCH_SOURCE}, xcodegen=${XCODEGEN_AVAILABLE}, fastlane=${FASTLANE_AVAILABLE}, asc_configured=${ASC_CONFIGURED}. Note: plugin detection is best-effort; 'unknown' means runtime check needed."
}
EOF
