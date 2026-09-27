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
    """Spending in any of its groups (spending:groceries, spending:dining, ...), from cards
    or the bank account. Refunds carry the same group with a positive amount, so they net."""
    return txns["category"].str.startswith("spending:", na=False)


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
    label = category.split(":", 1)[1].replace("_", " ").capitalize()
    return {"Discretionary": "Unclassified card spending", "Card fees": "Card fees", "Fast food": "Fast food"}.get(
        label, label
    )


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
    ranked = (
        txns.groupby(column)["amount"]
        .agg(amount=lambda a: abs(a.sum()), count="size")
        .sort_values("amount", ascending=False)
        .reset_index()
        .rename(columns={column: "label"})
    )
    ranked["is_rest"] = False
    if keep is not None and len(ranked) > keep:
        rest = ranked.iloc[keep:]
        ranked = pd.concat(
            [
                ranked.iloc[:keep],
                pd.DataFrame(
                    {
                        "label": [f"{len(rest)} others"],
                        "amount": [rest["amount"].sum()],
                        "count": [rest["count"].sum()],
                        "is_rest": [True],
                    }
                ),
            ],
            ignore_index=True,
        )
    return ranked


# ---------- Date ranges for the slicers ----------
RANGE_PRESETS = ["This month", "Last month", "Last 3 months", "Year to date", "Custom"]


def date_range_for(preset, today, custom=None):
    """(start, end) as normalized Timestamps, inclusive, for a preset name."""
    today = pd.Timestamp(today).normalize()
    month_start = today.replace(day=1)
    if preset == "Last month":
        end = month_start - pd.Timedelta(days=1)
        return end.replace(day=1), end
    if preset == "Last 3 months":
        return (month_start - pd.DateOffset(months=2)).normalize(), today
    if preset == "Year to date":
        return today.replace(month=1, day=1), today
    if preset == "Custom" and custom and len(custom) == 2 and all(custom):
        start, end = (pd.Timestamp(d).normalize() for d in custom)
        return (start, end) if start <= end else (end, start)
    return month_start, today


def previous_range(start, end, today):
    """The comparison window: the same stretch of the month before when the range is a
    partial current month (so a half month is not compared with a whole one), otherwise
    the period of equal length immediately before."""
    today = pd.Timestamp(today).normalize()
    if start == today.replace(month=1, day=1) and end == today:
        # Year to date compares with the same stretch of the previous year.
        return start - pd.DateOffset(years=1), end - pd.DateOffset(years=1)
    if start == start.replace(day=1) and end == today and start.month == today.month and start.year == today.year:
        prev_start = (start - pd.DateOffset(months=1)).normalize()
        prev_end = prev_start + pd.Timedelta(days=min(end.day, prev_start.days_in_month) - 1)
        return prev_start, prev_end
    whole_months = start == start.replace(day=1) and end == end.to_period("M").to_timestamp(how="end").normalize()
    if whole_months:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        prev_end = start - pd.Timedelta(days=1)
        return (prev_end.replace(day=1) - pd.DateOffset(months=months - 1)).normalize(), prev_end
    length = end - start
    prev_end = start - pd.Timedelta(days=1)
    return prev_end - length, prev_end


def in_range(txns, start, end):
    return (txns["effective"] >= start) & (txns["effective"] <= end + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))


def monthly_totals(txns, last_month, months=6):
    """income, bills, spending and left_over per month for the `months` months ending at
    `last_month` (a Period), zero-filled, oldest first."""
    periods = pd.period_range(end=last_month, periods=months, freq="M")
    rows = []
    for period in periods:
        income, bills, spending = month_totals(txns[txns["month"] == period])
        rows.append(
            {
                "month": period,
                "income": income,
                "bills": bills,
                "spending": spending,
                "left_over": income - bills - spending,
            }
        )
    return pd.DataFrame(rows)


def describe_range(start, end):
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.strftime('%b %-d')}–{end.strftime('%-d, %Y')}"
        return f"{start.strftime('%b %-d')} – {end.strftime('%b %-d, %Y')}"
    return f"{start.strftime('%b %-d, %Y')} – {end.strftime('%b %-d, %Y')}"
