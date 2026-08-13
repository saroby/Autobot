#!/bin/bash
# Thin entrypoint for the runtime-backed pipeline engine.
# Usage:
#   bash pipeline.sh schema
#   bash pipeline.sh init-build --build-id build-20260401-demo --app-name Demo --display-name "Demo"
#   bash pipeline.sh start-phase --phase 1 --detail "Architecture + Contracts"
#   bash pipeline.sh advance-phase --phase 1            # run gate, mark complete on pass
#   bash pipeline.sh advance-phase --phase 2 --status fallback --detail "Stitch unavailable"
#   bash pipeline.sh fail-phase --phase 5 --error "xcodebuild failed" --increment-retry
#   bash pipeline.sh run-gate --gate "4->5"             # run gate, record evidence (no phase mutation)
#   bash pipeline.sh preflight-ship                     # fresh gate 5->6; exit 1 unless a CLEAN pass (shipping entry points)
#   bash pipeline.sh record-environment --xcodegen true --stitch false
#   bash pipeline.sh set-flag --key backend_required --value true
#
# Helper subcommands (delegate to focused scripts; same project-dir handling):
#   bash pipeline.sh env-snapshot         capture|load|ensure|is-stale
#   bash pipeline.sh write-run-summary    (write artifacts/<buildId>/run-summary.{json,md})
#   bash pipeline.sh grade-learnings      --build-id <id>   (update learning effect_score)
#   bash pipeline.sh input-hash           compute|should-skip --phase N [--force]
#   bash pipeline.sh freeze-contracts     decide|apply --phase 1 [--regenerate]
#   bash pipeline.sh context-pack         --phase N --agent <name> [--budget N] [--format text|json]
#   bash pipeline.sh build-checkpoint     save|latest|restore [--attempt N] [--exclude-signature HASH]
#   bash pipeline.sh app-review-controller init|next|complete|fail|status
#   bash pipeline.sh doctor               --profile local|ship --format text|json
#   bash pipeline.sh sandbox              check|set-active|clear-active ...
#   bash pipeline.sh build-lock           acquire --build-id <id> | renew --build-id <id> | release --build-id <id> [--expected-token <token>|--force] | status
set -euo pipefail

MODE="${1:-}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${SCRIPT_DIR}/runtime.py"

USAGE="Usage: pipeline.sh <schema|init-build|record-environment|set-flag|start-phase|advance-phase|fail-phase|run-gate|preflight-ship|env-snapshot|write-run-summary|grade-learnings|input-hash|freeze-contracts|context-pack|build-checkpoint|app-review-controller|doctor|sandbox|build-lock> [options]"

if [[ -z "$MODE" ]]; then
  echo "$USAGE" >&2
  exit 1
fi

shift

case "$MODE" in
  schema)             exec python3 "$RUNTIME" validate-schema    --project-dir "$PROJECT_DIR" "$@" ;;
  init-build)         exec python3 "$RUNTIME" init-state         --project-dir "$PROJECT_DIR" "$@" ;;
  record-environment) exec python3 "$RUNTIME" record-environment --project-dir "$PROJECT_DIR" "$@" ;;
  set-flag)           exec python3 "$RUNTIME" set-flag           --project-dir "$PROJECT_DIR" "$@" ;;
  start-phase)        exec python3 "$RUNTIME" start-phase        --project-dir "$PROJECT_DIR" "$@" ;;
  advance-phase)      exec python3 "$RUNTIME" advance-phase      --project-dir "$PROJECT_DIR" "$@" ;;
  complete-phase)
    cat >&2 <<EOF
ERROR: pipeline.sh complete-phase was removed because it bypasses gates.

  Use advance-phase for successful/fallback completion:
    bash pipeline.sh advance-phase --phase <N> [--status completed|fallback] [--metadata KEY=VALUE]

  Use fail-phase for pre-gate failures:
    bash pipeline.sh fail-phase --phase <N> --error "<error>" --increment-retry
EOF
    exit 2
    ;;
  fail-phase)         exec python3 "$RUNTIME" fail-phase         --project-dir "$PROJECT_DIR" "$@" ;;
  run-gate)           exec python3 "$RUNTIME" run-gate           --project-dir "$PROJECT_DIR" "$@" ;;
  preflight-ship)
    # Runtime shipping block (anti-laundering): archive/upload entry points
    # call this to re-prove gate 5->6 FRESH before producing a shippable
    # artifact. The verdict is judged from the fresh run's own JSON output —
    # never from previously persisted state.gates evidence — so a crashed
    # re-run cannot hide behind a stale 'passed'. Only a CLEAN pass ships:
    # 'degraded' means functional verification could not run (unverified).
    # A shippable artifact without build state has no verification identity.
    # Manual callers must initialize/verify the project rather than bypassing
    # the anti-laundering boundary.
    if [[ ! -f "$PROJECT_DIR/.autobot/build-state.json" ]]; then
      echo "ERROR: preflight-ship: no .autobot/build-state.json in $PROJECT_DIR — refusing to ship without verified build state" >&2
      exit 1
    fi
    # Anti-laundering (upstream): a DEGRADED gate passed only via graceful
    # degradation (circuit breaker). An unresolved DEGRADED gate upstream of
    # 5->6 must block shipping — ship is the hard boundary where degradation
    # cannot ride along silently. 5->6 itself is excluded here because it is
    # re-judged FRESH below.
    python3 - "$PROJECT_DIR/.autobot/build-state.json" <<'PY'
import json, sys
from pathlib import Path
try:
    state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception as exc:
    sys.stderr.write(f"ERROR: preflight-ship: unreadable build-state.json ({exc}) -- refusing to ship\n")
    raise SystemExit(1)
gates = state.get("gates") or {}
degraded = sorted(
    gid for gid, ev in gates.items()
    if gid != "5->6" and isinstance(ev, dict) and ev.get("status") == "degraded"
)
if degraded:
    sys.stderr.write(
        "ERROR: preflight-ship: unresolved DEGRADED upstream gate(s) block shipping: "
        + ", ".join(degraded) + "\n"
        "  Re-run each with quality inputs until it records a clean pass before shipping.\n"
    )
    raise SystemExit(1)
PY
    GATE_JSON="$(python3 "$RUNTIME" run-gate --project-dir "$PROJECT_DIR" --gate "5->6" --format json "$@" || true)"
    printf '%s' "$GATE_JSON" | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
try:
    result = json.loads(raw)
except ValueError:
    sys.stderr.write("ERROR: preflight-ship: gate 5->6 re-run produced no parseable result -- refusing to ship\n")
    raise SystemExit(1)
passed = bool(result.get("passed"))
degraded = bool(result.get("degraded"))
if passed and not degraded:
    print("OK: preflight-ship: gate 5->6 clean pass -- shipping permitted")
    raise SystemExit(0)
if degraded:
    sys.stderr.write("ERROR: preflight-ship: gate 5->6 DEGRADED -- functional verification could not run; refusing to ship an unverified build (re-run /autobot:resume 5 with simulator+axe+xcodebuild)\n")
else:
    sys.stderr.write("ERROR: preflight-ship: gate 5->6 FAILED -- fix Phase 5 (/autobot:resume 5) before shipping\n")
raise SystemExit(1)
'
    ;;

  # ── Helper passthroughs to focused modules ───────────────────────────────
  env-snapshot)
    SUBCMD="${1:-ensure}"; shift || true
    exec python3 "${SCRIPT_DIR}/env_snapshot.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  write-run-summary)
    exec python3 "${SCRIPT_DIR}/run_summary.py" write --project-dir "$PROJECT_DIR" "$@"
    ;;
  grade-learnings)
    exec python3 "${SCRIPT_DIR}/learning_impact.py" grade --project-dir "$PROJECT_DIR" "$@"
    ;;
  input-hash)
    SUBCMD="${1:-should-skip}"; shift || true
    exec python3 "${SCRIPT_DIR}/input_hash.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  freeze-contracts)
    SUBCMD="${1:-apply}"; shift || true
    exec python3 "${SCRIPT_DIR}/contract_freeze.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  context-pack)
    exec python3 "${SCRIPT_DIR}/context_pack.py" --project-dir "$PROJECT_DIR" "$@"
    ;;
  build-checkpoint)
    SUBCMD="${1:-latest}"; shift || true
    exec python3 "${SCRIPT_DIR}/build_checkpoint.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  app-review-controller)
    SUBCMD="${1:-status}"; shift || true
    exec python3 "${SCRIPT_DIR}/app_review_controller.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  doctor)
    exec python3 "${SCRIPT_DIR}/doctor.py" --project-dir "$PROJECT_DIR" "$@"
    ;;
  sandbox)
    SUBCMD="${1:-check}"; shift || true
    exec python3 "${SCRIPT_DIR}/sandbox_guard.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  build-lock)
    SUBCMD="${1:-status}"; shift || true
    exec python3 "${SCRIPT_DIR}/build_lock.py" "$SUBCMD" --project-dir "$PROJECT_DIR" "$@"
    ;;
  *)
    echo "$USAGE" >&2
    exit 1
    ;;
esac
