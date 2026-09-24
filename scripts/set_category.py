#!/usr/bin/env python3
"""Tag one transaction by hand. The daily sync will not overwrite it.

python scripts/set_category.py --find "zelle"          # list matching transactions with ids
python scripts/set_category.py <transaction_id> income:paycheck
python scripts/set_category.py <transaction_id> --auto  # hand it back to the rules
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_conn  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("transaction_id", nargs="?")
    parser.add_argument("category", nargs="?", help="e.g. income:paycheck, bill:rent, spending:discretionary")
    parser.add_argument("--find", metavar="TEXT", help="list recent transactions whose description contains TEXT")
    parser.add_argument("--auto", action="store_true", help="clear the manual flag so the rules apply again")
    args = parser.parse_args()

    conn = get_conn()
    with conn, conn.cursor() as cur:
        if args.find:
            cur.execute(
                "SELECT id, posted::date, amount, description, category, category_manual FROM transactions "
                "WHERE description ILIKE %s ORDER BY posted DESC LIMIT 25",
                (f"%{args.find}%",),
            )
            for row in cur.fetchall():
                flag = " (manual)" if row[5] else ""
                print(f"{row[0]}  {row[1]}  {row[2]:>10}  {row[3][:45]:45}  {row[4] or '-'}{flag}")
            return
        if not args.transaction_id or not (args.category or args.auto):
            parser.error("give a transaction id and a category, or --auto, or --find TEXT")
        if args.auto:
            cur.execute(
                "UPDATE transactions SET category_manual = false, updated_at = now() WHERE id = %s",
                (args.transaction_id,),
            )
        else:
            cur.execute(
                "UPDATE transactions SET category = %s, category_manual = true, updated_at = now() WHERE id = %s",
                (args.category, args.transaction_id),
            )
        if cur.rowcount == 0:
            sys.exit(f"No transaction with id {args.transaction_id}")
        print("Updated. The dashboard picks it up within 5 minutes.")
    conn.close()


if __name__ == "__main__":
    main()
