#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_DIR="$SCRIPT_DIR/db"
BACKUP_DIR="$HOME/yamtrack-backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/yamtrack-db-$TIMESTAMP.tar.gz"

if [ ! -d "$DB_DIR" ]; then
  echo "Error: $DB_DIR not found. Run this from the repo root after the stack has started at least once." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
tar -czf "$ARCHIVE" -C "$SCRIPT_DIR" db

echo "Backed up $DB_DIR -> $ARCHIVE"
