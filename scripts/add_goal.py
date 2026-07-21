#!/usr/bin/env python3
"""Add or list savings goals. Metabase (OSS) has no easy write-back form for this."""
import argparse
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "finance"),
        user=os.environ.get("POSTGRES_USER", "finance"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


def list_accounts(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, org_name, name, account_type, last_balance FROM accounts ORDER BY account_type")
        print(f"{'id':<42} {'type':<12} {'org / name':<40} balance")
        for id_, org, name, acct_type, balance in cur.fetchall():
            print(f"{id_:<42} {acct_type or '?':<12} {org} / {name:<25} {balance}")


def list_goals(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.id, g.name, g.target_amount, g.target_date,
                   g.starting_amount, a.last_balance, a.name
            FROM goals g
            LEFT JOIN accounts a ON a.id = g.linked_account_id
            ORDER BY g.created_at
            """
        )
        rows = cur.fetchall()
        if not rows:
            print("No goals yet.")
            return
        for id_, name, target, target_date, starting, balance, acct_name in rows:
            progress = (balance - starting) if balance is not None else None
            pct = f"{100 * progress / target:.0f}%" if progress is not None and target else "n/a"
            print(
                f"[{id_}] {name}: {progress if progress is not None else '?'} / {target} "
                f"({pct}) due {target_date or 'no date'} — tracked via {acct_name or 'manual'}"
            )


def add_goal(conn, name, target_amount, target_date, account_id):
    with conn.cursor() as cur:
        starting_amount = 0
        if account_id:
            cur.execute("SELECT last_balance FROM accounts WHERE id = %s", (account_id,))
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"No account with id {account_id!r}. Use --list-accounts to see valid ids.")
            starting_amount = row[0] or 0
        cur.execute(
            """
            INSERT INTO goals (name, target_amount, target_date, linked_account_id, starting_amount)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (name, target_amount, target_date, account_id, starting_amount),
        )
        goal_id = cur.fetchone()[0]
    conn.commit()
    print(f"Created goal #{goal_id}: {name} (target ${target_amount}, starting from ${starting_amount})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-accounts", action="store_true", help="Show linkable account ids and exit")
    parser.add_argument("--list", action="store_true", help="Show existing goals and exit")
    parser.add_argument("name", nargs="?", help="Goal name, e.g. 'Emergency fund'")
    parser.add_argument("target_amount", nargs="?", type=float, help="Target amount, e.g. 5000")
    parser.add_argument("--target-date", help="YYYY-MM-DD, optional")
    parser.add_argument("--account", help="Account id to track progress against (see --list-accounts)")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.list_accounts:
            list_accounts(conn)
        elif args.list:
            list_goals(conn)
        elif args.name and args.target_amount:
            add_goal(conn, args.name, args.target_amount, args.target_date, args.account)
        else:
            parser.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
