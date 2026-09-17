"""Forward cash forecast: today's balance plus every expected paycheck and bill, day by day.

Pure pandas, no Streamlit, so it can be tested on its own. The approach follows the
balance-forecast reports in mature budgeting apps: recurring items are detected from
the bank feed, projected onto a calendar, and summed into a running balance whose
lowest point says how much cash is really free. Spending that has no schedule is
added as a flat daily amount so the line is not optimistic.
"""
import pandas as pd

# A payee with no payment in this many days is treated as ended (two monthly cycles).
ACTIVE_DAYS = 62
PAY_SCHEDULES = {52: "weekly", 26: "every two weeks", 24: "twice a month", 12: "monthly"}
CARD_PAYMENT = "bill:debt_payment"


def payee_key(descriptions):
    """Normalise bank descriptions to a payee. Banks vary the prefix over time
    ("ACH: X", "Direct Deposit: X", plain "X"), so keep what follows the last ": "."""
    return descriptions.fillna("").str.split(": ").str[-1].str.strip().str.upper()


def paychecks_per_year(dates):
    """Closest standard pay schedule to the median gap between deposits, or None."""
    gaps = pd.to_datetime(pd.Series(list(dates))).sort_values().diff().dt.days.dropna()
    if gaps.empty:
        return None
    return min(PAY_SCHEDULES, key=lambda n: abs(365.25 / n - gaps.median()))


def occurrences(last_date, step, today, horizon_end, limit=None):
    """Future dates an item repeats on, continuing its own rhythm from the last time it happened.

    Anchoring on the last real occurrence (rather than a fixed day of the month) keeps
    a bill that drifts, like rent posting on the 31st or the 3rd, close to reality.
    Steps are multiples from the anchor so month-end dates do not creep (31st -> 28th -> 28th).
    A missed occurrence is skipped, not back-filled.
    """
    dates, k = [], 1
    while last_date + step * k <= horizon_end:
        due = last_date + step * k
        if due > today:
            dates.append(due)
            if limit is not None and len(dates) >= limit:
                break
        k += 1
    return dates


def recurring_bills(cash_txns, today):
    """Monthly bills paid from cash: latest amount and date for each payee still active.

    Card payments are excluded here because they vary month to month; they are
    forecast separately from their recent average.
    """
    bills = cash_txns[
        cash_txns["category"].str.startswith("bill:", na=False)
        & (cash_txns["category"] != CARD_PAYMENT)
        & (cash_txns["posted"] >= today - pd.Timedelta(days=ACTIVE_DAYS))
    ].sort_values("posted", ascending=False)
    if bills.empty:
        return pd.DataFrame(columns=["label", "amount", "last_date"])
    bills = bills.assign(payee=payee_key(bills["description"]))
    latest = bills.groupby("payee").first().reset_index()
    return pd.DataFrame({
        "label": latest["category"].str.split(":").str[1].str.replace("_", " ").str.capitalize(),
        "amount": latest["amount"].astype(float),
        "last_date": latest["posted"].dt.normalize(),
    })


def card_payment_pattern(cash_txns, today, window_days=90):
    """Average monthly card payments from cash, and the date of the last main payment.

    Returns (monthly_amount, last_main_payment_date). Several cards are paid within a
    few days of each other, so they are forecast as one payment on the main card's date.
    """
    payments = cash_txns[
        (cash_txns["category"] == CARD_PAYMENT)
        & (cash_txns["posted"] >= today - pd.Timedelta(days=window_days))
    ]
    if payments.empty:
        return 0.0, None
    monthly = float(-payments["amount"].sum()) * 30.44 / window_days
    main = payments[-payments["amount"] >= 0.25 * monthly]
    last = (main if not main.empty else payments)["posted"].max().normalize()
    return monthly, last


def other_cash_spending(cash_txns, today, window_days=90):
    """Monthly cash spending with no schedule: uncategorised outflows (Zelle, debit card)."""
    other = cash_txns[
        cash_txns["category"].isna() & (cash_txns["amount"] < 0)
        & (cash_txns["posted"] >= today - pd.Timedelta(days=window_days))
    ]
    return float(-other["amount"].sum()) * 30.44 / window_days


def income_streams(cash_txns, today):
    """One row per active income payer: latest amount, last date, inferred schedule."""
    income = cash_txns[
        cash_txns["category"].str.startswith("income:", na=False)
        & (cash_txns["posted"] >= today - pd.Timedelta(days=ACTIVE_DAYS))
    ].sort_values("posted", ascending=False)
    if income.empty:
        return pd.DataFrame(columns=["payer", "category", "amount", "last_date", "per_year", "deposits"])
    income = income.assign(payer=payee_key(income["description"]))
    rows = []
    for payer, group in income.groupby("payer", sort=False):
        is_paycheck = group["category"].iloc[0] == "income:paycheck"
        rows.append({
            "payer": payer,
            "category": group["category"].iloc[0],
            # A paycheck is a fixed amount, so take the latest; gig payouts vary, so average.
            "amount": float(group["amount"].iloc[0] if is_paycheck else group["amount"].mean()),
            "last_date": group["posted"].max().normalize(),
            "per_year": paychecks_per_year(group["posted"]),
            "deposits": len(group),
        })
    return pd.DataFrame(rows)


def schedule_step(per_year):
    if per_year == 12:
        return pd.DateOffset(months=1)
    return pd.Timedelta(days=round(365.25 / per_year))


def project_balance(start_balance, events, daily_spend, today, days):
    """Running balance from today. `events` has date, label, amount (signed).

    Today's balance already reflects today, so events and daily spending start tomorrow.
    Returns (daily, events_with_balance).
    """
    index = pd.date_range(today, today + pd.Timedelta(days=days), freq="D")
    scheduled = events.groupby("date")["amount"].sum().reindex(index, fill_value=0.0)
    drift = pd.Series(-daily_spend, index=index)
    drift.iloc[0] = 0.0
    daily = pd.DataFrame({"date": index, "balance": start_balance + (scheduled + drift).cumsum().values})
    labels = events.groupby("date")["label"].agg(", ".join)
    daily["events"] = daily["date"].map(labels).fillna("")
    listed = events.sort_values(["date", "amount"]).merge(
        daily[["date", "balance"]].rename(columns={"balance": "balance_after"}), on="date", how="left")
    return daily, listed
