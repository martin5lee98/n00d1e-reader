#!/usr/bin/env bash
# backup.sh -- download a full copy of the D1 database to this computer.
#
# Usage (from anywhere):
#   ./backup.sh                 # saves to ~/Backups/yuelanshi
#   ./backup.sh /some/folder    # saves somewhere else
#
# Produces two files named by date:
#   backup-YYYY-MM-DD.sql  -- plain-text SQL dump (what you'd restore from)
#   backup-YYYY-MM-DD.db   -- the same data as a SQLite file you can open
#                             in DB Browser for SQLite
#
# Requires being logged in to wrangler (npx wrangler login) -- no env vars.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HOME/Backups/yuelanshi}"
STAMP="$(date +%Y-%m-%d_%H%M)"
SQL="$DEST/backup-$STAMP.sql"
DB="$DEST/backup-$STAMP.db"

mkdir -p "$DEST"

echo "Exporting yuelanshi-articles -> $SQL"
(cd "$REPO_DIR/astro-src" && npx wrangler d1 export yuelanshi-articles --remote --output="$SQL")

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" < "$SQL"
  n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM articles;")
  echo "Created $DB ($n articles)"
else
  echo "sqlite3 not found -- skipped creating the .db file (the .sql backup is complete)."
fi

echo "Done."
