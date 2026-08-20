#!/bin/sh
# Push a data directory to the DGX over the tailnet.
#
# No rsync on this Windows box, so this streams a tarball over ssh instead. That is a
# full copy every run, not a delta. Fine while the corpus is megabytes; install rsync
# on both ends and swap the pipe for `rsync -az --delete` when it stops being.
#
#   DGX_USER=<user> ./sync.sh ../project-data
#   DGX_USER=<user> DGX_DEST=/data/cosmai ./sync.sh ../project-data/datasets
#
# The DGX is `spark-2ea6` (100.96.113.69) on the tailnet. It does not run Tailscale
# SSH, so this needs a real account and an authorized key on that host.

set -eu

HOST="${DGX_HOST:-spark-2ea6}"
USER="${DGX_USER:?set DGX_USER to the SSH account on $HOST}"
DEST="${DGX_DEST:-cosmai-data}"
SRC="${1:?usage: sync.sh SOURCE_DIR}"

[ -d "$SRC" ] || { echo "not a directory: $SRC" >&2; exit 1; }

echo "sending $SRC -> $USER@$HOST:$DEST"
tar czf - -C "$SRC" . \
  | ssh "$USER@$HOST" "mkdir -p '$DEST' && tar xzf - -C '$DEST' && du -sh '$DEST'"
