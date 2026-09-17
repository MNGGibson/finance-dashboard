"""Forecasting page: debt payoff simulator + adjustable planning levers.

Run with: .venv/bin/streamlit run app.py
"""
import html
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import ui
from finance_data import load_accounts, load_goals, load_monthly_discretionary, load_recent_by_category


# Used when the current employer has too few deposits on record to measure a pay cycle.
# Weekly matches the current pay schedule; change it if that stops being true.
FALLBACK_PAYCHECKS_PER_YEAR = 52
PAY_SCHEDULES = {52: "weekly", 26: "every two weeks", 24: "twice a month", 12: "monthly"}


def infer_pay_frequency(paychecks):
    """Paychecks per year for the employer behind the most recent paycheck.

    `paychecks` is newest-first with `posted` and `description`. Only deposits from the
    same payer as the latest one are used, so a job change switches the schedule as soon
    as the new employer's first deposit lands rather than blending the two.
    """
    if paychecks.empty:
        return FALLBACK_PAYCHECKS_PER_YEAR, "No paychecks synced yet. Assuming weekly."
    # Banks prefix the payer differently over time ("ACH: X", "Direct Deposit: X", "X").
    payer = paychecks["description"].fillna("").str.split(": ").str[-1].str.strip().str.upper()
    same_payer = paychecks[payer == payer.iloc[0]]
    name = payer.iloc[0]
    if len(same_payer) < 2:
        return FALLBACK_PAYCHECKS_PER_YEAR, f"Only one deposit from {name} so far. Assuming weekly."
    gap_days = pd.to_datetime(same_payer["posted"]).sort_values().diff().dt.days.dropna().median()
    per_year = min(PAY_SCHEDULES, key=lambda n: abs(365.25 / n - gap_days))
    return per_year, f"{name} pays {PAY_SCHEDULES[per_year]}, based on {len(same_payer)} deposits."


# A payee with no payment in this many days is treated as ended (two monthly cycles).
BILL_ACTIVE_DAYS = 62


def estimate_monthly_bill(category):
    """Monthly cost of a fixed bill: the latest payment to each payee still being paid.

    Calendar-month totals mislead for these bills. Rent posts on either side of a month
    boundary, and one-off charges or a doubled payment would skew an average. Each payee
    is assumed to bill monthly, which holds for rent, loans and the family payment.
    """
    txns = load_recent_by_category(category, 24)
    if txns.empty:
        return 0.0
    posted = pd.to_datetime(txns["posted"], utc=True).dt.tz_localize(None)
    txns = txns[posted >= pd.Timestamp.today() - pd.Timedelta(days=BILL_ACTIVE_DAYS)]
    # Same payee normalisation as paychecks: banks vary the prefix ("ACH: X", "Zelle: X").
    payee = txns["description"].fillna("").str.split(": ").str[-1].str.strip().str.upper()
    latest_per_payee = txns.groupby(payee)["amount"].first()  # frame is newest-first
    return float(-latest_per_payee.sum())


accounts = load_accounts()
net_worth = accounts["last_balance"].sum()
total_debt = -accounts.loc[accounts["last_balance"] < 0, "last_balance"].sum()

st.title("Forecasting")

# ---------- Sidebar: editable assumptions, pre-filled from live data ----------
st.sidebar.header("Assumptions")
st.sidebar.caption("Pre-filled from synced data. Adjust anything that looks stale.")

paycheck_recent = load_recent_by_category("income:paycheck", 12)
paycheck_default = float(paycheck_recent["amount"].iloc[0]) if not paycheck_recent.empty else 0.0
paycheck_amount = st.sidebar.number_input("Paycheck amount", value=round(paycheck_default, 2), step=25.0)
frequency_default, frequency_note = infer_pay_frequency(paycheck_recent)
paycheck_per_year = st.sidebar.number_input("Paychecks per year", value=frequency_default, step=1)
st.sidebar.caption(frequency_note)

uber_recent = load_recent_by_category("income:uber", 10)
uber_default = float(uber_recent["amount"].mean()) if not uber_recent.empty else 0.0
uber_avg = st.sidebar.number_input("Side-gig avg per payout", value=round(uber_default, 2), step=5.0)
uber_per_year = st.sidebar.number_input("Side-gig payouts per year", value=52, step=1)

st.sidebar.markdown("---")
rent = st.sidebar.number_input("Rent", value=round(estimate_monthly_bill("bill:rent"), 2), step=25.0)
family_payment = st.sidebar.number_input("Family payment", value=round(estimate_monthly_bill("bill:family"), 2), step=10.0)
car_loan = st.sidebar.number_input("Car loan", value=round(estimate_monthly_bill("bill:car_loan"), 2), step=10.0)
student_loan = st.sidebar.number_input("Student loan", value=round(estimate_monthly_bill("bill:student_loan"), 2), step=10.0)
st.sidebar.caption(f"Each is the latest payment to every payee paid in the last {BILL_ACTIVE_DAYS} days.")

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

# ---------- Headline tiles ----------
# Whichever account has a promotional APR ending soonest -- generic across any
# balance-transfer or intro-APR card, not tied to a specific issuer.
promo_accounts = accounts[accounts["promo_apr_expires"].notna()].copy()
if not promo_accounts.empty:
    promo_accounts["days_left"] = promo_accounts["promo_apr_expires"].apply(lambda d: (d - date.today()).days)
    next_promo = promo_accounts.sort_values("days_left").iloc[0]
    promo_tile = ui.stat_tile(
        "0% APR ends", f"{next_promo['days_left']} days",
        f"{html.escape(next_promo['name'])}, {next_promo['promo_apr_expires'].strftime('%b %-d')}",
    )
else:
    promo_tile = ui.stat_tile("0% APR ends", "n/a", "No promotional rate on file")

flow_class, flow_word = ("good", "▲ Surplus") if base_net >= 0 else ("bad", "▼ Deficit")
ui.tile_row([
    ui.stat_tile("Monthly income", ui.money(monthly_income), "Paychecks plus side gig"),
    ui.stat_tile("Fixed bills", ui.money(fixed_obligations), "Rent, loans and family"),
    ui.stat_tile("Card spending", ui.money(discretionary), "2-month average"),
    ui.stat_tile("Net cash flow", ui.money(base_net), f'<span class="delta {flow_class}">{flow_word}</span> each month'),
    ui.stat_tile("Total debt", ui.money(total_debt), f"Net worth {ui.money(net_worth)}"),
    promo_tile,
], min_width=150)

# ---------- Debt focus + levers ----------
ui.section_label("Debt payoff")
debt_accounts = accounts[accounts["account_type"] == "credit_card"].copy()
debt_accounts["has_deadline"] = debt_accounts["promo_apr_expires"].notna()
debt_accounts = debt_accounts.sort_values(["has_deadline", "last_balance"], ascending=[False, True])
debt_options = {
    f"{row['name']} — ${-row['last_balance']:,.0f}": row["id"]
    for _, row in debt_accounts.iterrows()
    if row["last_balance"] < 0
}
left, right = st.columns([1, 2])
with left, st.container(border=True, key="card_levers"):
    focus_label = st.selectbox("Focus payoff on", list(debt_options.keys()))
    focus_id = debt_options[focus_label]
    focus_row = accounts[accounts["id"] == focus_id].iloc[0]
    focus_balance = -focus_row["last_balance"]
    focus_deadline = focus_row["promo_apr_expires"] if pd.notna(focus_row["promo_apr_expires"]) else None

    st.subheader("Levers")
    cut = st.slider("Cut card spending ($/mo)", 0, 2000, 0, step=25)
    side = st.slider("More side income ($/mo)", 0, 1500, 0, step=25)
    raise_ = st.slider("Raise / new job ($/mo)", 0, 1500, 0, step=25)

    toward_debt = max(0.0, base_net + cut + side + raise_)
    st.markdown(
        f'<div class="hero-label" style="margin-top:10px">Toward this debt</div>'
        f'<div class="tile-value">{ui.money(toward_debt)}'
        f'<span style="font-size:0.85rem;font-weight:400;color:{ui.INK_MUTED}"> per month</span></div>',
        unsafe_allow_html=True,
    )

with right, st.container(border=True, key="card_payoff"):
    history = [focus_balance]
    if toward_debt > 0:
        while history[-1] > 0.5 and len(history) <= 240:
            history.append(max(0.0, history[-1] - toward_debt))
        payoff_date = pd.Timestamp.today() + pd.DateOffset(months=len(history) - 1)
    else:
        payoff_date = None

    deadline_month = None
    if focus_deadline:
        deadline_month = (focus_deadline.year - date.today().year) * 12 + (focus_deadline.month - date.today().month)

    # Headline and status first: the chart supports the answer, it is not the answer.
    st.subheader(f"Paying off {focus_row['name']}")
    if payoff_date is None:
        st.markdown('<div class="status"><span class="bad">✕ Never at this rate.</span> '
                    'Nothing is left over to put toward it.</div>', unsafe_allow_html=True)
    else:
        status = f"Paid off by <b style=\"color:{ui.INK}\">{payoff_date.strftime('%B %Y')}</b>"
        if focus_deadline is not None:
            days_margin = (focus_deadline - payoff_date.date()).days
            if days_margin >= 0:
                status += f' <span class="good">✓ {days_margin} days ahead of the 0% deadline</span>'
            else:
                status += f' <span class="bad">✕ {-days_margin} days past the 0% deadline</span>'
        st.markdown(f'<div class="status">{status}</div>', unsafe_allow_html=True)

    months_shown = max(len(history) - 1, deadline_month or 0, 6)
    balance_path = pd.DataFrame({
        "month": range(len(history)),
        "balance": history,
        "date": [(pd.Timestamp.today() + pd.DateOffset(months=i)).strftime("%b %Y") for i in range(len(history))],
    })
    x = alt.X("month:Q", title="Months from now", scale=alt.Scale(domain=[0, months_shown], nice=False),
              axis=alt.Axis(grid=False, tickMinStep=1, tickCount=8))
    y = alt.Y("balance:Q", title=None, scale=alt.Scale(domain=[0, focus_balance * 1.08], nice=False),
              axis=alt.Axis(format="$,.0f", tickCount=4, domain=False, ticks=False))
    tooltip = [alt.Tooltip("date:N", title="Month"), alt.Tooltip("balance:Q", title="Balance left", format="$,.0f")]
    path = alt.Chart(balance_path)
    layers = [
        path.mark_area(color=ui.ACCENT, opacity=0.10).encode(x=x, y=y),
        path.mark_line(color=ui.ACCENT, strokeWidth=2, strokeJoin="round").encode(x=x, y=y, tooltip=tooltip),
        path.mark_point(size=500, opacity=0).encode(x=x, y=y, tooltip=tooltip),  # generous hover targets
        alt.Chart(balance_path.tail(1)).mark_point(
            size=80, filled=True, opacity=1, color=ui.ACCENT, stroke=ui.SURFACE, strokeWidth=2).encode(x=x, y=y),
    ]
    if deadline_month is not None and 0 <= deadline_month <= months_shown:
        mark = pd.DataFrame({"month": [deadline_month], "label": ["0% APR ends"]})
        layers.append(alt.Chart(mark).mark_rule(color=ui.WARNING, strokeWidth=1.5).encode(x="month:Q"))
        layers.append(alt.Chart(mark).mark_text(
            align="right" if deadline_month > months_shown * 0.75 else "left",
            dx=-6 if deadline_month > months_shown * 0.75 else 6,
            baseline="top", fontSize=12, color=ui.INK_SECONDARY,
        ).encode(x="month:Q", y=alt.value(4), text="label:N"))
    ui.show_chart(alt.layer(*layers), height=300)

# ---------- Goals ----------
ui.section_label("Savings goals")
goals = load_goals()
with st.container(border=True, key="card_goals"):
    if goals.empty:
        st.caption("No goals yet. Add one with `python scripts/add_goal.py \"Name\" amount --account <id>`.")
    else:
        for _, g in goals.iterrows():
            progress = (g["last_balance"] or 0) - g["starting_amount"]
            pct = max(0.0, min(1.0, progress / g["target_amount"])) if g["target_amount"] else 0
            st.write(f"{g['name']}: {ui.money(progress)} of {ui.money(g['target_amount'])}")
            st.progress(pct)

st.caption("Data refreshes every 5 minutes from the local Postgres database, synced daily via scripts/sync.py.")
