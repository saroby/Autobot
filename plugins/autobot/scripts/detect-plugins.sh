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

# Check for Axiom plugin
AXIOM_AVAILABLE="false"
if [ -f "${HOME}/.claude/plugins/installed_plugins.json" ]; then
  if python3 -c "
import json
d=json.load(open('${HOME}/.claude/plugins/installed_plugins.json'))
plugins=d.get('plugins',{})
print('true' if any('axiom' in k for k in plugins) else 'false')
" 2>/dev/null | grep -q "true"; then
    AXIOM_AVAILABLE="true"
  fi
fi

# Check for Serena plugin
SERENA_AVAILABLE="false"
if [ -f "${HOME}/.claude/plugins/installed_plugins.json" ]; then
  if python3 -c "
import json
d=json.load(open('${HOME}/.claude/plugins/installed_plugins.json'))
plugins=d.get('plugins',{})
print('true' if any('serena' in k for k in plugins) else 'false')
" 2>/dev/null | grep -q "true"; then
    SERENA_AVAILABLE="true"
  fi
fi

# Check for xcodegen
XCODEGEN_AVAILABLE="false"
if command -v xcodegen &>/dev/null; then
  XCODEGEN_AVAILABLE="true"
fi

# Check for ASC credentials
ASC_CONFIGURED="false"
if [ -n "${ASC_API_KEY_ID:-}" ] && [ -n "${ASC_API_ISSUER_ID:-}" ]; then
  ASC_CONFIGURED="true"
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APP_SPECIFIC_PASSWORD:-}" ]; then
  ASC_CONFIGURED="true"
fi

cat << EOF
{
  "systemMessage": "[Autobot Plugin Detection] axiom=${AXIOM_AVAILABLE}, serena=${SERENA_AVAILABLE}, xcodegen=${XCODEGEN_AVAILABLE}, asc_configured=${ASC_CONFIGURED}"
}
EOF
