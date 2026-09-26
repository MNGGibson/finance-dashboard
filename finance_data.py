"""Cached data loaders for the Streamlit app."""

import pandas as pd
import streamlit as st

from db import query, to_local_naive
from merchants import add_merchants
from rules import income_mask  # noqa: F401  (re-exported: the app's income definition lives in rules)


@st.cache_data(ttl=300)
def load_accounts():
    """Accounts with their latest balance. `updated_at` is when the last sync touched them."""
    df = query(
        "SELECT id, name, org_name, account_type, last_balance, apr, promo_apr_expires, post_promo_apr, updated_at "
        "FROM accounts"
    )
    df["updated_at"] = to_local_naive(df["updated_at"])
    return df


@st.cache_data(ttl=300)
def load_transactions(months=12):
    """Transactions with their account, dated in the local zone, plus a cleaned merchant
    name. Merchants are derived here, once per load, rather than on every rerun."""
    df = query(
        "SELECT t.posted, t.amount, t.description, t.category, t.pending, "
        "a.id AS account_id, a.name AS account_name, a.account_type "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.posted >= now() - (%(months)s || ' months')::interval "
        "ORDER BY t.posted DESC",
        {"months": months},
    )
    df["posted"] = to_local_naive(df["posted"])
    return add_merchants(df, df["description"])


@st.cache_data(ttl=300)
def load_balance_history():
    df = query(
        "SELECT bs.as_of, bs.balance, a.id AS account_id, a.name, a.account_type "
        "FROM balance_snapshots bs JOIN accounts a ON a.id = bs.account_id "
        "ORDER BY bs.as_of"
    )
    df["as_of"] = to_local_naive(df["as_of"])
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
