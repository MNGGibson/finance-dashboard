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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from classify import (  # noqa: E402
    CARD_CREDIT,
    REVIEW_BATCH,
    Classifier,
    credit_wording,
    description_override,
    review_categories,
)
from classify import DEFAULT as UNCLASSIFIED  # noqa: E402
from db import get_conn, setting  # noqa: E402

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


def categorize_with_source(description, rules, account_type=None, amount=None, classifier=None, payee=None):
    """(category, source). Rules first. A card charge no rule matches is placed by merchant
    (classify.py); one the merchant layers cannot place yet stays unclassified card spending."""
    if description:
        desc_lower = description.lower()
        for pattern, category in rules:
            if pattern in desc_lower:
                return category, "rule"
    if amount is None or classifier is None:
        if account_type == "credit_card" and amount is not None and float(amount) < 0:
            return UNCLASSIFIED, "default"
        return None, None
    amount = float(amount)
    if account_type == "credit_card" and amount > 0 and credit_wording(description):
        return CARD_CREDIT, "keyword"  # a perk or reimbursement, whatever store issued it
    override = description_override(description)
    if override and account_type in ("credit_card", "checking", "savings"):
        # Explicit patterns (fuel, plan fees, memberships): the model's review leaves these alone.
        return override, "override"
    if account_type == "credit_card":
        # Charges are grouped by merchant. Money coming back is a payment you made, a
        # statement credit, or a refund; a refund takes its merchant's group, so it nets out.
        placed = classifier.category_for(payee, description)
        if placed:
            return placed, "merchant"
        return (UNCLASSIFIED, "default") if amount < 0 else (CARD_CREDIT, "default")
    if account_type in ("checking", "savings") and amount < 0:
        # Debit-card purchases and Zelle payments from the bank account, same layers.
        placed = classifier.category_for(payee, description)
        return (placed, "merchant") if placed else (UNCLASSIFIED, "default")
    if account_type in ("checking", "savings") and amount > 0:
        # Deposits no rule names: interest by keyword, anything else is other income.
        placed = classifier.category_for(payee, description, spending_only=False)
        return (placed, "merchant") if placed else ("income:other", "default")
    return None, None


def categorize(description, rules, account_type=None, amount=None, classifier=None, payee=None):
    return categorize_with_source(description, rules, account_type, amount, classifier, payee)[0]


def review_rows(conn, where_sql, params=(), label="new"):
    """The model audits proposed groups for the rows `where_sql` selects (never manual ones),
    with the raw text and amount as evidence, and corrects the ones it disagrees with.
    Returns the number corrected. Skipped silently without a key; never fails the sync."""
    api_key = setting("GEMINI_API_KEY")
    if not api_key:
        return 0
    with conn.cursor() as cur:
        # Rules are the owner's own knowledge (their landlord, their employer, their family) and are
        # never second-guessed; the model only reviews what the generic merchant/keyword layers decided.
        cur.execute(
            "SELECT t.id, t.description, t.raw->>'payee', t.amount, a.account_type, t.category "
            "FROM transactions t JOIN accounts a ON a.id = t.account_id "
            "WHERE NOT t.category_manual AND coalesce(t.category_source, '') NOT IN ('rule', 'manual', 'override') "
            f"AND ({where_sql})",
            params,
        )
        rows = cur.fetchall()
    items = [
        {"id": r[0], "description": r[1], "payee": r[2], "amount": r[3], "account_type": r[4], "proposed": r[5]}
        for r in rows
        if r[5]
    ]
    corrected = 0
    for start in range(0, len(items), REVIEW_BATCH):
        batch = items[start : start + REVIEW_BATCH]
        changes = None
        for attempt in range(1, 4):  # the free tier answers 503 now and then; wait and retry
            try:
                changes = review_categories(batch, api_key)
                break
            except Exception as error:  # noqa: BLE001  (a model outage must not fail the sync)
                if attempt == 3:
                    print(f"Model review skipped for {len(batch)} rows: {error}", file=sys.stderr)
                else:
                    time.sleep(10 * attempt)
        print(f"  reviewed {min(start + REVIEW_BATCH, len(items))}/{len(items)}", flush=True)
        if changes is None:
            continue
        with conn.cursor() as cur:
            for txn_id, (category, reason) in changes.items():
                cur.execute(
                    "UPDATE transactions SET category = %s, category_source = 'model', category_note = %s, "
                    "updated_at = now() WHERE id = %s AND NOT category_manual",
                    (category, reason, txn_id),
                )
                corrected += cur.rowcount
        conn.commit()
    print(f"Model reviewed {len(items)} {label} transactions, corrected {corrected}")
    return corrected


def load_merchant_categories(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT merchant, category FROM merchant_categories")
        return dict(cur.fetchall())


def save_learned(conn, classifier):
    """Persist what the keyword and model layers decided, never overwriting a manual entry."""
    if not classifier.learned:
        return 0
    with conn.cursor() as cur:
        for merchant, category, source in classifier.learned:
            cur.execute(
                "INSERT INTO merchant_categories (merchant, category, source) VALUES (%s, %s, %s) "
                "ON CONFLICT (merchant) DO UPDATE SET category = EXCLUDED.category, source = EXCLUDED.source, "
                "updated_at = now() WHERE merchant_categories.source <> 'manual'",
                (merchant, category, source),
            )
    conn.commit()
    count = len(classifier.learned)
    classifier.learned = []
    return count


def apply_model(conn, classifier):
    """Let the model place the merchants nothing else could, when a key is configured."""
    api_key = setting("GEMINI_API_KEY")
    if not api_key or not classifier.pending:
        return {}
    try:
        answers = classifier.resolve_pending(api_key)
    except Exception as error:  # noqa: BLE001  (a model outage must not fail the sync)
        print(f"Model classification skipped: {error}", file=sys.stderr)
        return {}
    if answers:
        with conn.cursor() as cur:
            for merchant, category in answers.items():
                cur.execute(
                    "UPDATE transactions SET category = %s, updated_at = now() WHERE NOT category_manual "
                    "AND category = %s AND lower(coalesce(nullif(raw->>'payee', ''), description)) = %s",
                    (category, UNCLASSIFIED, merchant),
                )
        conn.commit()
    return answers


def upsert(conn, data):
    now = datetime.now(timezone.utc)
    rules = load_category_rules(conn)
    account_types = load_account_types(conn)
    descriptions = [t.get("description") for a in data.get("accounts", []) for t in a.get("transactions", [])]
    classifier = Classifier(load_merchant_categories(conn), descriptions)
    touched = []
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
                category, source = categorize_with_source(
                    txn.get("description"),
                    rules,
                    account_type=account_types.get(account["id"]),
                    amount=txn["amount"],
                    classifier=classifier,
                    payee=txn.get("payee"),
                )
                touched.append(txn["id"])
                cur.execute(
                    """
                    INSERT INTO transactions (id, account_id, posted, amount, description, pending, category,
                                              category_source, raw, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        posted = EXCLUDED.posted,
                        amount = EXCLUDED.amount,
                        description = EXCLUDED.description,
                        pending = EXCLUDED.pending,
                        -- A category set by hand, or corrected by the model's review, is kept.
                        -- Otherwise the layers win, but a miss never blanks a category already set.
                        category = CASE WHEN transactions.category_manual OR transactions.category_source = 'model'
                                        THEN transactions.category
                                        ELSE COALESCE(EXCLUDED.category, transactions.category) END,
                        category_source = CASE WHEN transactions.category_manual OR transactions.category_source = 'model'
                                               THEN transactions.category_source
                                               ELSE COALESCE(EXCLUDED.category_source, transactions.category_source) END,
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
                        source,
                        json.dumps(txn),
                        now,
                    ),
                )
    conn.commit()
    save_learned(conn, classifier)
    placed = apply_model(conn, classifier)
    save_learned(conn, classifier)
    if placed:
        print(f"Model placed {len(placed)} new merchants")
    if classifier.pending:
        print(f"{len(classifier.pending)} merchants still unclassified; run scripts/classify.py --review")
    # The model's review of everything this run brought in that was not already reviewed.
    if touched:
        review_rows(
            conn,
            "t.id = ANY(%s) AND coalesce(t.category_source, '') <> 'model' AND t.updated_at >= %s",
            (touched, now - timedelta(minutes=5)),
        )


def recategorize(conn):
    """Re-run the rules and merchant layers over every stored transaction not tagged by hand.

    The daily sync only re-fetches a two-week window, so a new rule, a new merchant group,
    or an account whose type was set after its transactions arrived leaves older rows
    behind. Returns the number of rows whose category changed.
    """
    rules = load_category_rules(conn)
    account_types = load_account_types(conn)
    changed = 0
    with conn.cursor() as cur:
        cur.execute("SELECT description FROM transactions")
        classifier = Classifier(load_merchant_categories(conn), [row[0] for row in cur.fetchall()])
        cur.execute("SELECT id, category_source FROM transactions")
        sources = dict(cur.fetchall())
        cur.execute(
            "SELECT id, account_id, description, amount, category, raw->>'payee' FROM transactions "
            "WHERE NOT category_manual AND coalesce(category_source, '') <> 'model'"
        )
        for txn_id, account_id, description, amount, current, payee in cur.fetchall():
            category, source = categorize_with_source(
                description, rules, account_types.get(account_id), amount, classifier, payee
            )
            if category is None:
                continue
            if category != current:
                cur.execute(
                    "UPDATE transactions SET category = %s, category_source = %s, updated_at = now() WHERE id = %s",
                    (category, source, txn_id),
                )
                changed += 1
            elif sources.get(txn_id) != source:
                cur.execute("UPDATE transactions SET category_source = %s WHERE id = %s", (source, txn_id))
    conn.commit()
    save_learned(conn, classifier)
    changed += len(apply_model(conn, classifier))
    save_learned(conn, classifier)
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
        "--days",
        type=int,
        default=None,
        help="Request this many days of transaction history (bank may return less than asked for)",
    )
    parser.add_argument(
        "--recategorize",
        action="store_true",
        help="Also re-run the category rules over every stored transaction not tagged by hand",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Have the model review every stored transaction's group against its raw text (needs GEMINI_API_KEY)",
    )
    args = parser.parse_args()

    start_date = time.time() - args.days * 86400 if args.days is not None else None

    data = fetch_accounts(start_date=start_date)
    failed = response_problems(data)

    # A hosted database that scales to zero can drop the first connection while it wakes
    # (psycopg2: "server closed the connection unexpectedly"). Try again before giving up.
    for attempt in range(1, 4):
        conn = get_conn()
        try:
            upsert(conn, data)
            if args.recategorize:
                print(f"Recategorized {recategorize(conn)} transactions")
            if args.audit:
                review_rows(conn, "TRUE", label="stored")
            break
        except psycopg2.OperationalError as error:
            if attempt == 3:
                raise
            reason = str(error).strip().splitlines()[0]
            print(f"Database connection dropped ({reason}); retrying in {5 * attempt}s")
            time.sleep(5 * attempt)
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
