#!/usr/bin/env bash
set -euo pipefail

ORACLE_HOST="ubuntu@100.70.228.90"
ORACLE_KEY="$HOME/.ssh/oracle-yamtrack.key"
REMOTE_DB_PATH="~/yamtrack/db/db.sqlite3"

BACKUP_DIR="$HOME/yamtrack-backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/yamtrack-db-$TIMESTAMP.tar.gz"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$BACKUP_DIR" "$TMP_DIR/db"
scp -i "$ORACLE_KEY" "$ORACLE_HOST:$REMOTE_DB_PATH" "$TMP_DIR/db/db.sqlite3"
tar -czf "$ARCHIVE" -C "$TMP_DIR" db

echo "Backed up $ORACLE_HOST:$REMOTE_DB_PATH -> $ARCHIVE"
