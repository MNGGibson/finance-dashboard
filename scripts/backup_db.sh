#!/bin/bash
# Nightly dump of the finance database. SimpleFIN only serves 90 days of history, so
# anything older exists nowhere but this database; the dumps live in a folder iCloud
# Drive (or Time Machine) picks up. Keeps the last BACKUP_KEEP dumps.
set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env; set +a
BACKUP_DIR=${BACKUP_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Backups/finance-dashboard}
BACKUP_KEEP=${BACKUP_KEEP:-30}
mkdir -p "$BACKUP_DIR" || exit 1
stamp=$(date +%Y-%m-%d)
file="$BACKUP_DIR/finance-$stamp.sql.gz"
if docker exec finance-postgres pg_dump -U "${POSTGRES_USER:-finance}" "${POSTGRES_DB:-finance}" | gzip > "$file.tmp"; then
    mv "$file.tmp" "$file"
    echo "Backed up to $file ($(du -h "$file" | cut -f1))"
else
    rm -f "$file.tmp"
    echo "Backup failed" >&2
    exit 1
fi
# Category rules as SQL too, so the dashboard's logic is restorable on its own.
.venv/bin/python scripts/rules.py export > "$BACKUP_DIR/category_rules.sql" 2>/dev/null
ls -1t "$BACKUP_DIR"/finance-*.sql.gz | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f
