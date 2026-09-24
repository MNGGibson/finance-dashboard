#!/bin/bash
# Start Docker Desktop if it is not running and wait for the finance-postgres container.
# Used by both launchd services so a reboot does not leave the dashboard or the sync
# without a database. Exits non-zero if Docker does not come up within the timeout.
set -u
# launchd starts jobs with a minimal PATH that does not include the docker CLI.
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
TIMEOUT=${1:-180}
if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running; starting Docker Desktop"
    open -g -a Docker || { echo "Could not open Docker Desktop" >&2; exit 1; }
fi
for ((i = 0; i < TIMEOUT; i += 3)); do
    if docker info >/dev/null 2>&1; then
        # Compose containers are 'restart: unless-stopped', so they come back with the daemon.
        if [ "$(docker inspect -f '{{.State.Health.Status}}' finance-postgres 2>/dev/null)" = healthy ]; then
            exit 0
        fi
    fi
    sleep 3
done
echo "Docker or finance-postgres not ready after ${TIMEOUT}s" >&2
exit 1
