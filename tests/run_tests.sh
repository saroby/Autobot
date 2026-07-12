#!/bin/bash
# Run the regression suite. stdlib only — no pytest needed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Global learning-store isolation, defense line 2 (line 1 is conftest.py's
# import-time isolation): no test — including subprocesses — may read or
# publish the developer's real ~/.config/autobot/learnings.json.
export XDG_CONFIG_HOME="$(mktemp -d)"
export AUTOBOT_TEST_XDG_ISOLATED=1
export AUTOBOT_NO_GLOBAL_PUBLISH=1
exec python3 -m unittest discover -s "$SCRIPT_DIR" -v
