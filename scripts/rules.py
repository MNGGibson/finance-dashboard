#!/usr/bin/env python3
"""Export or load the category rules, the substring -> category mapping that drives the
dashboard. They live in Postgres; this keeps a copy on disk that backups and a fresh
install can use.

    python scripts/rules.py export > db/category_rules.local.sql   # your rules (gitignored)
    python scripts/rules.py load db/category_rules.example.sql      # seed a fresh database
    python scripts/rules.py list

The export is plain INSERT statements, idempotent on (pattern, category).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_conn  # noqa: E402


def export(cur):
    cur.execute("SELECT pattern, category, priority FROM category_rules ORDER BY priority DESC, category, pattern")
    print("-- category_rules: substring (case-insensitive) -> category. Higher priority wins.")
    for pattern, category, priority in cur.fetchall():
        quoted = pattern.replace("'", "''")
        print(
            f"INSERT INTO category_rules (pattern, category, priority) SELECT '{quoted}', '{category}', {priority} "
            f"WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '{quoted}' AND category = '{category}');"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "load", "list"])
    parser.add_argument("file", nargs="?", help="SQL file to load")
    args = parser.parse_args()
    conn = get_conn()
    with conn, conn.cursor() as cur:
        if args.action == "export":
            export(cur)
        elif args.action == "list":
            cur.execute("SELECT priority, category, pattern FROM category_rules ORDER BY priority DESC, category")
            for priority, category, pattern in cur.fetchall():
                print(f"{priority:>3}  {category:28} {pattern}")
        else:
            if not args.file:
                parser.error("load needs a file")
            cur.execute(Path(args.file).read_text())
            cur.execute("SELECT count(*) FROM category_rules")
            print(f"Loaded. {cur.fetchone()[0]} rules in the database.")
    conn.close()


if __name__ == "__main__":
    main()
