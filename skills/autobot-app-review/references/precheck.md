## Phase 0 — Precheck

```bash
# (a) Autobot project
if [ ! -f .autobot/build-state.json ]; then
  echo "ERROR: .autobot/build-state.json not found. Run /autobot:mvp first."
  exit 1
fi

# (b) Build completed (Phase 5)
P5=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('phases',{}).get('5',{}).get('status',''))")
[ "$P5" != "completed" ] && { echo "ERROR: Phase 5 (build) not completed (status: $P5). Run /autobot:resume."; exit 1; }

# (c) Bundle ID
BUNDLE_ID=$(python3 -c "import json; print(json.load(open('.autobot/build-state.json')).get('bundleId',''))")
[ -z "$BUNDLE_ID" ] && { echo "ERROR: bundleId missing — run /autobot:setup."; exit 1; }
```

ASC credential validation is owned by the controller's Phase 0 **ship doctor**
(env → project `.env` → `~/.autobot/.env` resolution) — do not re-check env
vars here. The deploy scripts themselves load the same resolution chain via
`scripts/release_env.sh`, so credentials living only in `.env` files are fine.

Halt on any failure. Do not proceed to Phase 0b.
