#!/bin/bash
# Detect available plugins and tools for Autobot to leverage
set -euo pipefail

# Read user prompt from stdin
INPUT=$(cat)
USER_PROMPT=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user_prompt',''))" 2>/dev/null || echo "")

# Only activate for autobot:build commands
if [[ "$USER_PROMPT" != *"autobot"* ]] && [[ "$USER_PROMPT" != *"/build"* ]]; then
  exit 0
fi

SETTINGS_FILE="${HOME}/.claude/settings.json"
INSTALLED_FILE="${HOME}/.claude/plugins/installed_plugins.json"

# ── Helper: check if a plugin is enabled or installed ──
# Priority: enabledPlugins (active) > installed_plugins.json (installed)
check_plugin() {
  local pattern="$1"

  # 1) Check enabledPlugins in settings.json (most reliable — currently active)
  if [ -f "$SETTINGS_FILE" ]; then
    if python3 -c "
import json, sys
d = json.load(open('$SETTINGS_FILE'))
enabled = d.get('enabledPlugins', {})
print('true' if any('$pattern' in k and v for k, v in enabled.items()) else 'false')
" 2>/dev/null | grep -q "true"; then
      echo "true"
      return
    fi
  fi

  # 2) Fallback: check installed_plugins.json
  if [ -f "$INSTALLED_FILE" ]; then
    if python3 -c "
import json
d = json.load(open('$INSTALLED_FILE'))
plugins = d.get('plugins', {})
print('true' if any('$pattern' in k for k in plugins) else 'false')
" 2>/dev/null | grep -q "true"; then
      echo "true"
      return
    fi
  fi

  echo "false"
}

# ── Detect plugins ──
AXIOM_AVAILABLE=$(check_plugin "axiom")
SERENA_AVAILABLE=$(check_plugin "serena")
CONTEXT7_AVAILABLE=$(check_plugin "context7")

# Check for xcodegen
XCODEGEN_AVAILABLE="false"
if command -v xcodegen &>/dev/null; then
  XCODEGEN_AVAILABLE="true"
fi

# Check for ASC credentials
ASC_CONFIGURED="false"
if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ]; then
  ASC_CONFIGURED="true"
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APP_SPECIFIC_PASSWORD:-}" ]; then
  ASC_CONFIGURED="true"
fi

cat << EOF
{
  "systemMessage": "[Autobot Plugin Detection] axiom=${AXIOM_AVAILABLE}, serena=${SERENA_AVAILABLE}, context7=${CONTEXT7_AVAILABLE}, xcodegen=${XCODEGEN_AVAILABLE}, asc_configured=${ASC_CONFIGURED}"
}
EOF
