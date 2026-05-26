#!/usr/bin/env bash
# Detect installed Axiom plugin (https://github.com/CharlesWiltgen/Axiom).
#
# Exit 0 + prints absolute path to the latest installed Axiom version dir
#        (the one containing `agents/`, `skills/`, `commands/`).
# Exit 1 if no Axiom installation is found — Autobot must treat this as
# "soft skip": continue the build, log skipped=true, no failure.
#
# Used by Phase 5 (Gate-5 critical audit) and Phase 7 (health-check report).

set -euo pipefail

candidates=(
  "$HOME/.claude/plugins/cache/axiom-marketplace/axiom"
)

# Optional sibling install: ${CLAUDE_PLUGIN_ROOT}/../axiom (when both plugins
# live in the same parent dir, e.g. local dev).
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  candidates+=("${CLAUDE_PLUGIN_ROOT}/../axiom")
fi

for base in "${candidates[@]}"; do
  [ -d "$base" ] || continue

  # If the dir itself contains agents/, it's a direct install (no version subdir).
  if [ -d "$base/agents" ] && [ -d "$base/skills" ]; then
    printf '%s\n' "$base"
    exit 0
  fi

  # Otherwise pick the highest-versioned subdir that contains agents/.
  latest=$(
    find "$base" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
      | sort -V \
      | while read -r dir; do
          [ -d "$dir/agents" ] && [ -d "$dir/skills" ] && printf '%s\n' "$dir"
        done \
      | tail -1
  )

  if [ -n "$latest" ]; then
    printf '%s\n' "$latest"
    exit 0
  fi
done

exit 1
