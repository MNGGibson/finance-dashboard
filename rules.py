"""The dashboard's accounting rules, as pure pandas functions so they can be tested.

Every frame here comes from finance_data.load_transactions(): columns posted, amount,
description, category, account_id, account_name, account_type.
"""
import pandas as pd

CARD_PAYMENT = "bill:debt_payment"
CASH_TYPES = ["checking", "savings"]
# Rent is due on the 1st but often leaves the bank this many days early.
EARLY_RENT_DAYS = 3


def is_card_payment(txns):
    return txns["category"] == CARD_PAYMENT


def is_bill(txns):
    """Fixed bills paid from cash. Card payments are tracked separately: they settle
    card spending that is already counted, so adding both would count dollars twice."""
    return txns["category"].str.startswith("bill:", na=False) & ~is_card_payment(txns)


def is_spending(txns):
    return txns["category"] == "spending:discretionary"


def is_transfer(txns):
    return txns["category"].str.startswith("transfer:", na=False)


def income_mask(txns):
    """Money arriving in a non-credit-card account that isn't a transfer. Positive amounts
    on credit cards are payments received, statement credits and points redemptions."""
    return (txns["amount"] > 0) & (txns["account_type"] != "credit_card") & ~is_transfer(txns)


def month_totals(txns):
    """(income, bills, spending) for a frame. Income - bills - spending is what is left."""
    income = txns.loc[income_mask(txns), "amount"].sum()
    bills = -txns.loc[is_bill(txns), "amount"].sum()
    spending = -txns.loc[is_spending(txns), "amount"].sum()
    return income, bills, spending


def effective_date(txns):
    """The date a transaction counts toward. Rent posted in the last EARLY_RENT_DAYS days of a
    month counts for the month it pays for; otherwise one month gets two rents and the next none."""
    posted = txns["posted"]
    early_rent = (txns["category"] == "bill:rent") & (posted.dt.days_in_month - posted.dt.day < EARLY_RENT_DAYS)
    next_month_start = (posted + pd.offsets.MonthBegin(1)).dt.normalize()
    return posted.where(~early_rent, next_month_start)


def category_label(category):
    """'bill:debt_payment' -> 'Debt payment'."""
    if pd.isna(category) or ":" not in category:
        return "Uncategorized"
    return category.split(":", 1)[1].replace("_", " ").capitalize()


def days_counted(period, today):
    """Full days in the month, or days elapsed so far if it's the current month."""
    if period == today.to_period("M"):
        return today.day
    return period.days_in_month


def net_worth_as_of(history, cutoff):
    """Net worth from the last sync run on or before `cutoff`: every account's balance from
    that one run, so the total is not a mix of dates. Returns (total, run_date) or (None, None)."""
    past = history[history["as_of"] <= cutoff]
    if past.empty:
        return None, None
    run = past["as_of"].max()
    return float(past.loc[past["as_of"] == run, "balance"].sum()), run


def rank_by(txns, column, keep=None):
    """Totals per value of `column`, largest first, with a tail folded into 'N others'."""
    ranked = (txns.groupby(column)["amount"].agg(amount=lambda a: abs(a.sum()), count="size")
              .sort_values("amount", ascending=False).reset_index().rename(columns={column: "label"}))
    ranked["is_rest"] = False
    if keep is not None and len(ranked) > keep:
        rest = ranked.iloc[keep:]
        ranked = pd.concat([ranked.iloc[:keep], pd.DataFrame({
            "label": [f"{len(rest)} others"], "amount": [rest["amount"].sum()],
            "count": [rest["count"].sum()], "is_rest": [True]})], ignore_index=True)
    return ranked
