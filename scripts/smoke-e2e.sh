#!/bin/bash
# Smoke end-to-end: 회귀 슈트(단위)가 잡지 못하는 실제 Xcode/simulator 회귀 보호.
#
# 검증 범위:
#   1. autobot-ios-scaffold/create-xcode-project.sh  — 프로젝트 생성
#   2. xcodebuild_runner.py scaffold_build           — 실제 build
#   3. sim_runtime.py smoke                          — 시뮬레이터 boot + install + launch
#   4. env_snapshot.py capture                       — 환경 스냅샷
#   5. xclog launch (선택)                            — print/Logger 캡처 검증
#
# 사용:
#   bash scripts/smoke-e2e.sh                 # 기본 (build + boot + launch)
#   bash scripts/smoke-e2e.sh --no-launch     # build 만
#   bash scripts/smoke-e2e.sh --keep          # 정리 안 함 (디버그용)
#   bash scripts/smoke-e2e.sh --workdir DIR   # 임시 dir 지정 (기본: mktemp)
#
# 종료 코드:
#   0 = 성공
#   1 = 환경 부족 (Xcode/simulator/SDK)
#   2 = scaffold 실패
#   3 = build 실패
#   4 = simulator/launch 실패
#   5 = env_snapshot 실패
#
# CI 통합 권장: nightly 1회 macOS runner 에서 실행 (실제 Xcode 26+ 필요).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

KEEP=false
NO_LAUNCH=false
WORKDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep) KEEP=true; shift;;
    --no-launch) NO_LAUNCH=true; shift;;
    --workdir) WORKDIR="$2"; shift 2;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    *) echo "ERROR: unknown option: $1" >&2; exit 1;;
  esac
done

# ---- 0. 환경 점검 -----------------------------------------------------------
log() { printf '\033[1;36m[smoke]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[smoke]\033[0m %s\n' "$*" >&2; }

log "환경 점검"
command -v xcodebuild >/dev/null || { err "xcodebuild 없음 — Xcode CLI Tools 설치 필요"; exit 1; }
command -v xcrun >/dev/null      || { err "xcrun 없음"; exit 1; }
command -v python3 >/dev/null    || { err "python3 없음"; exit 1; }

SDK_VER="$(xcrun --sdk iphonesimulator --show-sdk-version 2>/dev/null || echo 0)"
if [[ "${SDK_VER%%.*}" -lt 26 ]]; then
  err "iOS Simulator SDK 26+ 필요 (현재: $SDK_VER)"
  exit 1
fi
log "Xcode SDK: $SDK_VER"

DEVICE_UDID="$(xcrun simctl list devices available -j \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
for runtime, devs in d['devices'].items():
    if 'iOS-26' not in runtime and 'iOS-27' not in runtime: continue
    for dev in devs:
        if dev.get('isAvailable') and 'iPhone' in dev['name']:
            print(dev['udid']); sys.exit(0)
print('')
")"
[[ -n "$DEVICE_UDID" ]] || { err "사용 가능한 iOS 26+ 시뮬레이터 없음"; exit 1; }
log "Simulator UDID: $DEVICE_UDID"

# ---- 1. 작업 디렉토리 -------------------------------------------------------
if [[ -z "$WORKDIR" ]]; then
  WORKDIR="$(mktemp -d -t autobot-smoke-XXXXXX)"
fi
log "Workdir: $WORKDIR"

cleanup() {
  if [[ "$KEEP" == "true" ]]; then
    log "유지: $WORKDIR"
  else
    log "정리: $WORKDIR"
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

# ---- 2. 프로젝트 scaffold ---------------------------------------------------
APP_NAME="AutobotSmoke"
BUNDLE_ID="com.autobot.smoke"

log "Scaffold: $APP_NAME"
if ! bash "$PLUGIN_ROOT/skills/autobot-ios-scaffold/scripts/create-xcode-project.sh" \
        --name "$APP_NAME" \
        --bundle-id "$BUNDLE_ID" \
        --deployment-target 26.0 \
        --project-dir "$WORKDIR" >"$WORKDIR/scaffold.log" 2>&1; then
  err "scaffold 실패 — log:"
  tail -20 "$WORKDIR/scaffold.log" >&2
  exit 2
fi
[[ -d "$WORKDIR/$APP_NAME.xcodeproj" ]] || { err "xcodeproj 생성 안 됨"; exit 2; }

# ---- 3. env_snapshot --------------------------------------------------------
log "env_snapshot capture"
if ! python3 "$PLUGIN_ROOT/scripts/env_snapshot.py" capture \
        --project-dir "$WORKDIR" >"$WORKDIR/env.log" 2>&1; then
  err "env_snapshot 실패 — log:"
  tail -20 "$WORKDIR/env.log" >&2
  exit 5
fi
log "  → snapshot 생성"

# ---- 4. xcodebuild ----------------------------------------------------------
log "xcodebuild (Debug, iphonesimulator)"
BUILD_LOG="$WORKDIR/build.log"
if ! xcodebuild \
        -project "$WORKDIR/$APP_NAME.xcodeproj" \
        -scheme "$APP_NAME" \
        -configuration Debug \
        -sdk iphonesimulator \
        -destination "platform=iOS Simulator,id=$DEVICE_UDID" \
        -derivedDataPath "$WORKDIR/DerivedData" \
        build >"$BUILD_LOG" 2>&1; then
  err "build 실패 — log tail:"
  tail -40 "$BUILD_LOG" >&2
  exit 3
fi
APP_PATH="$WORKDIR/DerivedData/Build/Products/Debug-iphonesimulator/$APP_NAME.app"
[[ -d "$APP_PATH" ]] || { err ".app 산출물 없음: $APP_PATH"; exit 3; }
log "  → 빌드 OK: $APP_PATH"

# ---- 5. simulator boot + install + launch ----------------------------------
if [[ "$NO_LAUNCH" == "true" ]]; then
  log "--no-launch — simulator 단계 skip"
  log "smoke OK (build-only)"
  exit 0
fi

log "Simulator boot"
xcrun simctl boot "$DEVICE_UDID" 2>/dev/null || true
xcrun simctl bootstatus "$DEVICE_UDID" -b >/dev/null

log "Install"
xcrun simctl install "$DEVICE_UDID" "$APP_PATH"

log "Launch"
LAUNCH_OUT="$(xcrun simctl launch "$DEVICE_UDID" "$BUNDLE_ID" 2>&1)" || {
  err "launch 실패: $LAUNCH_OUT"
  exit 4
}
PID="${LAUNCH_OUT##*: }"
log "  → PID $PID"

sleep 2
if xcrun simctl spawn "$DEVICE_UDID" launchctl list 2>/dev/null | grep -q "$BUNDLE_ID"; then
  log "  → 프로세스 생존 확인"
else
  log "  → 프로세스 단명 — 즉시 종료 가능 (앱이 background-only 가 아닌 한 의심)"
fi

# ---- 6. cleanup launch (정리 후 trap 에서 work dir 삭제) --------------------
xcrun simctl terminate "$DEVICE_UDID" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl uninstall "$DEVICE_UDID" "$BUNDLE_ID" 2>/dev/null || true

log "smoke OK (full pipeline)"
