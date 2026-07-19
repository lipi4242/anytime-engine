#!/usr/bin/env bash
# Sync the canonical anytime-engine into a consumer agent repo (vendored copy).
# Usage: packages/anytime-engine/sync-to.sh /path/to/agent-repo
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET_REPO="${1:?Usage: sync-to.sh /path/to/agent-repo}"
TARGET="$TARGET_REPO/anytime_engine"

# .git is a file in submodules/worktrees — -e, not -d
[ -e "$TARGET_REPO/.git" ] || { echo "ERROR: $TARGET_REPO is not a git repo" >&2; exit 1; }

VERSION="$(python3 -c "
import re,pathlib
t=pathlib.Path('$HERE/src/anytime_engine/__init__.py').read_text()
print(re.search(r'__version__ = \"([^\"]+)\"', t).group(1))
")"

mkdir -p "$TARGET/tests"
# Module files (flat copy; no __pycache__)
for f in "$HERE"/src/anytime_engine/*.py; do
  cp "$f" "$TARGET/$(basename "$f")"
done
for f in "$HERE"/tests/*.py; do
  cp "$f" "$TARGET/tests/$(basename "$f")"
done

# License must travel with the vendored copy — Apache-2.0 requires the
# license and attribution notice to accompany any redistribution, and the
# vendored copy IS a redistribution.
cp "$HERE/LICENSE" "$TARGET/LICENSE"
cp "$HERE/NOTICE" "$TARGET/NOTICE"

cat > "$TARGET/VENDORED.md" <<EOF
# VENDOROLT MÁSOLAT — NE SZERKESZD KÉZZEL

Forrás: https://github.com/lipi4242/anytime-engine (kanonikus)
Verzió: $VERSION
Sync: $(date +%Y-%m-%d)

## Frissítés

\`\`\`bash
git clone https://github.com/lipi4242/anytime-engine
./anytime-engine/sync-to.sh <ez-a-repo>
\`\`\`

Javítás/módosítás MINDIG a kanonikus forrásban történik, soha nem itt.
Sync után futtasd a teszteket, és csak zöld mellett commitolj.
EOF

echo "Synced anytime-engine v$VERSION -> $TARGET"
echo "Now run the consumer repo's tests before committing."
