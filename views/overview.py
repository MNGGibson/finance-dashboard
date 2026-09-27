"""The dashboard: slicers at the top, four totals, charts that select, and the transactions.

Every visual obeys the slicers (date range, accounts, categories, merchant search). Clicking
a bar narrows what sits below it, clicking it again deselects, and "Clear" resets. State
lives in st.session_state under the keys named here so chart clicks can drive the slicers.
"""

import html
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import ui
from finance_data import cash_on_hand_for_month, load_accounts, load_balance_history, load_transactions
from rules import (
    CASH_TYPES,
    RANGE_PRESETS,
    category_label,
    date_range_for,
    describe_range,
    effective_date,
    in_range,
    income_mask,
    is_bill,
    is_card_payment,
    is_transfer,
    month_totals,
    monthly_totals,
    net_worth_as_of,
    previous_range,
    rank_by,
)

# ---------- Data ----------
accounts = load_accounts()
transactions = load_transactions(months=12)
transactions["effective"] = effective_date(transactions)
transactions["month"] = transactions["effective"].dt.to_period("M")
transactions["label"] = transactions["category"].map(category_label)
today = pd.Timestamp.today().normalize()

# ---------- State ----------
state = st.session_state
state.setdefault("range_preset", "This month")
state.setdefault("custom_range", (today.replace(day=1).date(), today.date()))
state.setdefault("reset_token", 0)  # bumped by Clear: chart keys change, so their selections reset


def set_range(start, end):
    state["range_preset"] = "Custom"
    state["custom_range"] = (start.date(), end.date())


def clear_selections():
    state["reset_token"] += 1


def reset_all():
    # Set the widgets' values rather than deleting the keys, so every control repaints empty.
    state["range_preset"] = "This month"
    state["custom_range"] = (today.replace(day=1).date(), today.date())
    state["accounts_pick"] = []
    state["categories_pick"] = []
    state["merchant_search"] = ""
    clear_selections()


# ---------- Header and slicers: one quiet row, everything below obeys it ----------
title_col, reset_col = st.columns([6, 1], vertical_alignment="center")
title_col.title("Overview")
reset_col.button("Reset", on_click=reset_all, type="tertiary", width="stretch")

range_col, account_col, category_col, merchant_col = st.columns([3.2, 1.6, 1.6, 1.6], vertical_alignment="center")
with range_col:
    short = {
        "This month": "This month",
        "Last month": "Last month",
        "Last 3 months": "3 months",
        "Year to date": "YTD",
        "Custom": "Custom",
    }
    st.pills("Date range", RANGE_PRESETS, key="range_preset", label_visibility="collapsed", format_func=short.get)
with account_col:
    picked_accounts = st.multiselect(
        "Accounts",
        list(accounts.sort_values("account_type")["name"]),
        key="accounts_pick",
        placeholder="All accounts",
        label_visibility="collapsed",
    )
with category_col:
    picked_categories = st.multiselect(
        "Categories",
        sorted(transactions["label"].unique()),
        key="categories_pick",
        placeholder="All categories",
        label_visibility="collapsed",
    )
with merchant_col:
    merchant_search = st.text_input(
        "Merchant search", key="merchant_search", placeholder="Search merchants", label_visibility="collapsed"
    ).strip()
preset = state["range_preset"] or "This month"
if preset == "Custom":
    st.date_input("Custom range", key="custom_range", label_visibility="collapsed", format="MM/DD/YYYY", width=300)
start, end = date_range_for(preset, today, state.get("custom_range"))

# ---------- Apply the slicers ----------
sliced = transactions[in_range(transactions, start, end)]
prev_start, prev_end = previous_range(start, end, today)
previous = transactions[in_range(transactions, prev_start, prev_end)]
sliced_accounts = accounts
if picked_accounts:
    sliced = sliced[sliced["account_name"].isin(picked_accounts)]
    previous = previous[previous["account_name"].isin(picked_accounts)]
    sliced_accounts = accounts[accounts["name"].isin(picked_accounts)]
if picked_categories:
    sliced = sliced[sliced["label"].isin(picked_categories)]
    previous = previous[previous["label"].isin(picked_categories)]


def matches_search(df):
    needle = merchant_search.lower()
    return df["merchant"].str.lower().str.contains(needle, regex=False) | df["description"].str.lower().str.contains(
        needle, regex=False, na=False
    )


if merchant_search:
    sliced = sliced[matches_search(sliced)]
    previous = previous[matches_search(previous)]
# Trend series: 6 months ending with the range's last month, under the same account/category/merchant slicers.
history = transactions
if picked_accounts:
    history = history[history["account_name"].isin(picked_accounts)]
if picked_categories:
    history = history[history["label"].isin(picked_categories)]
if merchant_search:
    history = history[matches_search(history)]

range_text = describe_range(start, end)
prev_text = describe_range(prev_start, prev_end)
# "Aug 1–26": the year is implied when it matches the range's; kept when comparing with last year.
prev_short = prev_text.rsplit(",", 1)[0] if "," in prev_text and prev_end.year == end.year else prev_text

# ---------- Hero: net worth today (not sliced: it is a point in time) ----------
net_worth = accounts["last_balance"].sum()
assets = accounts.loc[accounts["last_balance"] > 0, "last_balance"].sum()
total_debt = -accounts.loc[accounts["last_balance"] < 0, "last_balance"].sum()
past_worth, past_date = net_worth_as_of(load_balance_history(), today - pd.Timedelta(days=30))
hero_note = (
    ui.delta_html(net_worth, past_worth, up_is_good=True, versus=past_date.strftime("%b %-d"))
    if past_worth is not None
    else "Trend appears once a month of daily syncs has built up"
)
cash_snapshot = cash_on_hand_for_month(end.to_period("M"), snapshot_day=15)
cash_text = (
    f"<b>{ui.money(cash_snapshot[0])}</b> cash on hand, {cash_snapshot[1].strftime('%b %-d')}"
    if cash_snapshot is not None
    else "No cash snapshot yet"
)
with st.container(border=True, key="card_hero"):
    st.markdown(
        f'<div class="hero-label">Net worth today</div><div class="hero-value">{ui.money(net_worth)}</div>'
        f'<div class="hero-sub">{hero_note} &nbsp;·&nbsp; Assets <b>{ui.money(assets)}</b> &nbsp;·&nbsp; '
        f"Debt <b>{ui.money(total_debt)}</b> &nbsp;·&nbsp; {cash_text}</div>",
        unsafe_allow_html=True,
    )

# ---------- Trend strip: the sliced range, its comparison, and six months of direction ----------
income, bills, spending = month_totals(sliced)
p_income, p_bills, p_spending = month_totals(previous)
left_over, p_left_over = income - bills - spending, p_income - p_bills - p_spending
paid_to_cards = -sliced.loc[is_card_payment(sliced), "amount"].sum()
trend = monthly_totals(history, end.to_period("M"), months=6)


def metric(col, label, value, prev, up_is_good):
    change = value - prev
    delta = f"{'+' if change >= 0 else '-'}{ui.money(abs(change))} vs {prev_short}" if previous.shape[0] else None
    col.metric(
        label,
        ui.money(value),
        delta=delta,
        delta_color=("normal" if up_is_good else "inverse") if delta else "off",
        border=False,
    )


ui.section_label(f"{range_text}  ·  compared with {prev_short}")
m1, m2, m3, m4 = st.columns(4)
metric(m1, "Income", income, p_income, True)
metric(m2, "Bills", bills, p_bills, False)
metric(m3, "Card spending", spending, p_spending, False)
metric(m4, "Left for debt and savings", left_over, p_left_over, True)
st.caption(
    f"Left for debt and savings is income minus bills minus card spending. Paid to cards in this range: "
    f"{ui.money(paid_to_cards)}, kept apart so card spending is not counted twice.".replace("$", "\\$")
)


# ---------- Charts that select ----------
CARD_HEIGHT = 400  # every card in a row is the same height, whatever it holds
CHART_HEIGHT = 290


def ranked_bars(ranked, label_title, key):
    """Horizontal bars, largest first. Click selects (several allowed), click again deselects,
    empty space clears. Returns the selected labels.

    Streamlit only reports clicks from single-layer charts, so the amount rides in the row
    label, and the click target is widened by drawing a second, near-invisible bar per row
    that spans the full width: clicking anywhere along a row selects it, not just its bar.
    """
    pick, hover = ui.click_and_hover("label", multi=True)
    ranked = ranked.assign(
        row=[f"{label}   {ui.money(amount)}" for label, amount in zip(ranked["label"], ranked["amount"], strict=True)]
    )
    reach = float(ranked["amount"].max()) * 1.04
    data = pd.concat([ranked.assign(kind="row", amount=reach), ranked.assign(kind="value")], ignore_index=True)
    is_row = alt.datum.kind == "row"
    chart = (
        alt.Chart(data)
        .mark_bar(size=18, cornerRadiusEnd=4, cursor="pointer", stroke="transparent", strokeWidth=16)
        .encode(
            y=alt.Y(
                "row:N",
                sort=list(ranked["row"]),
                title=None,
                axis=alt.Axis(
                    ticks=False,
                    domain=False,
                    labelLimit=240,
                    labelFontSize=13,
                    labelColor=ui.INK_SECONDARY,
                    labelPadding=12,
                ),
            ),
            x=alt.X("amount:Q", axis=None, stack=None, scale=alt.Scale(domain=[0, reach], nice=False)),
            color=alt.when(is_row)
            .then(alt.value(ui.INK))
            .when(alt.datum.is_rest)
            .then(alt.value(ui.DEEMPHASIS))
            .otherwise(alt.value(ui.ACCENT)),
            opacity=alt.when(hover, is_row)
            .then(alt.value(0.08))
            .when(is_row)
            .then(alt.value(0.03))
            .when(hover)
            .then(alt.value(1))
            .when(pick)
            .then(alt.value(0.85))
            .otherwise(alt.value(0.3)),
            order=alt.Order("kind:N", sort="ascending"),  # "row" backgrounds drawn before "value" bars
            tooltip=[
                alt.Tooltip("label:N", title=label_title),
                alt.Tooltip("count:Q", title="Transactions"),
            ],
        )
        .add_params(pick, hover)
    )
    event = ui.show_chart(chart, height=CHART_HEIGHT, key=f"{key}_{state['reset_token']}", selection="pick")
    chosen = [c for c in ui.picked_all(event, "pick", "label") if c in set(ranked["label"])]
    return chosen


def ranked_card(container, title, subtitle, txns, column, label_title, key, keep=8):
    with container, st.container(border=True, key=f"card_{key}", height=CARD_HEIGHT):
        st.subheader(title)
        if txns.empty:
            st.caption(subtitle + " Nothing in this view.")
            return []
        ranked = rank_by(txns, column, keep=keep)
        st.caption(f"{subtitle} {ui.money(ranked['amount'].sum())} across {len(ranked)}.".replace("$", "\\$"))
        return ranked_bars(ranked, label_title, key)


# Outflows exclude transfers (they net to zero) and, unless the category slicer asks for them,
# card payments (they settle spending that is already counted).
outflows = sliced[(sliced["amount"] < 0) & ~is_transfer(sliced)]
if not picked_categories:
    outflows = outflows[~is_card_payment(outflows)]
inflows = sliced[income_mask(sliced)]

out_col, merchant_col2, in_col = st.columns(3)
picked_out = ranked_card(out_col, "Money out", "By category.", outflows, "label", "Category", "out")
narrowed = outflows[outflows["label"].isin(picked_out)] if picked_out else outflows
everyday = narrowed if (picked_out or picked_categories) else narrowed[~is_bill(narrowed)]
picked_merchants = ranked_card(
    merchant_col2,
    "Top merchants",
    ("Within the selection." if (picked_out or picked_categories) else "Everyday spending, bills left out."),
    everyday,
    "merchant",
    "Merchant",
    "merchant",
    keep=8,
)
picked_in = ranked_card(in_col, "Money in", "By source.", inflows, "merchant", "Source", "in")

selections = [*picked_out, *picked_merchants, *picked_in]
if selections:
    note_col, clear_col = st.columns([5, 1], vertical_alignment="center")
    note_col.markdown(
        f'<div class="selection-note">Selected: <b>{html.escape(", ".join(selections))}</b>. '
        "Click again to deselect.</div>",
        unsafe_allow_html=True,
    )
    clear_col.button("Clear selections", on_click=clear_selections, width="stretch")

# ---------- By month, and the accounts ----------
ui.section_label("By month")
flow_col, accounts_col = st.columns(2)


def jump_to_month(chart_key):
    """Chart click handler: set the date range to the month that was clicked."""
    clicked = ui.picked(state.get(chart_key), "pick", "month_key")
    if clicked:
        period = pd.Period(clicked, freq="M")
        month_end = min(period.to_timestamp(how="end").normalize(), today)
        set_range(period.to_timestamp(), month_end)


with flow_col, st.container(border=True, key="card_flow", height=CARD_HEIGHT):
    st.subheader("Monthly cash flow")
    st.caption("Click a month to jump to it.")
    flow = trend.melt(
        id_vars=["month"], value_vars=["income", "bills", "spending"], var_name="kind", value_name="amount"
    )
    flow["kind"] = flow["kind"].str.capitalize()
    flow["label"] = flow["month"].dt.strftime("%b")
    flow["month_key"] = flow["month"].astype(str)
    flow["in_range"] = flow["month"].apply(lambda m: start.to_period("M") <= m <= end.to_period("M"))
    kinds = ["Income", "Bills", "Spending"]
    pick, hover = ui.click_and_hover("month_key")
    flow_chart = (
        alt.Chart(flow)
        .mark_bar(cornerRadiusEnd=3, cursor="pointer")
        .encode(
            x=alt.X(
                "label:N",
                sort=list(flow["label"].unique()),
                title=None,
                axis=alt.Axis(labelAngle=0, ticks=False),
                scale=alt.Scale(paddingInner=0.25),
            ),
            xOffset=alt.XOffset("kind:N", sort=kinds, scale=alt.Scale(paddingInner=0.15)),
            y=alt.Y("amount:Q", title=None, axis=alt.Axis(format="$~s", tickCount=4, domain=False, ticks=False)),
            color=alt.Color(
                "kind:N",
                sort=kinds,
                scale=alt.Scale(domain=kinds, range=[ui.SERIES["aqua"], ui.SERIES["orange"], ui.SERIES["blue"]]),
            ),
            opacity=alt.when(hover)
            .then(alt.value(1))
            .when(alt.datum.in_range)
            .then(alt.value(1))
            .otherwise(alt.value(0.4)),
            tooltip=[
                alt.Tooltip("label:N", title="Month"),
                alt.Tooltip("kind:N", title="Type"),
                alt.Tooltip("amount:Q", title="Amount", format="$,.0f"),
            ],
        )
        .add_params(pick, hover)
    )
    flow_key = f"flow_chart_{start.date()}_{end.date()}_{state['reset_token']}"
    ui.show_chart(
        flow_chart, height=CHART_HEIGHT, key=flow_key, selection="pick", on_select=lambda: jump_to_month(flow_key)
    )

with accounts_col, st.container(border=True, key="card_accounts", height=CARD_HEIGHT):
    st.subheader("Accounts")
    st.caption(
        f"{ui.money(sliced_accounts['last_balance'].sum())} across {len(sliced_accounts)} accounts, today".replace(
            "$", "\\$"
        )
    )
    groups = [
        ("Cash", sliced_accounts[sliced_accounts["account_type"].isin(CASH_TYPES)]),
        ("Credit cards", sliced_accounts[sliced_accounts["account_type"] == "credit_card"]),
        ("Other", sliced_accounts[~sliced_accounts["account_type"].isin(CASH_TYPES + ["credit_card"])]),
    ]
    rows = []
    for group_name, group in groups:
        if group.empty:
            continue
        rows.append(
            f'<div class="acct-group"><span>{group_name}</span><span>{ui.money(group["last_balance"].sum())}</span></div>'
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

# ---------- Transactions ----------
ui.section_label("Transactions")
with st.container(border=True, key="card_transactions"):
    table = sliced
    if picked_out or picked_in:
        wanted_labels = set(picked_out)
        table = (
            table[table["label"].isin(wanted_labels) | (table["merchant"].isin(picked_in) & income_mask(table))]
            if picked_in
            else table[table["label"].isin(wanted_labels)]
        )
    if picked_merchants:
        chosen = set(picked_merchants)
        if any(m.endswith(" others") for m in chosen):
            listed = set(rank_by(everyday, "merchant", keep=8).loc[lambda d: ~d["is_rest"], "label"])
            chosen = (chosen - {m for m in chosen if m.endswith(" others")}) | (set(everyday["merchant"]) - listed)
        table = table[table["merchant"].isin(chosen)]
    table = table.sort_values("posted", ascending=False)
    st.subheader(f"Transactions, {range_text}")
    summary = f"{len(table)} transactions, net {ui.money(table['amount'].sum(), cents=True)}"
    if selections:
        summary += f". Narrowed to {', '.join(selections)}."
    st.caption(summary.replace("$", "\\$"))
    st.dataframe(
        table[["posted", "merchant", "description", "label", "account_name", "amount"]],
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "posted": st.column_config.DateColumn("Date", format="MMM D", width="small"),
            "merchant": st.column_config.TextColumn("Merchant", width="medium"),
            "description": st.column_config.TextColumn("Bank description", width="large"),
            "label": st.column_config.TextColumn("Category", width="medium"),
            "account_name": st.column_config.TextColumn("Account", width="medium"),
            "amount": st.column_config.NumberColumn("Amount", format="dollar", width="small"),
        },
    )

last_sync = accounts["updated_at"].max()
age_hours = (pd.Timestamp.now() - last_sync).total_seconds() / 3600
freshness = f"Data as of {last_sync.strftime('%a %b %-d, %-I:%M %p')}"
if age_hours > 12:
    freshness += f" ({age_hours:.0f} hours ago; the sync runs every 6 hours, so check the sync logs)"
st.caption(
    f"{freshness}. Balances and transactions come from the bank feed every 6 hours; the page re-reads them every 5 minutes."
)
