#!/usr/bin/env bash
# Thin wrapper around build_preview.py.
#
# Usage:
#   bash build-preview.sh [--project-dir DIR] [--output FILE]
#
# Reads .autobot/architecture.{md,json}, .autobot/design-spec.md, .autobot/designs/*.png,
# and .autobot/app-icon-1024.png to produce a single self-contained
# .autobot/designs/preview/index.html .
#
# The critique section is left as a placeholder marker — the
# autobot-plan-preview skill injects HIG critique afterwards.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/build_preview.py" "$@"
