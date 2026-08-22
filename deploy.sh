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

# Delete by extension, not by `git ls-files`. Listing tracked files names only what the
# repository still has, so a file deleted from the repository is exactly the one that
# survives on the host -- which is the drift this script exists to stop, and which it
# reproduced on its first run by doing precisely that.
#
# Everything matching these extensions in the destination came from this repository. Data,
# venv, model outputs and MANIFEST.txt have other extensions and are left alone.
ssh "$HOST" "cd '$DEST' && rm -f -- *.py *.md && rm -rf -- __pycache__ experiments"

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
