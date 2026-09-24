#!/usr/bin/env python3
"""Pull accounts/balances/transactions from SimpleFIN and upsert into Postgres.

Intended to run daily (see launchd/com.financedashboard.sync.plist). Exits non-zero
when SimpleFIN reports an error or returns no accounts, so a broken bank link shows up
as a failed job rather than a quiet stretch of stale data.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_conn  # noqa: E402

ACCESS_URL = os.environ["SIMPLEFIN_ACCESS_URL"]


def split_auth(url: str):
    parts = urlsplit(url)
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    clean_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return clean_url, (parts.username, parts.password)


def fetch_accounts(start_date=None):
    base_url, auth = split_auth(ACCESS_URL)
    params = {"start-date": int(start_date)} if start_date is not None else {}
    resp = requests.get(f"{base_url}/accounts", auth=auth, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def load_category_rules(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT pattern, category FROM category_rules ORDER BY priority DESC")
        return [(pattern.strip("%").lower(), category) for pattern, category in cur.fetchall()]


def load_account_types(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, account_type FROM accounts")
        return dict(cur.fetchall())


def categorize(description, rules, account_type=None, amount=None):
    if description:
        desc_lower = description.lower()
        for pattern, category in rules:
            if pattern in desc_lower:
                return category
    # Fallback: any otherwise-unmatched charge on a credit card is discretionary spending
    if account_type == "credit_card" and amount is not None and float(amount) < 0:
        return "spending:discretionary"
    return None


def upsert(conn, data):
    now = datetime.now(timezone.utc)
    rules = load_category_rules(conn)
    account_types = load_account_types(conn)
    with conn.cursor() as cur:
        for account in data.get("accounts", []):
            balance_date = (
                datetime.fromtimestamp(account["balance-date"], tz=timezone.utc)
                if account.get("balance-date")
                else None
            )
            cur.execute(
                """
                INSERT INTO accounts (id, org_name, name, currency, last_balance, balance_date, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    org_name = EXCLUDED.org_name,
                    name = EXCLUDED.name,
                    currency = EXCLUDED.currency,
                    last_balance = EXCLUDED.last_balance,
                    balance_date = EXCLUDED.balance_date,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    account["id"],
                    account.get("org", {}).get("name", "Unknown"),
                    account["name"],
                    account.get("currency", "USD"),
                    account.get("balance"),
                    balance_date,
                    now,
                ),
            )

            cur.execute(
                "INSERT INTO balance_snapshots (account_id, balance, as_of) VALUES (%s, %s, %s)",
                (account["id"], account.get("balance"), now),
            )

            for txn in account.get("transactions", []):
                category = categorize(
                    txn.get("description"), rules,
                    account_type=account_types.get(account["id"]),
                    amount=txn["amount"],
                )
                cur.execute(
                    """
                    INSERT INTO transactions (id, account_id, posted, amount, description, pending, category, raw, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        posted = EXCLUDED.posted,
                        amount = EXCLUDED.amount,
                        description = EXCLUDED.description,
                        pending = EXCLUDED.pending,
                        -- A category set by hand (scripts/set_category.py) is kept. Otherwise the
                        -- rules win, but a rule miss never blanks a category that was already set.
                        category = CASE WHEN transactions.category_manual THEN transactions.category
                                        ELSE COALESCE(EXCLUDED.category, transactions.category) END,
                        raw = EXCLUDED.raw,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        txn["id"],
                        account["id"],
                        datetime.fromtimestamp(txn["posted"], tz=timezone.utc),
                        txn["amount"],
                        txn.get("description"),
                        txn.get("pending", False),
                        category,
                        json.dumps(txn),
                        now,
                    ),
                )
    conn.commit()


def recategorize(conn):
    """Re-run the rules over every stored transaction that was not tagged by hand.

    The daily sync only re-fetches a two-week window, so a new rule, or an account whose
    type was set after its transactions arrived, leaves older rows behind. Returns the
    number of rows whose category changed.
    """
    rules = load_category_rules(conn)
    account_types = load_account_types(conn)
    changed = 0
    with conn.cursor() as cur:
        cur.execute("SELECT id, account_id, description, amount, category FROM transactions "
                    "WHERE NOT category_manual")
        for txn_id, account_id, description, amount, current in cur.fetchall():
            category = categorize(description, rules, account_types.get(account_id), amount)
            if category is not None and category != current:
                cur.execute("UPDATE transactions SET category = %s, updated_at = now() WHERE id = %s",
                            (category, txn_id))
                changed += 1
    conn.commit()
    return changed


def response_problems(data):
    """Print SimpleFIN's errors and say whether the run should count as failed."""
    failed = False
    for error in data.get("errors", []):
        # A capped date range is a notice, not a failure; anything else means the bank link is off.
        if "capped" in str(error).lower():
            print("SimpleFIN notice:", error)
        else:
            print("SimpleFIN error:", error, file=sys.stderr)
            failed = True
    if not data.get("accounts"):
        print("SimpleFIN returned no accounts; nothing synced.", file=sys.stderr)
        failed = True
    return failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--days", type=int, default=None,
        help="Request this many days of transaction history (bank may return less than asked for)",
    )
    parser.add_argument(
        "--recategorize", action="store_true",
        help="Also re-run the category rules over every stored transaction not tagged by hand",
    )
    args = parser.parse_args()

    start_date = time.time() - args.days * 86400 if args.days is not None else None

    data = fetch_accounts(start_date=start_date)
    failed = response_problems(data)

    conn = get_conn()
    try:
        upsert(conn, data)
        if args.recategorize:
            print(f"Recategorized {recategorize(conn)} transactions")
    finally:
        conn.close()

    n_accounts = len(data.get("accounts", []))
    n_txns = sum(len(a.get("transactions", [])) for a in data.get("accounts", []))
    if data.get("accounts"):
        oldest = min(
            (t["posted"] for a in data["accounts"] for t in a.get("transactions", [])),
            default=None,
        )
        oldest_str = datetime.fromtimestamp(oldest, tz=timezone.utc).date() if oldest else "n/a"
    else:
        oldest_str = "n/a"
    print(
        f"Synced {n_accounts} accounts, {n_txns} transactions "
        f"(oldest: {oldest_str}) at {datetime.now(timezone.utc).isoformat()}"
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
