#!/bin/sh
# Put this repository on the GPU host at a known commit, and record which one.
#
# The previous method was scp of whichever files were being edited. An audit found the
# result: model_a.py on spark-2ea6 was the pre-purge version, still reporting MAE 0.1398
# and passing its own self-check, while the repository had moved to 0.1360. Numbers were
# quoted from a host running code nobody could name.
#
# So: git archive at HEAD, which cannot carry a working-tree edit, plus a MANIFEST naming
# the commit. Anything the archive does not contain is deleted from the destination first,
# because a stale file that nobody overwrites is exactly how the last drift happened.

set -eu

HOST="${DEPLOY_HOST:-user@spark-2ea6}"
DEST="${DEPLOY_DEST:-cosmai-data}"

cd "$(dirname "$0")"

if [ -n "$(git status --porcelain)" ]; then
  echo "working tree is dirty -- commit first, so the deployed commit means something" >&2
  git status --short >&2
  exit 1
fi

commit=$(git rev-parse HEAD)
short=$(git rev-parse --short HEAD)
stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "deploying $short to $HOST:$DEST"

# The venv, the data and the model outputs live in the destination and are not ours to
# remove; only the tracked .py and .md files are replaced.
git ls-files -z '*.py' '*.md' | ssh "$HOST" "cd '$DEST' && xargs -0 -r rm -f"

git archive --format=tar HEAD $(git ls-files '*.py' '*.md') \
  | ssh "$HOST" "tar xf - -C '$DEST'"

ssh "$HOST" "cat > '$DEST/MANIFEST.txt'" <<EOF
commit:    $commit
short:     $short
deployed:  $stamp
from:      $(git config --get remote.origin.url)
files:     $(git ls-files '*.py' '*.md' | wc -l | tr -d ' ')
EOF

echo "verifying"
remote=$(ssh "$HOST" "grep '^commit:' '$DEST/MANIFEST.txt' | awk '{print \$2}'")
[ "$remote" = "$commit" ] || { echo "manifest mismatch: $remote != $commit" >&2; exit 1; }
ssh "$HOST" "cd '$DEST' && ls *.py"
echo "ok: $short"
