#!/bin/bash
# Run the regression suite. stdlib only — no pytest needed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -m unittest discover -s "$SCRIPT_DIR" -v
