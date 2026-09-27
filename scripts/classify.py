#!/usr/bin/env python3
"""Review and correct how merchants are grouped.

    python scripts/classify.py --review                 # merchants still unclassified, biggest first
    python scripts/classify.py --list                   # every merchant and its group
    python scripts/classify.py --set "Rico Nail" spending:personal_care
    python scripts/classify.py --groups                 # the group names and what they mean
    python scripts/classify.py --export > db/merchant_categories.local.sql

A group set here is marked manual and never overwritten by the keyword or model layers.
Setting one re-tags that merchant's past card charges too (unless tagged by hand).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from classify import DEFAULT, GROUPS, merchant_key  # noqa: E402
from db import get_conn  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--groups", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--set", nargs=2, metavar=("MERCHANT", "GROUP"))
    args = parser.parse_args()

    if args.groups:
        for key, what in GROUPS.items():
            print(f"{key:26} {what}")
        return

    conn = get_conn()
    with conn, conn.cursor() as cur:
        if args.review:
            cur.execute(
                "SELECT lower(coalesce(nullif(raw->>'payee',''), description)) m, count(*), round(sum(-amount)) "
                "FROM transactions WHERE category = %s GROUP BY 1 ORDER BY 3 DESC",
                (DEFAULT,),
            )
            rows = cur.fetchall()
            if not rows:
                print("Every merchant is classified.")
            for merchant, n, total in rows:
                print(f"{merchant:40} {n:>4} charges  ${total:>8}")
            if rows:
                print(
                    '\nAssign one with: python scripts/classify.py --set "<merchant>" <group>   (--groups lists them)'
                )
        elif args.list:
            cur.execute("SELECT merchant, category, source FROM merchant_categories ORDER BY category, merchant")
            for merchant, category, source in cur.fetchall():
                print(f"{category:26} {merchant:40} {source}")
        elif args.export:
            cur.execute("SELECT merchant, category, source FROM merchant_categories ORDER BY merchant")
            print("-- merchant_categories export")
            for merchant, category, source in cur.fetchall():
                m = merchant.replace("'", "''")
                print(
                    f"INSERT INTO merchant_categories (merchant, category, source) VALUES ('{m}', '{category}', '{source}') "
                    f"ON CONFLICT (merchant) DO UPDATE SET category = EXCLUDED.category, source = EXCLUDED.source;"
                )
        elif args.set:
            name, group = args.set
            if group not in GROUPS:
                sys.exit(f"Unknown group {group!r}; --groups lists them")
            merchant = merchant_key(name, "")
            cur.execute(
                "INSERT INTO merchant_categories (merchant, category, source) VALUES (%s, %s, 'manual') "
                "ON CONFLICT (merchant) DO UPDATE SET category = EXCLUDED.category, source = 'manual', updated_at = now()",
                (merchant, group),
            )
            cur.execute(
                "UPDATE transactions SET category = %s, updated_at = now() WHERE NOT category_manual "
                "AND category LIKE 'spending:%%' AND lower(coalesce(nullif(raw->>'payee',''), description)) = %s",
                (group, merchant),
            )
            print(f"{merchant} -> {group}; re-tagged {cur.rowcount} past charges.")
        else:
            parser.print_help()
    conn.close()


if __name__ == "__main__":
    main()
