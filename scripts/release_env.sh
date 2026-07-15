#!/bin/bash
# Canonical precedence: inherited env, project .env, global config.

autobot_load_release_env() {
  local project_dir="${1:-${CLAUDE_PROJECT_DIR:-.}}"
  local script_dir key value
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while IFS= read -r -d '' key && IFS= read -r -d '' value; do
    export "$key=$value"
  done < <(python3 "$script_dir/release_environment.py" --project-dir "$project_dir" --format nul)
}
