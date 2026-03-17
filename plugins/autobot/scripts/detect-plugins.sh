#!/bin/bash
# Detect available plugins and tools for Autobot to leverage
# SessionStart hook — outputs systemMessage JSON with environment info
set -euo pipefail

# ── Detect CLI tools ──
XCODEGEN_AVAILABLE="false"
if command -v xcodegen &>/dev/null; then
  XCODEGEN_AVAILABLE="true"
fi

FASTLANE_AVAILABLE="false"
if command -v fastlane &>/dev/null; then
  FASTLANE_AVAILABLE="true"
fi

# ── Check for ASC credentials ──
ASC_CONFIGURED="false"
if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ]; then
  ASC_CONFIGURED="true"
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APP_SPECIFIC_PASSWORD:-}" ]; then
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
import json
try:
    d = json.load(open('$settings'))
    enabled = d.get('enabledPlugins', {})
    print('true' if any('$pattern' in str(k) and v for k, v in enabled.items()) else 'false')
except:
    print('false')
" 2>/dev/null | grep -q "true"; then
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

cat << EOF
{
  "systemMessage": "[Autobot Environment] axiom=${AXIOM_AVAILABLE}, serena=${SERENA_AVAILABLE}, context7=${CONTEXT7_AVAILABLE}, xcodegen=${XCODEGEN_AVAILABLE}, fastlane=${FASTLANE_AVAILABLE}, asc_configured=${ASC_CONFIGURED}. Note: plugin detection is best-effort; 'unknown' means runtime check needed."
}
EOF
