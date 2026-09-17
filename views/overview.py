"""Overview page: where things stand today, and income/spending for a selected month."""
import html
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import ui
from finance_data import cash_on_hand_for_month, income_mask, load_accounts, load_balance_history, load_transactions

FILTERS = ["All", "Cash", "Debt", "Income", "Bills", "Spending"]
CASH_TYPES = ["checking", "savings"]


def is_bill(txns):
    return txns["category"].str.startswith("bill:", na=False)


def is_spending(txns):
    return txns["category"] == "spending:discretionary"


def month_totals(txns):
    income = txns.loc[income_mask(txns), "amount"].sum()
    bills = -txns.loc[is_bill(txns), "amount"].sum()
    spending = -txns.loc[is_spending(txns), "amount"].sum()
    return income, bills, spending


def left_for_debt(txns):
    """Income minus living costs, before any debt payments.

    Debt payments are left out on purpose: a card payment settles spending that is
    already counted, so subtracting both would count the same dollars twice. This is
    the same quantity the Forecasting page calls net cash flow.
    """
    income, bills, spending = month_totals(txns)
    debt_payments = -txns.loc[txns["category"] == "bill:debt_payment", "amount"].sum()
    return income - (bills - debt_payments) - spending


def category_label(category):
    """'bill:debt_payment' -> 'Debt payment'."""
    if pd.isna(category) or ":" not in category:
        return "Uncategorized"
    return category.split(":", 1)[1].replace("_", " ").capitalize()


def days_counted(period):
    """Full days in the month, or days elapsed so far if it's the current month."""
    today = pd.Timestamp.today().normalize()
    if period == today.to_period("M"):
        return today.day
    return period.days_in_month


def net_worth_as_of(history, cutoff):
    """Net worth from the latest snapshot of each account on or before `cutoff`."""
    past = history[history["as_of"] <= cutoff]
    if past.empty:
        return None, None
    latest = past.sort_values("as_of").groupby("name").tail(1)
    return float(latest["balance"].sum()), latest["as_of"].max()


# ---------- Data ----------
accounts = load_accounts()
transactions = load_transactions(months=12)
transactions["month"] = transactions["posted"].dt.to_period("M")

today = pd.Timestamp.today().normalize()
available_months = sorted(transactions["month"].unique(), reverse=True)
month_labels = {m: m.strftime("%B %Y") for m in available_months}

# ---------- Header: title + the one filter row that scopes everything below ----------
title_col, month_col = st.columns([3, 1], vertical_alignment="bottom")
title_col.title("Overview")
selected_month = month_col.selectbox(
    "Month", options=available_months, format_func=lambda m: month_labels[m], index=0,
    label_visibility="collapsed",
)
month_name = month_labels[selected_month]
month_txns = transactions[transactions["month"] == selected_month]

# ---------- Hero: net worth, and what it is made of ----------
net_worth = accounts["last_balance"].sum()
assets = accounts.loc[accounts["last_balance"] > 0, "last_balance"].sum()
total_debt = -accounts.loc[accounts["last_balance"] < 0, "last_balance"].sum()

past_worth, past_date = net_worth_as_of(load_balance_history(), today - pd.Timedelta(days=30))
hero_note = (
    ui.delta_html(net_worth, past_worth, up_is_good=True, versus=past_date.strftime("%b %-d"))
    if past_worth is not None else "Trend appears once a month of daily syncs has built up"
)

cash_snapshot = cash_on_hand_for_month(selected_month, snapshot_day=15)
if cash_snapshot is not None:
    cash_text = f"<b>{ui.money(cash_snapshot[0])}</b> cash on hand, {cash_snapshot[1].strftime('%b %-d')}"
else:
    cash_text = f"No cash snapshot for {html.escape(month_name)}"

with st.container(border=True, key="card_hero"):
    hero_left, hero_right = st.columns([2, 3], vertical_alignment="center")
    hero_left.markdown(
        f'<div class="hero-label">Net worth</div><div class="hero-value">{ui.money(net_worth)}</div>'
        f'<div class="hero-sub">{hero_note}</div>',
        unsafe_allow_html=True,
    )
    total = max(assets + total_debt, 1)
    hero_right.markdown(
        f'<div class="meter">'
        f'<span style="width:{assets / total * 100:.1f}%;background:{ui.SERIES["blue"]}"></span>'
        f'<span style="width:{total_debt / total * 100:.1f}%;background:{ui.SERIES["orange"]}"></span></div>'
        f'<div class="legend">'
        f'<span><span class="swatch" style="background:{ui.SERIES["blue"]}"></span>Assets <b>{ui.money(assets)}</b></span>'
        f'<span><span class="swatch" style="background:{ui.SERIES["orange"]}"></span>Debt <b>{ui.money(total_debt)}</b></span>'
        f'<span>{cash_text}</span></div>',
        unsafe_allow_html=True,
    )

# ---------- This month, against the same stretch of last month ----------
prev_month = selected_month - 1
prev_txns = transactions[transactions["month"] == prev_month]
is_current_month = selected_month == today.to_period("M")
if is_current_month:
    # A partial month against a full one always looks like a win; compare like with like.
    prev_txns = prev_txns[prev_txns["posted"].dt.day <= today.day]
    versus = f"{prev_month.strftime('%b')} 1–{today.day}"
else:
    versus = prev_month.strftime("%B")
has_prev = not prev_txns.empty

income, bills, spending = month_totals(month_txns)
p_income, p_bills, p_spending = month_totals(prev_txns) if has_prev else (None, None, None)
left_over = left_for_debt(month_txns)
p_left_over = left_for_debt(prev_txns) if has_prev else None
per_day = spending / days_counted(selected_month)
p_per_day = p_spending / (today.day if is_current_month else prev_month.days_in_month) if has_prev else None

ui.section_label(month_name)
ui.tile_row([
    ui.stat_tile("Income", ui.money(income), ui.delta_html(income, p_income, True, versus)),
    ui.stat_tile("Bills", ui.money(bills), ui.delta_html(bills, p_bills, False, versus)),
    ui.stat_tile("Spending", ui.money(spending), ui.delta_html(spending, p_spending, False, versus)),
    ui.stat_tile("Left for debt and savings", ui.money(left_over), ui.delta_html(left_over, p_left_over, True, versus)),
    ui.stat_tile("Spending per day", ui.money(per_day, cents=True), ui.delta_html(per_day, p_per_day, False, versus)),
])

# ---------- Cross-filter: one control, every visual below follows it ----------
st.write("")
choice = st.segmented_control("Show", FILTERS, default="All", key="overview_filter") or "All"

filtered_txns = month_txns
filtered_accounts = accounts
if choice == "Income":
    filtered_txns = month_txns[income_mask(month_txns)]
elif choice == "Bills":
    filtered_txns = month_txns[is_bill(month_txns)]
elif choice == "Spending":
    filtered_txns = month_txns[is_spending(month_txns)]
elif choice == "Cash":
    filtered_txns = month_txns[month_txns["account_type"].isin(CASH_TYPES)]
    filtered_accounts = accounts[accounts["account_type"].isin(CASH_TYPES)]
elif choice == "Debt":
    filtered_txns = month_txns[month_txns["account_type"] == "credit_card"]
    filtered_accounts = accounts[accounts["account_type"] == "credit_card"]
if choice in ("Income", "Bills", "Spending"):
    filtered_accounts = accounts[accounts["name"].isin(filtered_txns["account_name"].unique())]

chart_col, accounts_col = st.columns([3, 2])

with chart_col, st.container(border=True, key="card_categories"):
    if choice == "Income":
        heading, cat_subset = "Income by source", filtered_txns
    else:
        heading = {"Bills": "Bills by type", "Spending": "Spending by category"}.get(choice, "Where the money went")
        # Transfers (points redemptions and the like) net to zero, so they are not outflows.
        cat_subset = filtered_txns[(filtered_txns["amount"] < 0)
                                   & ~filtered_txns["category"].str.startswith("transfer:", na=False)]
    by_cat = (
        cat_subset.assign(label=cat_subset["category"].map(category_label))
        .groupby("label")["amount"].sum().abs().sort_values(ascending=False).reset_index()
    )
    st.subheader(heading)
    if by_cat.empty:
        st.caption("Nothing to show for this view.")
    else:
        st.caption(f"{ui.money(by_cat['amount'].sum())} across {len(by_cat)} categories, {month_name}")
        base = alt.Chart(by_cat).encode(
            y=alt.Y("label:N", sort="-x", title=None,
                    axis=alt.Axis(ticks=False, domain=False, labelLimit=170, labelFontSize=13,
                                  labelColor=ui.INK_SECONDARY, labelPadding=10)),
            x=alt.X("amount:Q", axis=None, scale=alt.Scale(domain=[0, by_cat["amount"].max() * 1.2])),
            tooltip=[alt.Tooltip("label:N", title="Category"), alt.Tooltip("amount:Q", title="Amount", format="$,.2f")],
        )
        bars = base.mark_bar(size=18, cornerRadiusEnd=4, color=ui.ACCENT)
        values = base.mark_text(align="left", dx=7, fontSize=12, color=ui.INK_SECONDARY).encode(
            text=alt.Text("amount:Q", format="$,.0f"))
        ui.show_chart(bars + values, height=34 * len(by_cat) + 8)

with chart_col, st.container(border=True, key="card_flow"):
    st.subheader("Monthly cash flow")
    st.caption(f"{month_name} highlighted")
    recent = [m for m in sorted(available_months)][-6:]
    flow_rows = []
    for m in recent:
        m_income, m_bills, m_spending = month_totals(transactions[transactions["month"] == m])
        for kind, amount in (("Income", m_income), ("Bills", m_bills), ("Spending", m_spending)):
            flow_rows.append({"month": m.strftime("%b"), "kind": kind, "amount": amount, "selected": m == selected_month})
    flow = pd.DataFrame(flow_rows)
    kinds = ["Income", "Bills", "Spending"]
    flow_chart = alt.Chart(flow).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("month:N", sort=[m.strftime("%b") for m in recent], title=None,
                axis=alt.Axis(labelAngle=0, ticks=False), scale=alt.Scale(paddingInner=0.25)),
        xOffset=alt.XOffset("kind:N", sort=kinds, scale=alt.Scale(paddingInner=0.15)),
        y=alt.Y("amount:Q", title=None, axis=alt.Axis(format="$~s", tickCount=4, domain=False, ticks=False)),
        color=alt.Color("kind:N", sort=kinds, scale=alt.Scale(
            domain=kinds, range=[ui.SERIES["aqua"], ui.SERIES["orange"], ui.SERIES["blue"]])),
        opacity=alt.condition(alt.datum.selected, alt.value(1), alt.value(0.4)),
        tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("kind:N", title="Type"),
                 alt.Tooltip("amount:Q", title="Amount", format="$,.0f")],
    )
    ui.show_chart(flow_chart, height=250)

with accounts_col, st.container(border=True, key="card_accounts"):
    st.subheader("Accounts")
    st.caption(f"{ui.money(filtered_accounts['last_balance'].sum())} across {len(filtered_accounts)} accounts")
    groups = [
        ("Cash", filtered_accounts[filtered_accounts["account_type"].isin(CASH_TYPES)]),
        ("Credit cards", filtered_accounts[filtered_accounts["account_type"] == "credit_card"]),
        ("Other", filtered_accounts[~filtered_accounts["account_type"].isin(CASH_TYPES + ["credit_card"])]),
    ]
    rows = []
    for group_name, group in groups:
        if group.empty:
            continue
        rows.append(
            f'<div class="acct-group"><span>{group_name}</span>'
            f'<span>{ui.money(group["last_balance"].sum())}</span></div>'
        )
        for _, acct in group.sort_values("last_balance", ascending=False).iterrows():
            badge = ""
            if pd.notna(acct["promo_apr_expires"]):
                days_left = (acct["promo_apr_expires"] - date.today()).days
                if days_left >= 0:
                    badge = f'<span class="badge">0% APR ends in {days_left} days</span>'
            rows.append(
                f'<div class="acct"><div style="min-width:0"><div class="acct-name">{html.escape(acct["name"])}{badge}</div>'
                f'<div class="acct-org">{html.escape(acct["org_name"] or "")}</div></div>'
                f'<div class="acct-bal">{ui.money(acct["last_balance"], cents=True)}</div></div>'
            )
    st.markdown("".join(rows), unsafe_allow_html=True)

# ---------- Trends (always card spending and whole months; not narrowed by the filter) ----------
ui.section_label("Trends")
pace_col, daily_col = st.columns(2)

spend_all = transactions[is_spending(transactions)]

with pace_col, st.container(border=True, key="card_pace"):
    st.subheader("Spending pace")
    st.caption("Card spending added up day by day")

    def cumulative(period, through_day):
        daily = (-spend_all[spend_all["month"] == period].set_index("posted")["amount"]).groupby(lambda d: d.day).sum()
        return daily.reindex(range(1, through_day + 1), fill_value=0).cumsum()

    this_name, prev_name = selected_month.strftime("%B"), prev_month.strftime("%B")
    series = [pd.DataFrame({"day": s.index, "spent": s.values, "month": name}) for s, name in [
        (cumulative(selected_month, days_counted(selected_month)), this_name),
        (cumulative(prev_month, prev_month.days_in_month), prev_name),
    ] if s.iloc[-1] > 0]
    if not series:
        st.caption("No card spending in these months.")
    else:
        pace = pd.concat(series)
        colour = alt.Color("month:N", sort=[this_name, prev_name],
                           scale=alt.Scale(domain=[this_name, prev_name], range=[ui.ACCENT, ui.DEEMPHASIS]))
        lines = alt.Chart(pace).mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round").encode(
            x=alt.X("day:Q", title="Day of month", scale=alt.Scale(domain=[1, 31], nice=False), axis=alt.Axis(grid=False, values=[1, 5, 10, 15, 20, 25, 31])),
            y=alt.Y("spent:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=4, domain=False, ticks=False)),
            color=colour,
            tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("day:Q", title="Day"),
                     alt.Tooltip("spent:Q", title="Spent so far", format="$,.0f")],
        )
        ends = pace.groupby("month").tail(1)
        dots = alt.Chart(ends).mark_point(size=70, filled=True, opacity=1, stroke=ui.SURFACE, strokeWidth=2).encode(
            x="day:Q", y="spent:Q", color=colour)
        ui.show_chart(lines + dots, height=230)

with daily_col, st.container(border=True, key="card_daily"):
    st.subheader("Spending per day")
    st.caption("Monthly average, card spending")
    monthly_spend = (-spend_all.groupby("month")["amount"].sum())
    daily = pd.DataFrame({
        "month": [m.strftime("%b") for m in monthly_spend.index],
        "per_day": [monthly_spend[m] / days_counted(m) for m in monthly_spend.index],
        "selected": [m == selected_month for m in monthly_spend.index],
    }).tail(6)
    daily_base = alt.Chart(daily).encode(
        x=alt.X("month:N", sort=list(daily["month"]), title=None, axis=alt.Axis(labelAngle=0, ticks=False)),
        y=alt.Y("per_day:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=4, domain=False, ticks=False)),
        tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("per_day:Q", title="Per day", format="$,.2f")],
    )
    columns = daily_base.mark_bar(size=22, cornerRadiusEnd=4).encode(
        color=alt.condition(alt.datum.selected, alt.value(ui.ACCENT), alt.value(ui.DEEMPHASIS)))
    cap = daily_base.transform_filter(alt.datum.selected).mark_text(dy=-8, fontSize=12, color=ui.INK).encode(
        text=alt.Text("per_day:Q", format="$,.0f"))
    ui.show_chart(columns + cap, height=230)

# ---------- Transactions ----------
ui.section_label("Transactions")
with st.container(border=True, key="card_transactions"):
    view_name = "All activity" if choice == "All" else choice
    st.subheader(f"{view_name}, {month_name}")
    st.caption(f"{len(filtered_txns)} transactions, net {ui.money(filtered_txns['amount'].sum(), cents=True)}")
    table = filtered_txns.sort_values("posted", ascending=False).assign(
        category=lambda d: d["category"].map(category_label))
    st.dataframe(
        table[["posted", "description", "category", "account_name", "amount"]],
        hide_index=True, use_container_width=True, height=420,
        column_config={
            "posted": st.column_config.DateColumn("Date", format="MMM D", width="small"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "category": st.column_config.TextColumn("Category", width="medium"),
            "account_name": st.column_config.TextColumn("Account", width="medium"),
            "amount": st.column_config.NumberColumn("Amount", format="dollar", width="small"),
        },
    )

st.caption("Data refreshes every 5 minutes from the local Postgres database, synced daily via scripts/sync.py.")
