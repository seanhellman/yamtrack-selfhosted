#!/usr/bin/env bash
set -euo pipefail

# Pulls a consistent snapshot of the live Yamtrack SQLite DB to ~/yamtrack-backups/.
#
# The DB runs in WAL mode, so a plain `scp db.sqlite3` is NOT safe: recently
# committed transactions can still live in the -wal sidecar (not yet checkpointed
# into the main file), and copying the main file mid-checkpoint can tear it. So
# we take a transactionally consistent copy with SQLite's online backup API,
# run as root on the instance (root can attach to the -wal/-shm sidecars, which
# the ssh user cannot — they're owned by uid 1000, mode 644).

ORACLE_HOST="ubuntu@yamtrack-vnic"          # stable MagicDNS name (IP is ephemeral)
ORACLE_KEY="$HOME/.ssh/oracle-yamtrack.key"
REMOTE_DB="/home/ubuntu/yamtrack/db/db.sqlite3"
REMOTE_SNAPSHOT="/tmp/yamtrack-backup-$$.sqlite3"

BACKUP_DIR="$HOME/yamtrack-backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/yamtrack-db-$TIMESTAMP.tar.gz"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"; ssh -i "$ORACLE_KEY" "$ORACLE_HOST" "sudo rm -f $REMOTE_SNAPSHOT" 2>/dev/null || true' EXIT

mkdir -p "$BACKUP_DIR" "$TMP_DIR/db"

# 1) Consistent snapshot on the instance (root: reads through the WAL). The
#    snapshot is set to DELETE journal mode so it's a clean single file (no
#    -wal/-shm sidecars to carry around or reason about).
ssh -i "$ORACLE_KEY" "$ORACLE_HOST" \
  "sudo python3 -c \"import sqlite3; s=sqlite3.connect('$REMOTE_DB'); d=sqlite3.connect('$REMOTE_SNAPSHOT'); s.backup(d); d.execute('PRAGMA journal_mode=DELETE'); d.close(); s.close()\" && sudo chmod 644 $REMOTE_SNAPSHOT"

# 2) Pull it, then archive. (Remote snapshot is removed by the EXIT trap.)
scp -i "$ORACLE_KEY" "$ORACLE_HOST:$REMOTE_SNAPSHOT" "$TMP_DIR/db/db.sqlite3"

# 3) Sanity-check the copy opens and passes an integrity check before trusting it.
if command -v sqlite3 >/dev/null 2>&1; then
  result="$(sqlite3 "$TMP_DIR/db/db.sqlite3" 'PRAGMA integrity_check;' 2>&1)"
  if [ "$result" != "ok" ]; then
    echo "Error: backup failed integrity check: $result" >&2
    exit 1
  fi
fi

tar -czf "$ARCHIVE" -C "$TMP_DIR" db
echo "Backed up $ORACLE_HOST:$REMOTE_DB (consistent snapshot) -> $ARCHIVE"
