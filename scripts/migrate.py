#!/usr/bin/env python3
"""Apply db/migrations/*.sql that have not been applied yet, in name order.

db/schema.sql is the full current schema for a fresh database. Migrations exist for
databases that already hold data. Each is written to be safe to re-run (IF NOT EXISTS),
so applying them to a fresh database is harmless; the schema_migrations table just
records what ran.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import ROOT, get_conn  # noqa: E402

MIGRATIONS = ROOT / "db" / "migrations"


def main():
    conn = get_conn()
    with conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT name FROM schema_migrations")
        done = {row[0] for row in cur.fetchall()}
        pending = [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.name not in done]
        for path in pending:
            cur.execute(path.read_text())
            cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            print(f"Applied {path.name}")
    conn.close()
    print(f"{len(pending)} migration(s) applied, {len(done)} already in place.")


if __name__ == "__main__":
    main()
