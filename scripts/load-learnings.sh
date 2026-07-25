#!/bin/bash
# Emit a minimal Autobot session summary.
# SessionStart hook — keep prompt footprint small and defer detailed reads to build/resume time.
set -euo pipefail

# PROJECT_DIR must be the USER's project (like every other script — see
# build-log.sh, pipeline.sh). It briefly pointed at CLAUDE_PLUGIN_ROOT, which
# made installed-plugin sessions merge/render learnings into
# ~/.claude/plugins/cache/.../.autobot/ instead of the project.
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}"

# ── Step 1: .env 파일 탐색 ──
# 우선순위: 프로젝트 → 전역 ~/.autobot/.env (config.json 옆, /autobot:setup 이 기록)
# → legacy ~/.config/autobot/.env. deploy 스크립트의 source 순서(전역→프로젝트)와
# 방향이 반대인 건 의도적: 여기선 "어디든 creds 가 있나"를 보이는 게 목적이라 가장
# 구체적인(프로젝트) 것부터 본다.
ENV_FILE=""
AUTOBOT_GLOBAL_ENV="${AUTOBOT_CONFIG_DIR:-$HOME/.autobot}/.env"
if [ -f "${PROJECT_DIR}/.env" ]; then
  ENV_FILE="${PROJECT_DIR}/.env"
elif [ -f "$AUTOBOT_GLOBAL_ENV" ]; then
  ENV_FILE="$AUTOBOT_GLOBAL_ENV"
elif [ -f "${HOME}/.config/autobot/.env" ]; then
  ENV_FILE="${HOME}/.config/autobot/.env"
fi

env_has_key() {
  local key="$1"

  if [ -n "${!key:-}" ]; then
    return 0
  fi

  if [ -n "$ENV_FILE" ] && grep -Eq "^[[:space:]]*${key}=" "$ENV_FILE"; then
    return 0
  fi

  return 1
}

HAS_ENV="false"
if [ -n "$ENV_FILE" ]; then
  HAS_ENV="true"
fi

ASC_CONFIGURED="false"
if env_has_key "APP_STORE_CONNECT_API_KEY_KEY_ID" && env_has_key "APP_STORE_CONNECT_API_KEY_ISSUER_ID" && env_has_key "APP_STORE_CONNECT_API_KEY_KEY_FILEPATH"; then
  ASC_CONFIGURED="true"
fi

# ── Step 2: 과거 학습 데이터 로드 ──
LEARNINGS_FILE="${PROJECT_DIR}/.autobot/learnings.json"
HAS_LEARNINGS="false"
ACTIVE_LEARNINGS="false"
ACTIVE_LEARNINGS_SUMMARY="unavailable"

# Refresh from the host-wide store (~/.config/autobot/learnings.json or
# $XDG_CONFIG_HOME/autobot/learnings.json) so an existing Autobot project picks
# up learnings other projects validated since its last session. Silent
# best-effort — never blocks bootstrap if the helper is missing.
#
# Gated on `.autobot/` already existing: this hook fires on EVERY SessionStart in
# EVERY directory, and merge-global creates the dir it writes into. Ungated it
# littered `.autobot/` into unrelated repos (AXI-Homepage). First-time seeding
# for a brand-new Autobot project happens in cli.py init_state instead.
IMPACT_SCRIPT="${PLUGIN_ROOT}/scripts/learning_impact.py"
if [ -f "$IMPACT_SCRIPT" ] && [ -d "${PROJECT_DIR}/.autobot" ]; then
  python3 "$IMPACT_SCRIPT" merge-global --project-dir "$PROJECT_DIR" >/dev/null 2>&1 || true
fi

if [ -f "$LEARNINGS_FILE" ]; then
  HAS_LEARNINGS="true"
fi

RENDER_SCRIPT="${PLUGIN_ROOT}/scripts/render-active-learnings.py"
if [ "$HAS_LEARNINGS" = "true" ] && [ -f "$RENDER_SCRIPT" ]; then
  ACTIVE_OUTPUT=$(python3 "$RENDER_SCRIPT" --project-dir "$PROJECT_DIR" 2>/dev/null || echo "available=invalid")
  case "$ACTIVE_OUTPUT" in
    available=true*)
      ACTIVE_LEARNINGS="true"
      ACTIVE_LEARNINGS_SUMMARY="${ACTIVE_OUTPUT#available=true }"
      ;;
    available=invalid*)
      ACTIVE_LEARNINGS="true"
      ACTIVE_LEARNINGS_SUMMARY="invalid_learnings_json"
      ;;
  esac
elif [ "$HAS_LEARNINGS" = "false" ] && [ -f "${PROJECT_DIR}/.autobot/active-learnings.md" ]; then
  rm -f "${PROJECT_DIR}/.autobot/active-learnings.md"
fi

# ── Step 3: build-state 확인 (resume 가능 여부) ──
STATE_FILE="${PROJECT_DIR}/.autobot/build-state.json"
HAS_BUILD_STATE="false"
if [ -f "$STATE_FILE" ]; then
  HAS_BUILD_STATE="true"
fi

# ── Output ──
# SessionStart JSON. Two channels with different audiences:
#   systemMessage             → shown to the USER only (not the model)
#   hookSpecificOutput.additionalContext → injected into the MODEL's context
# SessionStart fires on source=compact too, so when a build is mid-flight we
# inject a compact "resume brief" that lets the model recover its bearings AFTER
# a context compaction. PreCompact cannot inject context (stdout ignored); this
# SessionStart channel is the supported path. Fail-open: any parse error just
# drops the brief and still emits the systemMessage.
HAS_ENV="$HAS_ENV" ASC_CONFIGURED="$ASC_CONFIGURED" HAS_LEARNINGS="$HAS_LEARNINGS" \
ACTIVE_LEARNINGS="$ACTIVE_LEARNINGS" ACTIVE_LEARNINGS_SUMMARY="$ACTIVE_LEARNINGS_SUMMARY" \
HAS_BUILD_STATE="$HAS_BUILD_STATE" STATE_FILE="$STATE_FILE" PLUGIN_ROOT="$PLUGIN_ROOT" \
python3 <<'PY'
import json, os

env = os.environ

# Build systemMessage by concatenation (never .format/% — the learnings summary
# may contain literal braces). json.dumps escapes safely at the end.
sysmsg = (
    "[Autobot] has_env=" + env.get("HAS_ENV", "")
    + ", asc_configured=" + env.get("ASC_CONFIGURED", "")
    + ", has_learnings=" + env.get("HAS_LEARNINGS", "")
    + ", active_learnings=" + env.get("ACTIVE_LEARNINGS", "")
    + ", learnings_summary=" + env.get("ACTIVE_LEARNINGS_SUMMARY", "")
    + ", has_build_state=" + env.get("HAS_BUILD_STATE", "")
    + ". Phase learning files use explicit names: architecture.md, parallel_coding.md, "
    "quality.md, deploy.md. Read the mapped phase file first when present, then "
    ".autobot/active-learnings.md for shared context."
)

out = {"systemMessage": sysmsg}

TERMINAL = {"completed", "fallback", "skipped"}

def phase_sort_key(pid):
    try:
        return float(pid)
    except Exception:
        return 1e9

def phase_names():
    try:
        spec = json.load(open(os.path.join(env.get("PLUGIN_ROOT", ""), "spec", "pipeline.json")))
        return {pid: (p.get("name") or pid) for pid, p in spec.get("phases", {}).items()}
    except Exception:
        return {}

if env.get("HAS_BUILD_STATE") == "true":
    try:
        st = json.load(open(env["STATE_FILE"]))
        phases = st.get("phases", {}) or {}
        active = None  # lowest-numbered non-terminal phase = where work resumes
        for pid in sorted(phases, key=phase_sort_key):
            if (phases[pid] or {}).get("status") not in TERMINAL:
                active = pid
                break
        if active is not None:
            ph = phases[active] or {}
            name = phase_names().get(active, active)
            retry = ph.get("retryCount", ph.get("retry_count", 0))
            brief = (
                "[Autobot build IN PROGRESS] buildId=" + str(st.get("buildId", "?"))
                + ", app=" + str(st.get("displayName") or st.get("appName", "?"))
                + ", currentPhase=" + str(active) + " (" + str(name) + ")"
                + ", status=" + str(ph.get("status", "pending"))
                + ", retry=" + str(retry)
                + ". This build's ground truth is .autobot/build-state.json (SSOT) — if your "
                "working context was just compacted, RE-READ it plus the mapped phase-learning "
                "file before acting. Never edit build-state.json directly; mutate state only via "
                "scripts/pipeline.sh. If you hold a build lock, preserve the OWNED_LOCK_TOKEN from "
                "init-build. Resume the build with /autobot:resume."
            )
            out["hookSpecificOutput"] = {
                "hookEventName": "SessionStart",
                "additionalContext": brief,
            }
    except Exception:
        pass

print(json.dumps(out, ensure_ascii=False))
PY
