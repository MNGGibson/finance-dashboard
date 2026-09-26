#!/bin/bash
# launchd entry point for the sync (every 6 hours): make sure Docker is up, run the sync, back up,
# and report. Failures raise an email/macOS notification (scripts/notify.py). Every run
# also checks in with a healthchecks.io monitor when HEALTHCHECK_URL is set in .env: if no
# check-in arrives by the deadline, that service emails you from outside this Mac, which
# covers the Mac being off or asleep all day, not just a sync that ran and failed.
set -u
cd "$(dirname "$0")/.." || exit 1
# Read the ping URL from .env unless the environment already provides one.
if [ -z "${HEALTHCHECK_URL:-}" ] && [ -f .env ]; then
    HEALTHCHECK_URL=$(grep -E '^HEALTHCHECK_URL=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')
fi
HEALTHCHECK_URL=${HEALTHCHECK_URL:-}

checkin() {
    # $1: "" (success), "start" or "fail". $2: optional text sent as the body.
    [ -n "$HEALTHCHECK_URL" ] || return 0
    curl -fsS -m 10 --retry 3 -o /dev/null --data-raw "${2:-}" "${HEALTHCHECK_URL%/}${1:+/$1}" \
        || echo "healthchecks.io check-in (${1:-success}) did not go through" >&2
}
fail() {
    # Email (when configured in .env) plus a macOS notification, and tell the monitor.
    .venv/bin/python scripts/notify.py "Daily sync failed" "$1"
    checkin fail "$1"
    exit 1
}

checkin start
scripts/ensure_docker.sh || fail "Docker did not start, so no bank data was pulled."
if ! output=$(.venv/bin/python scripts/sync.py --days 14 2>&1); then
    echo "$output"
    # Last non-warning line is the reason (SimpleFIN error, no accounts, exception).
    reason=$(echo "$output" | grep -v -iE 'warning|warnings\.warn' | tail -1 | cut -c1-120)
    fail "${reason:-see logs/sync.err.log}"
fi
summary=$(echo "$output" | grep -v -iE 'NotOpenSSLWarning|warnings\.warn')
echo "$summary"
# The sync runs every 6 hours; the backup once a day, on the first run that finds no dump
# for today (so a Mac asleep at 7am still gets one). A failed backup is worth a notification.
BACKUP_DIR=${BACKUP_DIR:-$HOME/Backups/finance-dashboard}
if [ -e "$BACKUP_DIR/finance-$(date +%Y-%m-%d).sql.gz" ]; then
    checkin "" "$summary"
elif scripts/backup_db.sh; then
    checkin "" "$summary"
else
    .venv/bin/python scripts/notify.py "Database backup failed" "See logs/sync.err.log on this Mac."
    checkin fail "Sync ok, backup failed"
fi
