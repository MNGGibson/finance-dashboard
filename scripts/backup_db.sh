#!/bin/bash
# Nightly dump of the finance database. SimpleFIN only serves 90 days of history, so
# anything older exists nowhere but this database. Dumps go to a local folder (Time
# Machine covers it) and are mirrored to iCloud Drive when it exists. Keeps BACKUP_KEEP.
#
# The mirror uses only shell redirection: macOS refuses background (launchd) jobs some
# operations inside iCloud Drive, and plain redirection is what works there.
set -u
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env; set +a
BACKUP_DIR=${BACKUP_DIR:-$HOME/Backups/finance-dashboard}
BACKUP_KEEP=${BACKUP_KEEP:-30}
ICLOUD_DIR=${ICLOUD_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/Backups/finance-dashboard}
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

# Keep the newest BACKUP_KEEP dumps (bash globs sort by name, and names sort by date).
dumps=("$BACKUP_DIR"/finance-*.sql.gz)
while [ ${#dumps[@]} -gt "$BACKUP_KEEP" ]; do
    rm -f "${dumps[0]}"
    dumps=("${dumps[@]:1}")
done

# Mirror to iCloud Drive if it is set up. Best effort: a refusal is reported, not fatal.
if [ -d "$(dirname "$ICLOUD_DIR")" ] || mkdir -p "$ICLOUD_DIR" 2>/dev/null; then
    mkdir -p "$ICLOUD_DIR" 2>/dev/null
    # Dated names only: a background job may create files in iCloud Drive, but macOS refuses
    # it permission to overwrite one that an interactive app created.
    if cat "$file" > "$ICLOUD_DIR/finance-$stamp.sql.gz" 2>/dev/null \
       && cat "$BACKUP_DIR/category_rules.sql" > "$ICLOUD_DIR/category_rules-$stamp.sql" 2>/dev/null; then
        echo "Mirrored to iCloud Drive"
    else
        echo "Could not mirror to iCloud Drive (macOS may block background jobs there); local copy is fine" >&2
    fi
fi
