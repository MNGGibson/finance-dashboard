#!/bin/bash
# launchd entry point for the daily sync: make sure Docker is up, run the sync, and
# raise a macOS notification if anything fails, so a dead bank link is noticed that morning.
set -u
cd "$(dirname "$0")/.." || exit 1
notify() {
    osascript -e "display notification \"$1\" with title \"Finance dashboard\" subtitle \"Daily sync failed\"" 2>/dev/null
}
if ! scripts/ensure_docker.sh; then
    notify "Docker did not start, so no bank data was pulled."
    exit 1
fi
if ! output=$(.venv/bin/python scripts/sync.py --days 14 2>&1); then
    echo "$output"
    # Last non-warning line is the reason (SimpleFIN error, no accounts, exception).
    reason=$(echo "$output" | grep -v -iE 'warning|warnings\.warn' | tail -1 | cut -c1-120)
    notify "${reason:-see logs/sync.err.log}"
    exit 1
fi
echo "$output" | grep -v -iE 'NotOpenSSLWarning|warnings\.warn'
# Nightly backup rides along with the sync. A failed backup is worth a notification too.
scripts/backup_db.sh || notify "Database backup failed; see logs/sync.err.log"
