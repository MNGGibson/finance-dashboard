"""Forecasting page: debt payoff simulator + adjustable planning levers.

Run with: .venv/bin/streamlit run app.py
"""
from datetime import date

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from finance_data import load_accounts, load_goals, load_monthly_discretionary, load_recent_by_category

st.set_page_config(page_title="Finance command center", layout="wide")

accounts = load_accounts()
net_worth = accounts["last_balance"].sum()
total_debt = -accounts.loc[accounts["last_balance"] < 0, "last_balance"].sum()

st.title("Forecasting")

# ---------- Sidebar: editable assumptions, pre-filled from live data ----------
st.sidebar.header("Assumptions")
st.sidebar.caption("Pre-filled from synced data. Adjust anything that looks stale.")

paycheck_recent = load_recent_by_category("income:paycheck", 1)
paycheck_default = float(paycheck_recent["amount"].iloc[0]) if not paycheck_recent.empty else 0.0
paycheck_amount = st.sidebar.number_input("Paycheck amount", value=round(paycheck_default, 2), step=25.0)
paycheck_per_year = st.sidebar.number_input("Paychecks per year", value=26, step=1)

uber_recent = load_recent_by_category("income:uber", 10)
uber_default = float(uber_recent["amount"].mean()) if not uber_recent.empty else 0.0
uber_avg = st.sidebar.number_input("Side-gig avg per payout", value=round(uber_default, 2), step=5.0)
uber_per_year = st.sidebar.number_input("Side-gig payouts per year", value=52, step=1)

st.sidebar.markdown("---")
rent = st.sidebar.number_input("Rent", value=0.0, step=25.0)
family_payment = st.sidebar.number_input("Family payment", value=0.0, step=10.0)
car_loan = st.sidebar.number_input("Car loan", value=0.0, step=10.0)
student_loan = st.sidebar.number_input("Student loan", value=0.0, step=10.0)

st.sidebar.markdown("---")
disc_monthly = load_monthly_discretionary()
disc_monthly["month"] = pd.to_datetime(disc_monthly["month"]).dt.tz_localize(None)
this_month = pd.Timestamp.today().to_period("M").to_timestamp()
disc_full_months = disc_monthly[disc_monthly["month"] < this_month]
disc_default = float(disc_full_months["spend"].tail(2).mean()) if len(disc_full_months) >= 1 else 0.0
discretionary = st.sidebar.number_input("Discretionary spending (card)", value=round(disc_default, 2), step=50.0)
st.sidebar.caption("Excludes the current in-progress month, which would understate this.")

monthly_income = paycheck_amount * paycheck_per_year / 12 + uber_avg * uber_per_year / 12
fixed_obligations = rent + family_payment + car_loan + student_loan
base_net = monthly_income - fixed_obligations - discretionary

# ---------- KPI row ----------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Net worth", f"${net_worth:,.0f}")
c2.metric("Total debt", f"${total_debt:,.0f}")
c3.metric("Monthly income", f"${monthly_income:,.0f}")
c4.metric("Net cash flow", f"${base_net:,.0f}", delta=f"{'surplus' if base_net >= 0 else 'deficit'}")

# Whichever account has a promotional APR ending soonest -- generic across any
# balance-transfer or intro-APR card, not tied to a specific issuer.
promo_accounts = accounts[accounts["promo_apr_expires"].notna()].copy()
if not promo_accounts.empty:
    promo_accounts["days_left"] = promo_accounts["promo_apr_expires"].apply(lambda d: (d - date.today()).days)
    next_promo = promo_accounts.sort_values("days_left").iloc[0]
    c5.metric(f"{next_promo['name']} 0% ends", f"{next_promo['days_left']} days")
else:
    c5.metric("Promo APR deadline", "n/a")

st.markdown("---")

# ---------- Debt focus + levers ----------
debt_accounts = accounts[accounts["account_type"] == "credit_card"].copy()
debt_accounts["has_deadline"] = debt_accounts["promo_apr_expires"].notna()
debt_accounts = debt_accounts.sort_values(["has_deadline", "last_balance"], ascending=[False, True])
debt_options = {
    f"{row['name']} — ${-row['last_balance']:,.0f}": row["id"]
    for _, row in debt_accounts.iterrows()
    if row["last_balance"] < 0
}
left, right = st.columns([1, 2])
with left:
    focus_label = st.selectbox("Focus payoff on", list(debt_options.keys()))
    focus_id = debt_options[focus_label]
    focus_row = accounts[accounts["id"] == focus_id].iloc[0]
    focus_balance = -focus_row["last_balance"]
    focus_deadline = focus_row["promo_apr_expires"] if pd.notna(focus_row["promo_apr_expires"]) else None

    st.subheader("Levers")
    cut = st.slider("Cut discretionary spending ($/mo)", 0, 2000, 0, step=25)
    side = st.slider("More side income ($/mo)", 0, 1500, 0, step=25)
    raise_ = st.slider("Raise / new job ($/mo)", 0, 1500, 0, step=25)

    toward_debt = max(0.0, base_net + cut + side + raise_)
    st.metric("Toward selected debt", f"${toward_debt:,.0f}/mo")

with right:
    months = []
    balance = focus_balance
    m = 0
    history = [balance]
    if toward_debt > 0:
        while balance > 0.5 and m < 240:
            m += 1
            balance = max(0.0, balance - toward_debt)
            history.append(balance)
        payoff_date = pd.Timestamp.today() + pd.DateOffset(months=m)
    else:
        payoff_date = None

    fig, ax = plt.subplots(figsize=(7, 3.5))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    ax.plot(range(len(history)), history, color="#0F6E56" if toward_debt > 0 else "#E24B4A", linewidth=2)
    if focus_deadline:
        deadline_month = (focus_deadline.year - date.today().year) * 12 + (focus_deadline.month - date.today().month)
        if 0 <= deadline_month <= len(history) + 12:
            ax.axvline(deadline_month, color="#888780", linestyle="--", linewidth=1)
            ax.text(deadline_month, max(history) * 0.95, " deadline", fontsize=9, color="#888780")
    ax.set_xlabel("Months from now")
    ax.set_ylabel("Balance ($)")
    ax.spines[["top", "right"]].set_visible(False)
    st.pyplot(fig, use_container_width=True)

    if payoff_date is not None:
        st.write(f"**Paid off by:** {payoff_date.strftime('%b %Y')}")
        if focus_deadline is not None:
            days_margin = (focus_deadline - payoff_date.date()).days
            if days_margin >= 0:
                st.success(f"{days_margin} days ahead of the deadline")
            else:
                st.error(f"{-days_margin} days past the deadline")
    else:
        st.write("**Paid off by:** never at this rate")

st.markdown("---")

# ---------- Goals ----------
st.subheader("Savings goals")
goals = load_goals()
if goals.empty:
    st.caption("No goals yet — add one with `python scripts/add_goal.py \"Name\" amount --account <id>`.")
else:
    for _, g in goals.iterrows():
        progress = (g["last_balance"] or 0) - g["starting_amount"]
        pct = max(0.0, min(1.0, progress / g["target_amount"])) if g["target_amount"] else 0
        st.write(f"{g['name']}: ${progress:,.0f} / ${g['target_amount']:,.0f}")
        st.progress(pct)

st.caption("Data refreshes every 5 minutes from the local Postgres database, synced daily via scripts/sync.py.")
