#!/bin/bash
# Pillow-based AppIcon fallback.
# Tries to generate a 1024x1024 PNG via Pillow when imagegen is unavailable.
# Installs Pillow into the user site if missing.
#
# Usage:
#   pillow-fallback.sh --name SocialFitness --out .autobot/app-icon-1024.png
#   pillow-fallback.sh --name SocialFitness --out .autobot/app-icon-1024.png --color "#3366FF"
#
# Exit codes:
#   0  PNG written
#   1  invocation/argument error
#   2  Pillow unavailable and install failed — caller should mark fallback metadata
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/pillow-fallback.py"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found — cannot run Pillow fallback" >&2
  exit 2
fi

# Try importing Pillow. Install on demand if missing.
if ! python3 -c "import PIL" >/dev/null 2>&1; then
  echo "ℹ️  Pillow not installed — installing into user site..." >&2
  if ! python3 -m pip install --user --quiet --disable-pip-version-check Pillow >&2; then
    echo "ERROR: Pillow install failed. Run manually: python3 -m pip install --user Pillow" >&2
    exit 2
  fi
  if ! python3 -c "import PIL" >/dev/null 2>&1; then
    echo "ERROR: Pillow still unavailable after install" >&2
    exit 2
  fi
fi

exec python3 "$PY" "$@"
