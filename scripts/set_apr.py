#!/usr/bin/env python3
"""Set the real APR on a credit card / loan account, once you know it."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_conn  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="Show accounts and their current apr, then exit")
    parser.add_argument("account_id", nargs="?")
    parser.add_argument("apr", nargs="?", type=float, help="Annual percentage rate, e.g. 24.99")
    args = parser.parse_args()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if args.list or not (args.account_id and args.apr is not None):
                cur.execute(
                    "SELECT id, org_name, name, account_type, apr FROM accounts "
                    "WHERE account_type IN ('credit_card', 'loan') ORDER BY name"
                )
                for id_, org, name, acct_type, apr in cur.fetchall():
                    print(f"[{id_}] {org} / {name} ({acct_type}) — apr: {apr if apr is not None else 'not set'}")
                return
            cur.execute("UPDATE accounts SET apr = %s WHERE id = %s RETURNING name", (args.apr, args.account_id))
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"No account with id {args.account_id!r}")
            conn.commit()
            print(f"Set apr={args.apr} on {row[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
