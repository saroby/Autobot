#!/bin/bash
# Register a new iOS product on AXI-Homepage (https://github.com/saroby/AXI-Homepage)
# by inserting a Product entry into src/data/products.ts, copying icon +
# screenshots into public/, and pushing to GitHub.
#
# Idempotent: if a product with the given slug already exists in products.ts,
# the script is a no-op (or rewrites when --force is passed).
#
# Required input:
#   --product-json <path>   JSON file describing the product (schema below).
#
# Status output (optional, atomic):
#   AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE
#
# Exit codes:
#   0  registered + pushed (or already_exists, or dry-run passed)
#   1  usage / input validation
#   2  homepage repo unreachable / clone failed / git push failed
#   3  products.ts insertion failed (parser couldn't find the array)
#   4  asset copy failed
set -euo pipefail

log_info()  { printf 'INFO: %s\n'  "$*"; }
log_ok()    { printf 'OK: %s\n'    "$*"; }
log_warn()  { printf 'WARN: %s\n'  "$*" >&2; }
log_error() { printf 'ERROR: %s\n' "$*" >&2; }

PRODUCT_JSON=""
HOMEPAGE_REPO=""
HOMEPAGE_REMOTE="git@github.com:saroby/AXI-Homepage.git"
HOMEPAGE_BRANCH="main"
HOMEPAGE_DOMAIN="https://axi-homepage.vercel.app"
HOMEPAGE_LOCALE="ko"   # locale segment for the canonical product URL: /<locale>/products/<slug>
SCREENSHOT_LIMIT=3   # how many screenshots to copy to public/screenshots/<slug>/
DRY_RUN=0
FORCE=0
NO_PUSH=0

usage() {
  cat <<'USAGE'
Usage: register-on-homepage.sh --product-json <path>
                               [--homepage-repo <dir>] [--homepage-remote <url>]
                               [--homepage-branch <name>] [--homepage-domain <url>]
                               [--screenshot-limit <N>] [--force] [--no-push] [--dry-run]

Required:
  --product-json       JSON file (schema below).

Optional:
  --homepage-repo      Local clone of AXI-Homepage. Default: $HOME/Code/AXI/AXI-Homepage.
                       If absent, the script will clone $HOMEPAGE_REMOTE there.
  --homepage-remote    Override the upstream git URL. Default: git@github.com:saroby/AXI-Homepage.git
  --homepage-branch    Branch to push to. Default: main
  --homepage-domain    Production domain used to build the canonical product URL.
                       Default: https://axi-homepage.vercel.app
  --screenshot-limit   Max screenshots to copy. Default: 3 (hero + 2 features).
  --force              Overwrite an existing product entry with the same slug.
  --no-push            Stage the commit locally but do not push.
  --dry-run            Print what would change; do not modify the repo.

Product JSON schema:
{
  "slug": "myapp",                              // kebab-case, [a-z0-9-]
  "name":        { "ko": "내 앱", "en": "My App" },
  "tagline":     { "ko": "...", "en": "..." },
  "description": { "ko": "...", "en": "..." },
  "features":    { "ko": ["...", "..."], "en": ["...", "..."] },
  "platform":    "iOS",                          // or "macOS"
  "systemRequirements": "iOS 26.0+",
  "techStack":   ["Swift 6", "SwiftUI", "iOS 26"],
  "downloadUrl": "https://apps.apple.com/app/id<appStoreId>",
  "downloadLabel": { "ko": "App Store에서 다운로드", "en": "Download on the App Store" },
  "iconPath":    "/abs/path/to/app-icon-1024.png",   // required for new entries
  "screenshots": ["/abs/path/01.png", "/abs/path/02.png", ...]
}

Output:
  Inserts into <homepage-repo>/src/data/products.ts before the closing `];`.
  Copies iconPath        → <homepage-repo>/public/icons/<slug>.png
  Copies screenshots[]   → <homepage-repo>/public/screenshots/<slug>/<NN>.png (NN = 01..screenshot-limit)
  Commits + pushes to <homepage-branch>.
USAGE
}

require_value() {
  if [ -z "${2:-}" ] || [[ "${2:-}" == --* ]]; then
    log_error "$1 requires a value"
    usage >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --product-json)      require_value "$1" "${2:-}"; PRODUCT_JSON="$2";     shift 2;;
    --homepage-repo)     require_value "$1" "${2:-}"; HOMEPAGE_REPO="$2";    shift 2;;
    --homepage-remote)   require_value "$1" "${2:-}"; HOMEPAGE_REMOTE="$2";  shift 2;;
    --homepage-branch)   require_value "$1" "${2:-}"; HOMEPAGE_BRANCH="$2";  shift 2;;
    --homepage-domain)   require_value "$1" "${2:-}"; HOMEPAGE_DOMAIN="$2";  shift 2;;
    --screenshot-limit)  require_value "$1" "${2:-}"; SCREENSHOT_LIMIT="$2"; shift 2;;
    --force)             FORCE=1;                                             shift 1;;
    --no-push)           NO_PUSH=1;                                           shift 1;;
    --dry-run)           DRY_RUN=1;                                           shift 1;;
    -h|--help)           usage; exit 0;;
    *) log_error "unknown option: $1"; usage >&2; exit 1;;
  esac
done

if [ -z "$PRODUCT_JSON" ]; then
  log_error "--product-json is required"
  usage >&2
  exit 1
fi
if [ ! -r "$PRODUCT_JSON" ]; then
  log_error "product JSON not readable: $PRODUCT_JSON"
  exit 1
fi

[ -z "$HOMEPAGE_REPO" ] && HOMEPAGE_REPO="$HOME/Code/AXI/AXI-Homepage"

if ! command -v python3 &>/dev/null; then
  log_error "python3 not found"
  exit 1
fi
if ! command -v git &>/dev/null; then
  log_error "git not found"
  exit 1
fi

# Validate JSON schema + extract slug for downstream use.
set +e
PARSED="$(python3 - "$PRODUCT_JSON" 2>&1 <<'PY'
import json, re, sys
p = json.load(open(sys.argv[1], "r", encoding="utf-8"))

required = ["slug","name","tagline","description","features","platform",
            "systemRequirements","techStack","downloadUrl","downloadLabel"]
missing = [k for k in required if k not in p]
if missing:
    print("missing required fields: " + ",".join(missing))
    sys.exit(1)

slug = p["slug"]
if not re.match(r"^[a-z][a-z0-9-]{1,40}$", slug):
    print(f"invalid slug: {slug!r} (must be kebab-case, [a-z0-9-], 2-41 chars)")
    sys.exit(1)

for k in ("name","tagline","description","downloadLabel"):
    v = p[k]
    if not (isinstance(v, dict) and "ko" in v and "en" in v):
        print(f"field '{k}' must be an object with 'ko' and 'en' keys")
        sys.exit(1)

if not (isinstance(p["features"], dict) and "ko" in p["features"] and "en" in p["features"]):
    print("field 'features' must be {ko: [...], en: [...]}")
    sys.exit(1)
for loc in ("ko","en"):
    if not isinstance(p["features"][loc], list) or not all(isinstance(x, str) for x in p["features"][loc]):
        print(f"field 'features.{loc}' must be an array of strings")
        sys.exit(1)

if not (isinstance(p["techStack"], list) and all(isinstance(x, str) for x in p["techStack"])):
    print("field 'techStack' must be an array of strings")
    sys.exit(1)

icon_path = p.get("iconPath", "")
screenshots = p.get("screenshots", [])
if not isinstance(screenshots, list) or not all(isinstance(x, str) for x in screenshots):
    print("field 'screenshots' must be an array of file paths")
    sys.exit(1)

print(slug)
PY
)"
PARSE_EXIT=$?
set -e
if [ $PARSE_EXIT -ne 0 ]; then
  log_error "$PARSED"
  exit 1
fi

SLUG="$(printf '%s\n' "$PARSED" | tail -n 1)"
log_info "slug:            $SLUG"
log_info "homepage repo:   $HOMEPAGE_REPO (branch: $HOMEPAGE_BRANCH)"
log_info "homepage domain: $HOMEPAGE_DOMAIN"
[ "$DRY_RUN" -eq 1 ] && log_info "DRY RUN — no files will change"

WORK_LOG="$(mktemp -t autobot-homepage.XXXXXX)"
cleanup() {
  local rc=$?
  rm -f "$WORK_LOG" 2>/dev/null || true
  if [ -n "${AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE:-}" ]; then
    rm -f "${AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE}.tmp.$$" 2>/dev/null || true
  fi
  return $rc
}
trap cleanup EXIT INT TERM HUP

emit_json() {
  python3 -c '
import json, sys
data = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    data[k] = v
print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
' "$@"
}

write_status() {
  local result="$1"
  local reason="${2:-}"
  local url="${3:-}"
  local commit_sha="${4:-}"
  local target="${AUTOBOT_HOMEPAGE_REGISTER_STATUS_FILE:-}"
  [ -z "$target" ] && return 0
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$target")"
  local tmp="${target}.tmp.$$"
  emit_json \
    "result=$result" \
    "slug=$SLUG" \
    "homepage_repo=$HOMEPAGE_REPO" \
    "homepage_branch=$HOMEPAGE_BRANCH" \
    "homepage_domain=$HOMEPAGE_DOMAIN" \
    "canonical_url=$url" \
    "commit_sha=$commit_sha" \
    "force=$FORCE" \
    "no_push=$NO_PUSH" \
    "reason=$reason" \
    "timestamp=$ts" \
    > "$tmp"
  mv -f "$tmp" "$target"
}

CANONICAL_URL="${HOMEPAGE_DOMAIN%/}/${HOMEPAGE_LOCALE}/products/${SLUG}"

# ----------------------------------------------------------------------------
# Clone or update the homepage repo
# ----------------------------------------------------------------------------
if [ ! -d "$HOMEPAGE_REPO/.git" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    log_info "DRY RUN — would clone $HOMEPAGE_REMOTE to $HOMEPAGE_REPO"
  else
    log_info "cloning $HOMEPAGE_REMOTE → $HOMEPAGE_REPO"
    mkdir -p "$(dirname "$HOMEPAGE_REPO")"
    if ! git clone "$HOMEPAGE_REMOTE" "$HOMEPAGE_REPO" 2>&1 | tee "$WORK_LOG"; then
      log_error "git clone failed — check SSH access to $HOMEPAGE_REMOTE"
      write_status "failed" "clone_failed" "$CANONICAL_URL"
      exit 2
    fi
  fi
else
  log_info "homepage repo present — fetching latest"
  if [ "$DRY_RUN" -eq 0 ]; then
    if ! (cd "$HOMEPAGE_REPO" && git fetch origin "$HOMEPAGE_BRANCH" --quiet 2>&1 | tee "$WORK_LOG"); then
      log_warn "git fetch failed — continuing with local state"
    fi
    # Ensure clean working tree on the target branch before mutating.
    if ! (cd "$HOMEPAGE_REPO" && git diff --quiet && git diff --cached --quiet); then
      log_error "homepage repo has uncommitted changes — refusing to mutate. Stash or commit first."
      write_status "failed" "dirty_worktree" "$CANONICAL_URL"
      exit 2
    fi
    if ! (cd "$HOMEPAGE_REPO" && git checkout "$HOMEPAGE_BRANCH" --quiet && git reset --hard "origin/$HOMEPAGE_BRANCH" --quiet 2>&1 | tee "$WORK_LOG"); then
      log_warn "could not fast-reset to origin/$HOMEPAGE_BRANCH — continuing with local state"
    fi
  fi
fi

PRODUCTS_TS="$HOMEPAGE_REPO/src/data/products.ts"
if [ ! -f "$PRODUCTS_TS" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    log_info "DRY RUN — products.ts is unavailable (repo not cloned yet). Skipping mutation preview."
    log_ok   "dry-run validation passed (would clone $HOMEPAGE_REMOTE and register $SLUG)"
    write_status "dry_run" "" "$CANONICAL_URL"
    exit 0
  fi
  log_error "expected file not found: $PRODUCTS_TS"
  log_info  "verify --homepage-repo points to a clone of AXI-Homepage"
  write_status "failed" "products_ts_missing" "$CANONICAL_URL"
  exit 3
fi

# ----------------------------------------------------------------------------
# Existence check — idempotency
# ----------------------------------------------------------------------------
ALREADY_EXISTS=0
if [ "$DRY_RUN" -eq 0 ] && grep -Eq "slug:[[:space:]]*\"$SLUG\"" "$PRODUCTS_TS"; then
  ALREADY_EXISTS=1
fi

if [ "$ALREADY_EXISTS" -eq 1 ] && [ "$FORCE" -eq 0 ]; then
  log_ok "product slug '$SLUG' already registered — nothing to do (use --force to overwrite)"
  write_status "already_exists" "" "$CANONICAL_URL"
  exit 0
fi

# ----------------------------------------------------------------------------
# Generate the TS object literal + perform insertion + asset copy
#
# Done in one Python pass so we either commit a fully-valid mutation or none.
# ----------------------------------------------------------------------------
set +e
PY_OUT="$(python3 - \
    "$PRODUCT_JSON" "$PRODUCTS_TS" "$HOMEPAGE_REPO" \
    "$SCREENSHOT_LIMIT" "$DRY_RUN" "$FORCE" "$ALREADY_EXISTS" \
    2>&1 <<'PY'
import json, os, re, shutil, sys
from pathlib import Path

(product_json, products_ts, repo_root,
 screenshot_limit, dry_run, force, already_exists) = sys.argv[1:8]

product = json.load(open(product_json, "r", encoding="utf-8"))
screenshot_limit = int(screenshot_limit)
dry_run     = dry_run == "1"
force       = force == "1"
already     = already_exists == "1"

slug = product["slug"]

# ---------------------------------------------------------------- Helpers ----
def js(s):
    """Escape a string for TypeScript single-line string literal."""
    return ('"' + s.replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\n", "\\n").replace("\r", "")
                  .replace("\t", "\\t") + '"')

def locmap(d):
    return "{ ko: " + js(d["ko"]) + ", en: " + js(d["en"]) + " }"

def arrloc(d):
    ko = "[" + ", ".join(js(x) for x in d["ko"]) + "]"
    en = "[" + ", ".join(js(x) for x in d["en"]) + "]"
    return "{ ko: " + ko + ", en: " + en + " }"

def arr(values):
    return "[" + ", ".join(js(x) for x in values) + "]"

# ---------------------------------------------------------------- Build TS ---
indent = "  "
lines = [indent + "{"]
lines.append(indent*2 + f"slug: {js(slug)},")
lines.append(indent*2 + f"name: {locmap(product['name'])},")
lines.append(indent*2 + f"tagline: {locmap(product['tagline'])},")
lines.append(indent*2 + f"description: {locmap(product['description'])},")
lines.append(indent*2 + f"features: {arrloc(product['features'])},")
lines.append(indent*2 + f"platform: {js(product['platform'])},")
lines.append(indent*2 + f"systemRequirements: {js(product['systemRequirements'])},")
lines.append(indent*2 + f"techStack: {arr(product['techStack'])},")
lines.append(indent*2 + f"downloadUrl: {js(product['downloadUrl'])},")
lines.append(indent*2 + f"downloadLabel: {locmap(product['downloadLabel'])},")

# Optional asset URLs — only emit if we actually copy the asset.
icon_src = product.get("iconPath", "")
icon_rel = f"/icons/{slug}.png" if icon_src else ""
if icon_rel:
    lines.append(indent*2 + f"icon: {js(icon_rel)},")

shots_src = product.get("screenshots", [])[:screenshot_limit]
shot_rels = []
for i, _src in enumerate(shots_src, start=1):
    shot_rels.append(f"/screenshots/{slug}/{i:02d}.png")
if shot_rels:
    lines.append(indent*2 + "screenshots: [")
    for r in shot_rels:
        lines.append(indent*3 + js(r) + ",")
    lines.append(indent*2 + "],")

lines.append(indent + "},")
NEW_BLOCK = "\n".join(lines) + "\n"

# ---------------------------------------------------------------- Mutate -----
src = Path(products_ts).read_text(encoding="utf-8")

# Find the start of the products array declaration.
m_open = re.search(r"export\s+const\s+products\s*:\s*Product\[\]\s*=\s*\[", src)
if not m_open:
    print("could not locate `export const products: Product[] = [` in products.ts")
    sys.exit(1)

# Walk from m_open.end() to find the matching closing `];`.
depth = 1
i = m_open.end()
while i < len(src) and depth > 0:
    c = src[i]
    if c == "[":
        depth += 1
    elif c == "]":
        depth -= 1
        if depth == 0:
            close_idx = i
            break
    i += 1
else:
    print("unterminated products array in products.ts")
    sys.exit(1)

# If --force and the slug exists, remove the existing block first.
if already and force:
    # Match a `{ ... slug: "<slug>" ... },` object. Find the slug occurrence,
    # then walk back to the opening `{` (depth-aware) and forward to the
    # closing `},`.
    sm = re.search(r"\{\s*\n?\s*slug:\s*\"" + re.escape(slug) + r"\"", src)
    if not sm:
        print("force=true but could not locate existing slug block")
        sys.exit(1)
    obj_start = sm.start()
    # Walk forward to balanced }
    bdepth = 1
    j = sm.end()
    while j < len(src) and bdepth > 0:
        if src[j] == "{":
            bdepth += 1
        elif src[j] == "}":
            bdepth -= 1
            if bdepth == 0:
                obj_end = j + 1
                break
        j += 1
    else:
        print("unterminated existing slug block")
        sys.exit(1)
    # Eat trailing `,` and one optional newline.
    if obj_end < len(src) and src[obj_end] == ",":
        obj_end += 1
    if obj_end < len(src) and src[obj_end] == "\n":
        obj_end += 1
    src = src[:obj_start] + src[obj_end:]
    # close_idx must be recomputed after the deletion.
    m_open = re.search(r"export\s+const\s+products\s*:\s*Product\[\]\s*=\s*\[", src)
    depth = 1
    i = m_open.end()
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
        i += 1

# Insertion point: just before close_idx, with leading newline if needed.
prefix = src[:close_idx]
suffix = src[close_idx:]
# Trim trailing whitespace on prefix so the new block lines up cleanly.
prefix_rstripped = prefix.rstrip(" \t")
sep = "\n" if not prefix_rstripped.endswith("\n") else ""
new_src = prefix_rstripped + sep + NEW_BLOCK + suffix

if dry_run:
    print("DRY_RUN: would insert the following block before the closing `];` of products[]:")
    print(NEW_BLOCK)
    print("DRY_RUN: would copy assets:")
    if icon_src:
        print(f"  iconPath '{icon_src}' → public/icons/{slug}.png")
    for i, src_path in enumerate(shots_src, start=1):
        print(f"  screenshots[{i}] '{src_path}' → public/screenshots/{slug}/{i:02d}.png")
    print("DRY_RUN_OK")
    sys.exit(0)

# Atomic write.
tmp = products_ts + ".tmp"
Path(tmp).write_text(new_src, encoding="utf-8")
os.replace(tmp, products_ts)

# Asset copy — after products.ts write so a failure here leaves traceable state.
def copy_to(src_path, dst_path):
    sp = Path(src_path)
    if not sp.is_file():
        print(f"asset not found: {src_path}")
        sys.exit(4)
    dp = Path(dst_path)
    dp.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sp, dp)

if icon_src:
    copy_to(icon_src, os.path.join(repo_root, "public", "icons", f"{slug}.png"))

shot_dir = os.path.join(repo_root, "public", "screenshots", slug)
# Remove any prior copies for this slug to avoid stale leftovers from --force runs.
if os.path.isdir(shot_dir):
    for f in os.listdir(shot_dir):
        if f.endswith(".png"):
            os.remove(os.path.join(shot_dir, f))
for i, src_path in enumerate(shots_src, start=1):
    copy_to(src_path, os.path.join(shot_dir, f"{i:02d}.png"))

print("INSERTED_AT=" + str(close_idx))
print(f"COPIED_ASSETS={1 if icon_src else 0}+{len(shots_src)}")
print("MUTATION_OK")
PY
)"
MUTATION_EXIT=$?
set -e

if [ $MUTATION_EXIT -ne 0 ]; then
  log_error "$PY_OUT"
  write_status "failed" "products_ts_mutation_failed" "$CANONICAL_URL"
  exit 3
fi

printf '%s\n' "$PY_OUT"

if [ "$DRY_RUN" -eq 1 ]; then
  if printf '%s\n' "$PY_OUT" | grep -q "DRY_RUN_OK"; then
    log_ok "dry-run validation passed (would register $SLUG)"
    write_status "dry_run" "" "$CANONICAL_URL"
    exit 0
  fi
  log_error "dry-run validation failed"
  write_status "failed" "dry_run_validation_failed" "$CANONICAL_URL"
  exit 3
fi

if ! printf '%s\n' "$PY_OUT" | grep -q "MUTATION_OK"; then
  log_error "products.ts mutation reported failure"
  write_status "failed" "products_ts_mutation_failed" "$CANONICAL_URL"
  exit 3
fi

# ----------------------------------------------------------------------------
# Commit + push
# ----------------------------------------------------------------------------
COMMIT_MSG="Add product: $SLUG"
[ "$ALREADY_EXISTS" -eq 1 ] && [ "$FORCE" -eq 1 ] && COMMIT_MSG="Update product: $SLUG"

set +e
COMMIT_OUTPUT="$(
  cd "$HOMEPAGE_REPO" && \
  git add src/data/products.ts public/icons/ public/screenshots/ 2>&1 && \
  git commit -m "$COMMIT_MSG" 2>&1
)"
COMMIT_EXIT=$?
set -e

printf '%s\n' "$COMMIT_OUTPUT"

if [ $COMMIT_EXIT -ne 0 ]; then
  # `nothing to commit` is benign — happens when the same product is registered
  # twice in a row before any other change lands.
  if printf '%s' "$COMMIT_OUTPUT" | grep -Eqi 'nothing to commit|no changes added'; then
    log_warn "git commit was a no-op (already in sync with origin)"
    write_status "no_op" "nothing_to_commit" "$CANONICAL_URL"
    exit 0
  fi
  log_error "git commit failed"
  write_status "failed" "git_commit_failed" "$CANONICAL_URL"
  exit 2
fi

COMMIT_SHA="$(cd "$HOMEPAGE_REPO" && git rev-parse HEAD)"

if [ "$NO_PUSH" -eq 1 ]; then
  log_ok "committed locally ($COMMIT_SHA) — skipping push (--no-push)."
  write_status "committed_no_push" "" "$CANONICAL_URL" "$COMMIT_SHA"
  exit 0
fi

set +e
PUSH_OUTPUT="$(cd "$HOMEPAGE_REPO" && git push origin "$HOMEPAGE_BRANCH" 2>&1)"
PUSH_EXIT=$?
set -e
printf '%s\n' "$PUSH_OUTPUT"

if [ $PUSH_EXIT -ne 0 ]; then
  log_error "git push failed. The local commit ($COMMIT_SHA) is preserved; resolve the push issue (auth, remote rejection, network) and re-push manually."
  write_status "failed" "git_push_failed" "$CANONICAL_URL" "$COMMIT_SHA"
  exit 2
fi

log_ok "registered '$SLUG' on AXI-Homepage and pushed to origin/$HOMEPAGE_BRANCH ($COMMIT_SHA)"
log_info "canonical product URL: $CANONICAL_URL"
write_status "registered" "" "$CANONICAL_URL" "$COMMIT_SHA"
exit 0
