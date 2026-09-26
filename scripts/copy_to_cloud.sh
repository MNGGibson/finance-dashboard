#!/bin/bash
# One-time copy of the local database into a hosted one (schema, data, rules, migrations).
#   DATABASE_URL="postgresql://..." scripts/copy_to_cloud.sh
# Safe to re-run: it drops and recreates the tables in the target first.
set -eu
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.docker/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1
: "${DATABASE_URL:?set DATABASE_URL to the hosted database connection string}"
set -a; . ./.env; set +a
echo "Dumping the local database and loading it into the hosted one"
docker exec finance-postgres pg_dump -U "${POSTGRES_USER:-finance}" --clean --if-exists --no-owner --no-privileges "${POSTGRES_DB:-finance}" \
    | docker run -i --rm postgres:16 psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q
echo "Row counts in the hosted database:"
docker run -i --rm postgres:16 psql "$DATABASE_URL" -Atc \
    "select 'accounts', count(*) from accounts union all select 'transactions', count(*) from transactions union all select 'category_rules', count(*) from category_rules union all select 'balance_snapshots', count(*) from balance_snapshots"
