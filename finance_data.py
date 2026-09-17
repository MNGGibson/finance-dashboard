"""Shared Postgres access for the Streamlit app and its pages."""
import os
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "finance"),
        user=os.environ.get("POSTGRES_USER", "finance"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


@st.cache_data(ttl=300)
def load_accounts():
    conn = get_conn()
    df = pd.read_sql(
        "SELECT id, name, org_name, account_type, last_balance, apr, promo_apr_expires, post_promo_apr "
        "FROM accounts", conn,
    )
    conn.close()
    return df


@st.cache_data(ttl=300)
def load_transactions(months=12):
    conn = get_conn()
    df = pd.read_sql(
        "SELECT t.posted, t.amount, t.description, t.category, t.pending, "
        "a.name AS account_name, a.account_type "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.posted >= now() - (%(months)s || ' months')::interval "
        "ORDER BY t.posted DESC",
        conn, params={"months": months},
    )
    conn.close()
    df["posted"] = pd.to_datetime(df["posted"]).dt.tz_localize(None)
    return df


def income_mask(txns):
    """Boolean mask of the rows in a load_transactions() frame that count as income.

    The single definition of income for the app: money arriving in a non-credit-card
    account that isn't a transfer. Positive amounts on credit cards are payments
    received, statement credits and points redemptions -- not income.
    """
    return (
        (txns["amount"] > 0)
        & (txns["account_type"] != "credit_card")
        & ~txns["category"].str.startswith("transfer:", na=False)
    )


@st.cache_data(ttl=300)
def load_balance_history():
    conn = get_conn()
    df = pd.read_sql(
        "SELECT bs.as_of, bs.balance, a.name, a.account_type "
        "FROM balance_snapshots bs JOIN accounts a ON a.id = bs.account_id "
        "ORDER BY bs.as_of",
        conn,
    )
    conn.close()
    df["as_of"] = pd.to_datetime(df["as_of"]).dt.tz_localize(None)
    return df


def cash_on_hand_for_month(month_period, snapshot_day=15):
    """Cash on hand (checking + savings) as of the balance snapshot closest to
    the given day of the month. Daily syncs (scripts/sync.py, run via launchd)
    naturally produce a snapshot on or near that day each month, so no separate
    monthly job is needed -- this just picks it out. Returns (amount, actual_date)
    or None if no snapshot exists within that month yet.
    """
    history = load_balance_history()
    cash_hist = history[history["account_type"].isin(["checking", "savings"])]

    month_start = month_period.to_timestamp()
    month_end = month_start + pd.offsets.MonthEnd(1)
    in_month = cash_hist[(cash_hist["as_of"] >= month_start) & (cash_hist["as_of"] <= month_end)]
    if in_month.empty:
        return None

    target_date = pd.Timestamp(month_period.year, month_period.month, min(snapshot_day, month_end.day))
    in_month = in_month.copy()
    in_month["dist"] = (in_month["as_of"] - target_date).abs()
    closest_date = in_month.loc[in_month["dist"].idxmin(), "as_of"]
    day_snapshot = in_month[in_month["as_of"] == closest_date]
    return float(day_snapshot["balance"].sum()), closest_date
