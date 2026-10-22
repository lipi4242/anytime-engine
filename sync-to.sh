#!/usr/bin/env bash
# Sync the canonical anytime-engine into a consumer agent repo (vendored copy).
# Usage: sync-to.sh /path/to/agent-repo [--pack calendar|cases|bekotes]... [--allow-downgrade] [--only-pack]
#   --pack calendar     also vendor the optional anytime_calendar pack
#   --pack cases        also vendor the cases concern pack (anytime_cases) and list
#                       it in mentat.json components.engine.plugins. A pack already
#                       listed there is vendored without the flag.
#   --pack bekotes      also vendor the bekotes pack (anytime_bekotes) and list it in
#                       mentat.json components.engine.plugins; kept on re-sync like cases.
#   --allow-downgrade   permit syncing an OLDER engine over a newer copy (a
#                       deliberate rollback — read the state rollback policy first).
#                       "Older" is the version, and — same version — the source
#                       recorded in anytime_engine/.sync-source.json (sync_guard.py)
#   --only-pack [PACK]  copy only the chosen pack(s) and list them in mentat.json;
#                       the vendored engine core is never touched (it must already
#                       be there, inside the pack's engine range)
#
# Writes anytime_engine/VERSION (version + content hash, via the source's own
# anytime_engine.verify) so `python3 -m anytime_engine.verify` in the consumer
# can prove the copy is unmodified and the only one.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET_REPO="${1:?Usage: sync-to.sh /path/to/agent-repo [--pack calendar|cases|bekotes]... [--allow-downgrade] [--only-pack]}"
shift
# Absolute, physical path: the script cd's into the source below, so a relative
# "." would point somewhere else by the time the VERSION stamp is written.
[ -d "$TARGET_REPO" ] || { echo "ERROR: $TARGET_REPO is not a directory" >&2; exit 1; }
TARGET_REPO="$(cd "$TARGET_REPO" && pwd -P)"
TARGET="$TARGET_REPO/anytime_engine"
PACKS=()
ALLOW_DOWNGRADE=0
ONLY_PACK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pack)
      case "${2:-}" in
        calendar|cases|bekotes) PACKS+=("$2"); shift 2 ;;
        *) echo "ERROR: unknown pack: '${2:-}' (known: calendar, cases, bekotes)" >&2; exit 2 ;;
      esac ;;
    --allow-downgrade) ALLOW_DOWNGRADE=1; shift ;;
    --only-pack)
      ONLY_PACK=1; shift
      case "${1:-}" in calendar|cases|bekotes) PACKS+=("$1"); shift ;; esac ;;
    *) echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
  esac
done

# .git is a file in submodules/worktrees — -e, not -d
[ -e "$TARGET_REPO/.git" ] || { echo "ERROR: $TARGET_REPO is not a git repo" >&2; exit 1; }

if [ "$ONLY_PACK" = "1" ] && [ -z "${PACKS[*]-}" ]; then
  echo "ERROR: --only-pack needs a pack (--only-pack bekotes, or --pack ...)" >&2; exit 2
fi

# A concern pack the agent already chose (mentat.json engine.plugins) comes along,
# so a re-sync never leaves a listed pack behind or a stale copy of it in place.
# (--only-pack: only the packs named on the command line.)
[ "$ONLY_PACK" = "1" ] || for chosen in cases bekotes; do
  if python3 -c "
import json,sys
try: p=json.load(open(sys.argv[1]))['components']['engine']['plugins']
except Exception: p=[]
sys.exit(0 if 'anytime_' + sys.argv[2] in p else 1)" "$TARGET_REPO/mentat.json" "$chosen" 2>/dev/null; then
    case " ${PACKS[*]-} " in *" $chosen "*) ;; *) PACKS+=("$chosen") ;; esac
  fi
done

VERSION="$(python3 -c "
import re,pathlib
t=pathlib.Path('$HERE/src/anytime_engine/__init__.py').read_text()
print(re.search(r'__version__ = \"([^\"]+)\"', t).group(1))
")"

# ── Gate: never go backwards by accident ────────────────────────────────
# The vendored version: VERSION (0.3+), else the human VENDORED.md line.
OLD=""
if [ -f "$TARGET/VERSION" ]; then
  OLD="$(sed -n 's/^version=//p' "$TARGET/VERSION" | head -1)"
elif [ -f "$TARGET/VENDORED.md" ]; then
  OLD="$(sed -n 's/^Verzió: //p' "$TARGET/VENDORED.md" | head -1)"
fi
if [ "$ONLY_PACK" = "1" ]; then
  [ -f "$TARGET/__init__.py" ] || { echo "ERROR: --only-pack: no vendored engine in $TARGET — sync the engine first" >&2; exit 1; }
  for pack in "${PACKS[@]}"; do
    python3 "$HERE/sync_guard.py" pack-ok "$HERE" "$TARGET" "anytime_$pack" || exit 1
  done
elif [ -n "$OLD" ] && [ "$ALLOW_DOWNGRADE" = "0" ]; then
  # cd: with -m the cwd comes first on sys.path — never pick up a consumer's copy.
  if ! (cd "$HERE" && PYTHONPATH=src python3 -m anytime_engine.versions check-upgrade "$OLD" "$VERSION"); then
    echo "ERROR: $TARGET holds $OLD; this source is $VERSION. Nothing was changed." >&2
    exit 1
  fi
fi
# Same version is not proof of same age: compare the recorded source / content.
if [ "$ONLY_PACK" = "0" ] && [ "$ALLOW_DOWNGRADE" = "0" ]; then
  python3 "$HERE/sync_guard.py" check "$HERE" "$TARGET" || exit 1
fi

# ── All or nothing: a failure after this point restores what was there ──
# (a half install — files copied, no VERSION, no mentat.json entry — is worse
# than none: nothing verifies and the next run sees a "vendored" copy).
BACKUP="$(mktemp -d)"
ITEMS="anytime_engine anytime_calendar anytime_cases anytime_bekotes mentat.json .mentat/local.json"
for item in $ITEMS; do
  if [ -e "$TARGET_REPO/$item" ]; then
    mkdir -p "$BACKUP/had/$(dirname "$item")"; cp -a "$TARGET_REPO/$item" "$BACKUP/had/$item"
  fi
done
rollback() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    for item in $ITEMS; do
      rm -rf "${TARGET_REPO:?}/$item"
      if [ -e "$BACKUP/had/$item" ]; then
        mkdir -p "$TARGET_REPO/$(dirname "$item")"; cp -a "$BACKUP/had/$item" "$TARGET_REPO/$item"
      fi
    done
    rmdir "$TARGET_REPO/.mentat" 2>/dev/null || true
    echo "ERROR: the sync failed (exit $rc); the repo is back to how it was." >&2
  fi
  rm -rf "$BACKUP"
  exit "$rc"
}
trap rollback EXIT

if [ "$ONLY_PACK" = "0" ]; then
mkdir -p "$TARGET/tests"
# Module files (flat copy; no __pycache__)
for f in "$HERE"/src/anytime_engine/*.py; do
  cp "$f" "$TARGET/$(basename "$f")"
done
for f in "$HERE"/tests/*.py; do
  cp "$f" "$TARGET/tests/$(basename "$f")"
done

# Files that left the core. The copy is never hand-edited, so a stale file here
# is only ever an old vendored one: remove it rather than let it keep importing
# a config function that is going away. (0.3.0: calendar_reconcile -> pack.)
for f in calendar_reconcile.py calendar_reconcile_cli.py tests/test_calendar_reconcile.py; do
  if [ -e "$TARGET/$f" ]; then rm -f "$TARGET/$f"; echo "Removed retired file: anytime_engine/$f"; fi
done
fi

PACK_LINES=""
PLUGIN_ARGS=()   # concern packs (ANYTIME_PLUGIN) the engine must load
for pack in ${PACKS[@]+"${PACKS[@]}"}; do
  case "$pack" in
    calendar) src="$HERE/src/anytime_calendar"; dst="$TARGET_REPO/anytime_calendar" ;;
    cases) src="$HERE/src/anytime_cases"; dst="$TARGET_REPO/anytime_cases"
           PLUGIN_ARGS+=(--plugin anytime_cases) ;;
    bekotes) src="$HERE/src/anytime_bekotes"; dst="$TARGET_REPO/anytime_bekotes"
             PLUGIN_ARGS+=(--plugin anytime_bekotes) ;;
  esac
  [ -d "$src" ] || { echo "ERROR: pack source missing: $src" >&2; exit 1; }
  mkdir -p "$dst"
  for f in "$src"/*.py; do cp "$f" "$dst/$(basename "$f")"; done
  PACK_LINES="$PACK_LINES
Csomag: $pack -> $(basename "$dst")/"
  echo "Synced pack $pack -> $dst"
done

if [ "$ONLY_PACK" = "0" ]; then
# License must travel with the vendored copy — Apache-2.0 requires the
# license and attribution notice to accompany any redistribution, and the
# vendored copy IS a redistribution.
cp "$HERE/LICENSE" "$TARGET/LICENSE"
cp "$HERE/NOTICE" "$TARGET/NOTICE"

cat > "$TARGET/VENDORED.md" <<EOF
# VENDOROLT MÁSOLAT — NE SZERKESZD KÉZZEL

Forrás: https://github.com/lipi4242/anytime-engine (kanonikus)
Verzió: $VERSION
Sync: $(date +%Y-%m-%d)$PACK_LINES

## Frissítés

\`\`\`bash
git clone https://github.com/lipi4242/anytime-engine
./anytime-engine/sync-to.sh <ez-a-repo>
\`\`\`

Javítás/módosítás MINDIG a kanonikus forrásban történik, soha nem itt.
A gépi bélyeg a \`VERSION\` (verzió + tartalom-hash); ellenőrzés:
\`python3 -m anytime_engine.verify\` (kézi szerkesztés, második példány).
Sync után futtasd a teszteket (pytest nem kell; 0 = zöld), és csak zöld mellett commitolj:

\`\`\`bash
python3 -m anytime_engine.selftest
\`\`\`
EOF

# Where this copy came from (the next sync's guard reads it), then the machine
# stamp (version + content hash) — one hash implementation: the source's verify.
python3 "$HERE/sync_guard.py" record "$HERE" "$TARGET"
(cd "$HERE" && PYTHONPATH=src python3 -m anytime_engine.verify --stamp --pkg "$TARGET" >/dev/null)
fi

# mentat.json (if the agent has one): components.engine.path + installed.engine,
# and each vendored concern pack in components.engine.plugins.
( cd "$TARGET_REPO" && ANYTIME_REPO_ROOT="$TARGET_REPO" PYTHONPATH="$TARGET_REPO" \
    python3 -m anytime_engine.engine_manifest ${PLUGIN_ARGS[@]+"${PLUGIN_ARGS[@]}"} ) \
  || { echo "ERROR: mentat.json not updated" >&2; exit 1; }

if [ "$ONLY_PACK" = "1" ]; then
  echo "Synced pack(s) only (${PACKS[*]}); the engine core in $TARGET is untouched."
else
  echo "Synced anytime-engine v$VERSION -> $TARGET"
fi
echo "Now run the tests (no pytest needed; exit 0 = green), from $TARGET_REPO:"
echo "  python3 -m anytime_engine.selftest"
echo "then: python3 -m anytime_engine.setup --tz <user's timezone> (dry run; --install to apply),"
echo "and your own repo's tests, before committing."
