#!/usr/bin/env bash
# clone_run.sh — the two mechanical halves of /autobot:clone, one command each.
#
#   clone_run.sh observe "<app name or bundle id>"
#       workspace → device gate → bundle resolve → doctor → session →
#       explore the WHOLE app → measure → flow map → router manifest.
#   clone_run.sh functional
#       build once, then walk the observed flow inside the running clone:
#       every reachable transition tapped, every mapped screen reached.
#   clone_run.sh polish
#       every screen that has a view: render → structural diff → side-by-side.
#   clone_run.sh verify
#       functional, then polish. Pixel work on a screen the app cannot reach is
#       work spent before knowing whether it counts, so the order is the gate.
#
# Between the two sits the only work a script cannot own: the model writes the
# screen specs and the SwiftUI views. Neither half asks a question — both are
# meant to run unattended, and both are resumable, because a real device run
# ends early (session expiry, lock screen, login wall) far more often than it
# runs to completion.
set -euo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLONE_ROOT="${CLONE_ROOT:-.autobot/clone}"
FLOW="${CLONE_FLOW_LOG:-$CLONE_ROOT/flow.jsonl}"

usage() {
  echo "Usage: clone_run.sh observe <app name or bundle id>" >&2
  echo "       clone_run.sh codegen | functional | polish [screen] | verify | install [RootView]" >&2
  echo "       codegen redoes views.json + router + views from flow.jsonl — no device" >&2
  echo "       polish takes a measurement stem or a view name to do just that screen" >&2
}

_flow_lines() {
  [[ -f "$FLOW" ]] && wc -l <"$FLOW" | tr -d ' ' || echo 0
}

_resolve_bundle_id() {
  local udid="$1" target="$2" apps
  if ! apps="$(xcrun devicectl device info apps --device "$udid" \
        --include-all-apps --search "$target" --json-output - 2>/dev/null)"; then
    echo "ERROR: could not list apps on $udid — is the device still connected and unlocked?" >&2
    return 1
  fi
  local script
  script="$(cat <<'PY'
import json, sys
target = sys.argv[1]
payload = json.load(sys.stdin)
apps = payload.get("result", {}).get("apps", [])
def field(app, *keys):
    for key in keys:
        value = app.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
how = "exact-bundle"
exact = [a for a in apps if field(a, "bundleIdentifier") == target]
if not exact:
    how = "exact-name"
    lowered = target.casefold()
    exact = [a for a in apps
             if field(a, "name", "appName", "bundleName", "displayName").casefold() == lowered]
if not exact:
    # `devicectl --search` is inert on this toolchain — measured 2026-08-22, a
    # nonsense term still returned all 77 installed apps — so the substring match
    # has to happen here or this tier can never be a *sole* hit.
    how = "sole-substring-hit"
    needle = target.casefold()
    exact = [a for a in apps
             if needle in field(a, "name", "appName", "bundleName", "displayName").casefold()
             or needle in field(a, "bundleIdentifier").casefold()]
identifiers = sorted({field(a, "bundleIdentifier") for a in exact if field(a, "bundleIdentifier")})
if not identifiers:
    print(f"ERROR: no installed app matches {target!r} — run "
          f"'xcrun devicectl device info apps --include-all-apps --search <name>' and pass the "
          "exact Bundle Identifier", file=sys.stderr)
    raise SystemExit(1)
if len(identifiers) > 1:
    print(f"ERROR: {target!r} matches {len(identifiers)} installed apps "
          f"({', '.join(identifiers)}) — pass the exact bundle ID", file=sys.stderr)
    raise SystemExit(1)
# The skill forbids guessing the target from a name or a remembered bundle ID,
# so the log of this run has to show what was resolved and on what evidence.
# (No apostrophes in this heredoc: bash 3.2 still scans it for quotes while
# looking for the closing paren of the command substitution around it.)
label = field(exact[0], "name", "appName", "bundleName", "displayName") or "?"
print(f"INFO: resolved {target} to {identifiers[0]} by {how} (name: {label})",
      file=sys.stderr)
# Resolution only reports a candidate. The caller checks it against the clone
# already on disk, proves doctor + session can bind to it, and only then records
# it. A lookup failure must never retarget an existing clone as a side effect.
print(json.dumps({"bundleId": identifiers[0],
                  "name": label if label != "?" else "",
                  "resolvedBy": how, "query": target}, ensure_ascii=False))
PY
)"
  python3 -c "$script" "$target" <<<"$apps"
}

_check_existing_target() {
  local bundle_id="$1"
  python3 - "$CLONE_ROOT/target.json" "$bundle_id" <<'PY'
import json, sys
from pathlib import Path

path, candidate = Path(sys.argv[1]), sys.argv[2]
if not path.is_file():
    raise SystemExit(0)
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"ERROR: cannot verify existing clone target in {path}: {exc}", file=sys.stderr)
    raise SystemExit(1)
current = payload.get("bundleId") if isinstance(payload, dict) else None
if not isinstance(current, str) or not current.strip():
    print(f"ERROR: {path} has no valid bundleId, so the existing clone target cannot be verified; "
          "repair it or use a separate CLONE_ROOT", file=sys.stderr)
    raise SystemExit(1)
if current.strip() != candidate:
    print(f"ERROR: {path} binds this clone to {current.strip()}, not {candidate}; "
          "use a separate CLONE_ROOT for a different app", file=sys.stderr)
    raise SystemExit(1)
PY
}

_record_target() {
  local metadata="$1"
  python3 - "$CLONE_ROOT/target.json" "$metadata" <<'PY'
import json, os, sys, tempfile
from pathlib import Path

path, metadata = Path(sys.argv[1]), json.loads(sys.argv[2])
bundle_id = metadata.get("bundleId") if isinstance(metadata, dict) else None
if not isinstance(bundle_id, str) or not bundle_id.strip():
    print("ERROR: resolved target metadata has no bundleId", file=sys.stderr)
    raise SystemExit(1)
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

# Ask for the administrator password at the START, if it is going to be needed.
#
# An iOS 18+ device needs a RemoteXPC tunnel, and creating its TUN interface
# needs root. device_wda.sh asks with `sudo -n` so no script blocks on a hidden
# prompt — which means the credential must already be cached. Discovering that
# minutes in, at `doctor`, wastes the whole preamble; and when the run is being
# driven by a tool with no terminal there is nowhere to type it at all.
_authorize_tunnel() {
  local udid="$1" status=0
  [[ "${CLONE_REQUIRE_SUDO:-1}" == "1" ]] || return 0
  bash "$_HERE/device_wda.sh" tunnel-status "$udid" >/dev/null 2>&1 || status=$?
  case "$status" in
    0) return 0 ;;                     # ready, or this device needs no tunnel
    2) bash "$_HERE/device_wda.sh" tunnel-status "$udid" >&2; return 1 ;;
  esac
  # A terminal can just ask. Without one the password still has to come from
  # somewhere, and macOS has a place: the administrator dialog. Asking HERE is
  # the point — the alternative is the same dialog appearing several minutes
  # later, inside `doctor`, after the run has already spent that time.
  if [[ -t 0 ]] && ! sudo -n true 2>/dev/null; then
    echo "INFO: $udid needs a RemoteXPC tunnel; creating it needs administrator rights." >&2
    echo "INFO: authenticate once now — this prompt itself runs nothing as root." >&2
    sudo -v || true
  fi
  echo "INFO: starting the RemoteXPC tunnel for $udid before anything else." >&2
  echo "INFO: if a macOS administrator dialog appears, that is this step asking for the password." >&2
  if bash "$_HERE/device_wda.sh" tunnel-start "$udid"; then
    return 0
  fi
  echo "ERROR: the RemoteXPC tunnel was not created, so this device cannot be driven." >&2
  echo "ERROR: authorize once and re-run — in Claude Code type it in the prompt as: ! sudo -v" >&2
  echo "ERROR: or create it yourself:" >&2
  echo "ERROR:   sudo appium driver run xcuitest tunnel-creation -- --udid '$udid'" >&2
  return 1
}

cmd_observe() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    usage
    return 2
  fi
  local udid bundle_id resolved_target sid status=0
  bash "$_HERE/clone_workspace.sh" prepare
  export CLONE_XCODE_PROJECT="${CLONE_XCODE_PROJECT:-$CLONE_ROOT/project/CloneWorkspace.xcodeproj}"

  udid="$(bash "$_HERE/device_wda.sh" device "${CLONE_DEVICE:-}")"
  _authorize_tunnel "$udid" || return 1
  resolved_target="$(_resolve_bundle_id "$udid" "$target")"
  bundle_id="$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["bundleId"])' \
    "$resolved_target")"
  _check_existing_target "$bundle_id" || return 1
  echo "INFO: target $bundle_id on $udid"
  bash "$_HERE/device_wda.sh" doctor "$udid" "$bundle_id"
  sid="$(bash "$_HERE/device_wda.sh" session "$udid" "$bundle_id")"
  _record_target "$resolved_target"

  # Rounds, not one call: explore stops on its own guards (routing cap, a step
  # that failed), and a fresh round re-seeds from wherever the device now is.
  # A round that grows the log by nothing is the real stop condition.
  local rounds="${CLONE_EXPLORE_ROUNDS:-8}" steps="${CLONE_EXPLORE_STEPS:-200}"
  local round=0 before after
  while [[ "$round" -lt "$rounds" ]]; do
    round=$((round + 1))
    before="$(_flow_lines)"
    echo "INFO: explore round $round/$rounds"
    if ! bash "$_HERE/device_wda.sh" explore "$sid" "$CLONE_ROOT/raw" "$steps"; then
      echo "WARN: explore round $round stopped early — keeping the evidence collected so far" >&2
      status=1
      break
    fi
    after="$(_flow_lines)"
    if python3 "$_HERE/device_flow.py" next "$FLOW" 2>/dev/null | grep -q "frontier empty"; then
      echo "INFO: global frontier drained after round $round"
      break
    fi
    # A round always re-captures its seed screen (one line). Anything less than
    # two new lines means it made no step at all — re-running would just take
    # the same screenshot again.
    if [[ $((after - before)) -le 1 ]]; then
      echo "INFO: round $round made no step — stopping (see device_flow.py next)"
      break
    fi
  done

  # bash 3.2 (the macOS default) errors on "${empty[@]}" under `set -u`, so the
  # optional flag is carried as a plain string, not an array.
  local catalog="$CLONE_ROOT/project/CloneWorkspace/Assets.xcassets"
  if [[ -d "$catalog" ]]; then
    python3 "$_HERE/clone_postprocess.py" "$CLONE_ROOT" \
      --workers "${CLONE_POSTPROCESS_WORKERS:-4}" --extract-assets \
      --assets-catalog "$catalog" || status=1
  else
    python3 "$_HERE/clone_postprocess.py" "$CLONE_ROOT" \
      --workers "${CLONE_POSTPROCESS_WORKERS:-4}" --extract-assets || status=1
  fi

  python3 "$_HERE/device_flow.py" map "$FLOW" "$CLONE_ROOT/flow-map.html" || status=1
  python3 "$_HERE/device_flow.py" stats "$FLOW" || true
  # Re-judge what this run actually tapped. A hole in the guard is invisible at
  # the time — the tap simply works — so the run has to check itself afterwards.
  # 2026-08-22: two runs liked and shared another person's posts on the user's
  # real account before a hand audit found it.
  if ! python3 "$_HERE/device_flow.py" audit "$FLOW"; then
    echo "ERROR: this run tapped state-changing targets — see above and tell the user" >&2
    status=1
  fi
  cmd_codegen || status=1
  echo "OK: observed — measurement evidence in $CLONE_ROOT/screens, map at $CLONE_ROOT/flow-map.html"
  return "$status"
}

# The generation half on its own: flow.jsonl -> views.json -> router -> views.
#
# It is its own command because it is the half that needs no phone, and it is
# the half that fails LAST. A contradiction in the log (an ambiguous transition,
# a state with no view mapping) surfaces only after the whole device run and
# leaves Sources/ empty — measured 2026-08-23: one such failure lost every
# generated view, and the only documented way back was `observe`, which would
# re-explore a live app for minutes to redo work no device is involved in. Fix
# the log, run this, keep the exploration.
cmd_codegen() {
  local status=0
  if [[ ! -s "$FLOW" ]]; then
    echo "ERROR: no $FLOW — run 'clone_run.sh observe' first" >&2
    return 1
  fi
  # Every run can add screens, so the manifest, the router and the views are
  # refreshed together EVERY time — an interrupted run included. Names already
  # in views.json are kept (hand edits and compare/ evidence are keyed by them);
  # only new states get new names.
  python3 - "$FLOW" "$CLONE_ROOT/views.json" "$_HERE/clone_flow_codegen.py" <<'PY' || status=1
import importlib.util, json, sys
from pathlib import Path
flow, views_path, codegen_path = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
spec = importlib.util.spec_from_file_location("cfc", codegen_path)
cfc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cfc)
fresh = cfc.manifest_template(cfc.load_flow(flow))
old = json.loads(views_path.read_text(encoding="utf-8")) if views_path.is_file() else {}
fresh_views = fresh.get("views", {})
old_views = old.get("views", {}) if isinstance(old.get("views", {}), dict) else {}
# The observed canonical state set is authoritative. Preserve a hand-chosen
# view type only for the exact canonical key that still exists; stale alias
# keys must not be reintroduced after load_flow has normalized the evidence.
merged = {state: old_views.get(state, suggested)
          for state, suggested in fresh_views.items()}
old_initial = old.get("initial_state")
out = {"version": old.get("version", fresh.get("version", 1)),
       "initial_state": old_initial if old_initial in merged else fresh.get("initial_state"),
       "views": dict(sorted(merged.items()))}
views_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
added = sum(state not in old_views for state in out["views"])
print(f"INFO: views.json {len(old_views)} -> {len(out['views'])} states ({added} new)")
PY
  python3 "$_HERE/clone_flow_codegen.py" generate "$FLOW" "$CLONE_ROOT/views.json" \
    "$CLONE_ROOT/Sources/ObservedFlow.swift" "$CLONE_ROOT/screens" || status=1
  # A measured first pass of every screen. Starting Step 5 from a blank
  # placeholder meant `verify` said the same thing about all of them (every
  # element missing) and the author had no idea which screens were close. This
  # never touches a file whose generated marker has been removed.
  python3 "$_HERE/clone_view_codegen.py" "$CLONE_ROOT" --flow "$FLOW" || status=1
  return "$status"
}

# Shared by both halves: the workspace exists, every mapped view is defined,
# and one simulator is settled for the whole run. VIEWS/SOURCES/SIMULATOR/PLAN
# are set on success.
_preflight() {
  VIEWS="$CLONE_ROOT/views.json"
  if [[ ! -f "$VIEWS" ]]; then
    echo "ERROR: no $VIEWS — run 'clone_run.sh observe' first" >&2
    return 1
  fi
  SOURCES="$CLONE_ROOT/Sources"
  if [[ ! -d "$SOURCES" ]]; then
    echo "ERROR: no $SOURCES — the SwiftUI reproduction has not been written yet" >&2
    return 1
  fi
  mkdir -p "$CLONE_ROOT/compare"
  local views="$VIEWS" sources="$SOURCES"
  local plan
  # "MISSING <View>" for a mapping with no Swift definition; PAIR/UNPAIRED come
  # from clone_view_codegen, which is what chose the capture each view was
  # generated from. Re-deriving that join here compared a screen against a
  # DIFFERENT capture of itself once the generator stopped always taking the
  # first one.
  plan="$(python3 - "$views" "$FLOW" "$CLONE_ROOT/screens" "$sources" <<'PY'
import json, sys
from pathlib import Path
views = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("views", {})
flow, screens, sources = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
# device_render.sh compiles every .swift under Sources together, and the
# generated router names the type of EVERY state in views.json. One unwritten
# view therefore fails the build for all of them, so name the unwritten ones
# instead of reporting 24 identical compiler failures.
swift = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                  for path in sorted(sources.rglob("*.swift")))
import re
defined = set(re.findall(r"\b(?:struct|class|enum|typealias)\s+([A-Za-z_][A-Za-z0-9_]*)", swift))
for view in sorted(set(views.values())):
    if view.split(".")[0] not in defined:
        print(f"MISSING {view}")
PY
)"
  plan="$plan
$(python3 "$_HERE/clone_view_codegen.py" "$CLONE_ROOT" --flow "$FLOW" --views "$views" --pairs)"
  local missing
  missing="$(sed -n 's/^MISSING //p' <<<"$plan")"
  if [[ -n "$missing" ]]; then
    echo "ERROR: $views maps states to views that $sources does not define:" >&2
    sed 's/^/ERROR:   /' <<<"$missing" >&2
    echo "ERROR: write them, or drop those states from $views and regenerate ObservedFlow.swift — one unwritten view fails the build for every screen" >&2
    return 1
  fi
  PLAN="$plan"
  # Settle the simulator once. It is a property of the run, not of a screen, so
  # a missing one must fail here — not 20 times over, blamed on 20 views.
  SIMULATOR="${CLONE_RENDER_SIMULATOR:-}"
  if [[ -z "$SIMULATOR" ]]; then
    if ! SIMULATOR="$(bash "$_HERE/device_render.sh" resolve-simulator)"; then
      echo "ERROR: cannot pick a simulator matching the measured device — see above" >&2
      return 1
    fi
  fi
  echo "INFO: rendering on simulator $SIMULATOR"
  # Name the roots so the single build hosts exactly the mapped screens plus the
  # router; without this device_render.sh has to guess from every `: View`
  # struct in Sources/, and a helper view with a required argument breaks the
  # launch-time dispatcher.
  CLONE_ROOT_VIEWS="$(python3 -c 'import json,sys; print(" ".join(sorted(set(json.load(open(sys.argv[1]))["views"].values()))))' "$VIEWS") ObservedFlowRootView"
  export CLONE_ROOT_VIEWS
}

# The gate the pixel work is not worth doing before: the clone builds, launches,
# and navigates the flow that was observed on the device.
cmd_functional() {
  _preflight || return 1
  if ! bash "$_HERE/device_render.sh" "$SOURCES" ObservedFlowRootView "$SIMULATOR" \
        "$CLONE_ROOT/compare/functional-boot.png"; then
    echo "ERROR: the reproduction does not build or does not launch — fix that before anything else" >&2
    return 1
  fi
  python3 "$_HERE/clone_functional.py" "$CLONE_ROOT" "$SIMULATOR"
}

# Capture crops are cut from the very image this compares against, so a score
# that includes them measures crop placement, not reproduction — measured
# 2026-08-23, they cover 18-39% of several screens and accounted for the whole
# of that round's apparent improvement.
_compare_one() {
  local stem="$1" mask_assets="" status=0
  [[ -f "$CLONE_ROOT/assets/manifest.json" ]] && mask_assets="$CLONE_ROOT/assets/manifest.json"
  if [[ -n "$mask_assets" ]]; then
    python3 "$_HERE/device_compare.py" \
      "$CLONE_ROOT/raw/$stem.png" "$CLONE_ROOT/compare/$stem-rendered.png" \
      "$CLONE_ROOT/compare/$stem-compare.png" \
      --measure "$CLONE_ROOT/screens/$stem.json" \
      --heatmap "$CLONE_ROOT/compare/$stem-heatmap.png" \
      --mask-system-chrome --mask-assets "$mask_assets" || status=1
  else
    python3 "$_HERE/device_compare.py" \
      "$CLONE_ROOT/raw/$stem.png" "$CLONE_ROOT/compare/$stem-rendered.png" \
      "$CLONE_ROOT/compare/$stem-compare.png" \
      --measure "$CLONE_ROOT/screens/$stem.json" \
      --heatmap "$CLONE_ROOT/compare/$stem-heatmap.png" \
      --mask-system-chrome || status=1
  fi
  printf '%s' "$status" > "$compare_status/$stem"
}

cmd_polish() {
  # A fix/re-measure loop that always costs all 28 screens is a loop nobody runs
  # twice. `polish <stem-or-view>` closes it on one screen.
  local only="${1:-}"
  _preflight || return 1
  local views="$VIEWS" sources="$SOURCES" simulator="$SIMULATOR" plan="$PLAN"
  local unpaired
  unpaired="$(sed -n 's/^UNPAIRED //p' <<<"$plan")"
  local pairs
  pairs="$(sed -n 's/^PAIR //p' <<<"$plan")"
  if [[ -n "$only" ]]; then
    unpaired=""
    pairs="$(awk -v want="$only" '$1 == want || $2 == want' <<<"$pairs")"
    if [[ -z "$pairs" ]]; then
      echo "ERROR: no screen matches '$only' — pass a measurement stem or a view name" >&2
      return 1
    fi
  fi
  if [[ -z "$pairs" ]]; then
    echo "ERROR: no screen has both a measurement in $CLONE_ROOT/screens and a view in $views" >&2
    return 1
  fi
  local stem view rendered failures=0 checked=0 unchecked=0
  local workers="${CLONE_COMPARE_WORKERS:-4}"
  local compare_status
  compare_status="$(mktemp -d -t clone_compare)"
  if [[ -n "$unpaired" ]]; then
    unchecked="$(grep -c . <<<"$unpaired")"
    echo "ERROR: $unchecked state(s) in $views have no measurement in $CLONE_ROOT/screens and cannot be verified:" >&2
    sed 's/^/ERROR:   /' <<<"$unpaired" >&2
    echo "ERROR: run 'clone_run.sh observe' again (or clone_postprocess.py) so every mapped state has one" >&2
    failures=$((failures + unchecked))
  fi
  while read -r stem view; do
    [[ -n "$stem" ]] || continue
    checked=$((checked + 1))
    rendered="$CLONE_ROOT/compare/$stem-rendered.png"
    echo "INFO: verify $stem ($view)"
    if ! bash "$_HERE/device_render.sh" "$sources" "$view" "$simulator" "$rendered"; then
      echo "ERROR: $view did not render — fix the compiler diagnostics above" >&2
      failures=$((failures + 1))
      continue
    fi
    if [[ -f "${rendered%.png}.tree.json" ]]; then
      if ! python3 "$_HERE/clone_structural_diff.py" \
            "$CLONE_ROOT/screens/$stem.json" "${rendered%.png}.tree.json"; then
        echo "ERROR: $stem is missing elements — that is the top-priority difference" >&2
        failures=$((failures + 1))
      fi
    elif command -v axe >/dev/null 2>&1; then
      # AXe is here and still produced no tree, so this screen was never checked
      # for the dominant failure (missing elements). Reporting it as passing is
      # exactly the hidden-coverage the skill forbids.
      echo "ERROR: no rendered accessibility tree for $stem — the structural check did not run" >&2
      failures=$((failures + 1))
    else
      echo "WARN: AXe is not installed — no screen can be checked for missing elements" >&2
    fi
    # The comparison needs no simulator, so it runs alongside the next render
    # instead of after it — it was about half the wall time of a polish run.
    while [[ "$(jobs -rp | grep -c .)" -ge "$workers" ]]; do sleep 0.2; done
    _compare_one "$stem" &
  done <<<"$pairs"
  wait
  local code
  for code in "$compare_status"/*; do
    [[ -f "$code" ]] || continue
    [[ "$(cat "$code")" == "0" ]] || failures=$((failures + 1))
  done
  rm -rf "$compare_status"
  if [[ "$failures" -gt 0 ]]; then
    echo "ERROR: $failures problem(s) failed verification across $((checked + unchecked)) mapped screen(s) — $checked checked, $unchecked unverifiable — fix missing elements and structure first, then re-run" >&2
    return 1
  fi
  echo "OK: $checked screen(s) rendered and compared — review $CLONE_ROOT/compare/"
}

# Put the reproduction on the phone. A clone that only exists in a simulator is
# not a clone of an app you can hold.
cmd_install() {
  _preflight || return 1
  local udid
  udid="$(bash "$_HERE/device_wda.sh" device "${CLONE_DEVICE:-}")" || return 1
  bash "$_HERE/device_install.sh" "$SOURCES" "${1:-ObservedFlowRootView}" "$udid"
}

cmd_verify() {
  if ! cmd_functional; then
    echo "ERROR: stopping before the pixel pass — a screen the app cannot reach is not worth polishing. Run 'clone_run.sh polish' to do it anyway." >&2
    return 1
  fi
  cmd_polish
}

case "${1:-}" in
  observe)    shift; cmd_observe "$@" ;;
  codegen)    shift; cmd_codegen "$@" ;;
  functional) shift; cmd_functional "$@" ;;
  polish)     shift; cmd_polish "$@" ;;
  verify)     shift; cmd_verify "$@" ;;
  install)    shift; cmd_install "$@" ;;
  *) usage; exit 2 ;;
esac
