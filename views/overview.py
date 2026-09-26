"""Overview page: where things stand today, and income/spending for a selected month."""

import html
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import ui
from finance_data import cash_on_hand_for_month, load_accounts, load_balance_history, load_transactions
from rules import (
    CASH_TYPES,
    category_label,
    days_counted,
    effective_date,
    income_mask,
    is_bill,
    is_card_payment,
    is_spending,
    is_transfer,
    month_totals,
    net_worth_as_of,
    rank_by,
)

FILTERS = ["All", "Income", "Bills", "Spending", "Card payments", "Cash", "Debt"]


# ---------- Data ----------
accounts = load_accounts()
transactions = load_transactions(months=12)
transactions["effective"] = effective_date(transactions)
transactions["month"] = transactions["effective"].dt.to_period("M")

today = pd.Timestamp.today().normalize()
available_months = sorted(transactions["month"].unique(), reverse=True)
month_labels = {m: m.strftime("%B %Y") for m in available_months}

# ---------- Header: title + the one filter row that scopes everything below ----------
title_col, month_col = st.columns([3, 1], vertical_alignment="bottom")
title_col.title("Overview")
selected_month = month_col.selectbox(
    "Month",
    options=available_months,
    format_func=lambda m: month_labels[m],
    index=0,
    label_visibility="collapsed",
    key="month_select",
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
    if past_worth is not None
    else "Trend appears once a month of daily syncs has built up"
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
        f"<span>{cash_text}</span></div>",
        unsafe_allow_html=True,
    )

# ---------- This month, against the same stretch of last month ----------
prev_month = selected_month - 1
prev_txns = transactions[transactions["month"] == prev_month]
is_current_month = selected_month == today.to_period("M")
if is_current_month:
    # A partial month against a full one always looks like a win; compare like with like.
    prev_txns = prev_txns[prev_txns["effective"].dt.day <= today.day]
    versus = f"{prev_month.strftime('%b')} 1–{today.day}"
else:
    versus = prev_month.strftime("%B")
has_prev = not prev_txns.empty

income, bills, spending = month_totals(month_txns)
p_income, p_bills, p_spending = month_totals(prev_txns) if has_prev else (None, None, None)
# The first three tiles add up to the fourth, so the row can be checked at a glance.
left_over = income - bills - spending
p_left_over = p_income - p_bills - p_spending if has_prev else None
paid_to_cards = -month_txns.loc[is_card_payment(month_txns), "amount"].sum()
p_paid_to_cards = -prev_txns.loc[is_card_payment(prev_txns), "amount"].sum() if has_prev else None

ui.section_label(month_name)
ui.tile_row(
    [
        ui.stat_tile("Income", ui.money(income), ui.delta_html(income, p_income, True, versus)),
        ui.stat_tile("Bills", ui.money(bills), ui.delta_html(bills, p_bills, False, versus)),
        ui.stat_tile("Card spending", ui.money(spending), ui.delta_html(spending, p_spending, False, versus)),
        ui.stat_tile(
            "Left for debt and savings", ui.money(left_over), ui.delta_html(left_over, p_left_over, True, versus)
        ),
        ui.stat_tile(
            "Paid to cards", ui.money(paid_to_cards), ui.delta_html(paid_to_cards, p_paid_to_cards, None, versus)
        ),
    ]
)
st.caption(
    "Income minus bills minus card spending is what is left. Card payments are shown apart "
    "because they pay for spending that is already counted."
)

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
elif choice == "Card payments":
    filtered_txns = month_txns[is_card_payment(month_txns)]
elif choice == "Cash":
    filtered_txns = month_txns[month_txns["account_type"].isin(CASH_TYPES)]
    filtered_accounts = accounts[accounts["account_type"].isin(CASH_TYPES)]
elif choice == "Debt":
    filtered_txns = month_txns[month_txns["account_type"] == "credit_card"]
    filtered_accounts = accounts[accounts["account_type"] == "credit_card"]
if choice in ("Income", "Bills", "Spending", "Card payments"):
    filtered_accounts = accounts[accounts["id"].isin(filtered_txns["account_id"].unique())]

chart_col, accounts_col = st.columns([3, 2])


def ranked_bars(ranked, label_title, key):
    """Horizontal bars, largest first. `ranked` has `label`, `amount`, `count`, `is_rest`.

    Click a bar to narrow everything below it; click it again, or empty space, to clear.
    Returns the clicked label, or None.

    Streamlit only reports clicks from single-layer charts, so this is one bar mark with no
    text layer: the amount rides in the row label instead of at the bar's tip.
    """
    pick, hover = ui.click_and_hover("label")
    ranked = ranked.assign(
        row=[f"{label}   {ui.money(amount)}" for label, amount in zip(ranked["label"], ranked["amount"], strict=True)]
    )
    chart = (
        alt.Chart(ranked)
        .mark_bar(
            size=18,
            cornerRadiusEnd=4,
            cursor="pointer",
            # An invisible outline widens the click target: a $60 bar is only a few pixels long.
            stroke="transparent",
            strokeWidth=16,  # bar 18 + outline 16 = the full 34px row
        )
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
            x=alt.X("amount:Q", axis=None),
            # The "N others" remainder is context, not a merchant, so it does not get the accent.
            color=alt.condition(alt.datum.is_rest, alt.value(ui.DEEMPHASIS), alt.value(ui.ACCENT)),
            opacity=alt.when(hover).then(alt.value(1)).when(pick).then(alt.value(0.85)).otherwise(alt.value(0.3)),
            tooltip=[
                alt.Tooltip("label:N", title=label_title),
                alt.Tooltip("amount:Q", title="Amount", format="$,.2f"),
                alt.Tooltip("count:Q", title="Transactions"),
            ],
        )
        .add_params(pick, hover)
    )
    event = ui.show_chart(chart, height=34 * len(ranked) + 8, key=key, selection="pick")
    return ui.picked(event, "pick", "label")


if choice == "Income":
    flow_subset = filtered_txns
else:
    # Money going out. Transfers net to zero, and card payments settle spending that is
    # already counted, so neither is an outflow unless card payments are what you asked for.
    flow_subset = filtered_txns[(filtered_txns["amount"] < 0) & ~is_transfer(filtered_txns)]
    if choice != "Card payments":
        flow_subset = flow_subset[~is_card_payment(flow_subset)]

# Clicking a bar narrows what is below it: category -> merchants -> transactions.
# Chart keys include the month and view, so changing either starts from a clean selection.
picked_category = picked_merchant = None
other_merchants = []

with chart_col, st.container(border=True, key="card_categories"):
    st.subheader(
        {
            "Income": "Income by source",
            "Bills": "Bills by type",
            "Spending": "Spending by category",
            "Card payments": "Card payments",
        }.get(choice, "Where the money went")
    )
    flow_subset = flow_subset.assign(label=flow_subset["category"].map(category_label))
    by_cat = rank_by(flow_subset, "label")
    if by_cat.empty:
        st.caption("Nothing to show for this view.")
    else:
        noun = "category" if len(by_cat) == 1 else "categories"
        st.caption(
            f"{ui.money(by_cat['amount'].sum())} across {len(by_cat)} {noun}, {month_name}. "
            "Click a bar to narrow the page to it.".replace("$", "\\$")
        )
        picked_category = ranked_bars(by_cat, "Category", key=f"cat_{selected_month}_{choice}")
        if picked_category not in set(by_cat["label"]):
            picked_category = None

with chart_col, st.container(border=True, key="card_merchants"):
    st.subheader("Who paid you" if choice == "Income" else "Where you spent it")
    if picked_category:
        merchant_subset, scope = flow_subset[flow_subset["label"] == picked_category], f"{picked_category} only. "
    elif choice == "All":
        # Rent alone would flatten every other bar, and the chart above already covers bills.
        merchant_subset, scope = flow_subset[~is_bill(flow_subset)], "Everyday spending, bills left out. "
    else:
        merchant_subset, scope = flow_subset, ""
    if merchant_subset.empty:
        st.caption("Nothing to show for this view.")
    else:
        by_merchant = rank_by(merchant_subset, "merchant", keep=8)
        st.caption(f"{scope}Names are cleaned up from bank descriptions, so grouping is approximate.")
        picked_merchant = ranked_bars(
            by_merchant, "Merchant", key=f"merchant_{selected_month}_{choice}_{picked_category}"
        )
        if picked_merchant not in set(by_merchant["label"]):
            picked_merchant = None
        listed = set(by_merchant.loc[~by_merchant["is_rest"], "label"])
        other_merchants = sorted(set(merchant_subset["merchant"]) - listed)

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
            f"<span>{ui.money(group['last_balance'].sum())}</span></div>"
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
pace_col, flow_col, daily_col = st.columns(3)

spend_all = transactions[is_spending(transactions)]


def jump_to_month(chart_key):
    """Chart click handler: switch the whole dashboard to the month that was clicked.
    Runs before the rerun, which is the only moment the month selector's value may be set."""
    clicked = ui.picked(st.session_state.get(chart_key), "pick", "month_key")
    if clicked:
        st.session_state["month_select"] = pd.Period(clicked, freq="M")


with pace_col, st.container(border=True, key="card_pace"):
    st.subheader("Spending pace")
    st.caption("Card spending added up day by day. Hover to compare.")

    def cumulative(period, through_day):
        daily = (-spend_all[spend_all["month"] == period].set_index("posted")["amount"]).groupby(lambda d: d.day).sum()
        return daily.reindex(range(1, through_day + 1), fill_value=0).cumsum()

    this_name, prev_name = selected_month.strftime("%B"), prev_month.strftime("%B")
    series = [
        pd.DataFrame({"day": s.index, "spent": s.values, "month": name})
        for s, name in [
            (cumulative(selected_month, days_counted(selected_month, today)), this_name),
            (cumulative(prev_month, prev_month.days_in_month), prev_name),
        ]
        if s.iloc[-1] > 0
    ]
    if not series:
        st.caption("No card spending in these months.")
    else:
        pace = pd.concat(series)
        names = list(pace["month"].unique())
        colour = alt.Color(
            "month:N",
            sort=[this_name, prev_name],
            scale=alt.Scale(domain=[this_name, prev_name], range=[ui.ACCENT, ui.DEEMPHASIS]),
        )
        x = alt.X(
            "day:Q",
            title="Day of month",
            scale=alt.Scale(domain=[1, 31], nice=False),
            axis=alt.Axis(grid=False, values=[1, 5, 10, 15, 20, 25, 31]),
        )
        y = alt.Y("spent:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=4, domain=False, ticks=False))
        lines = (
            alt.Chart(pace)
            .mark_line(strokeWidth=2, strokeJoin="round", strokeCap="round")
            .encode(x=x, y=y, color=colour)
        )
        ends = pace.groupby("month").tail(1)
        dots = (
            alt.Chart(ends)
            .mark_point(size=70, filled=True, opacity=1, stroke=ui.SURFACE, strokeWidth=2)
            .encode(x="day:Q", y="spent:Q", color=colour)
        )

        # Crosshair: aim at a day, not at a 2px line. One readout lists every month at that day.
        readout = pace.pivot(index="day", columns="month", values="spent").reset_index()
        for name in names:
            readout[name] = readout[name].map(lambda v: "not yet" if pd.isna(v) else f"${v:,.0f}")
        nearest = alt.selection_point(
            name="crosshair", nearest=True, on="mouseover", clear="mouseout", fields=["day"], empty=False
        )
        crosshair = (
            alt.Chart(readout)
            .mark_rule(color=ui.INK_MUTED, strokeWidth=1)
            .encode(
                x="day:Q",
                opacity=alt.condition(nearest, alt.value(0.8), alt.value(0)),
                tooltip=[alt.Tooltip("day:Q", title="Day of month")] + [alt.Tooltip(f"{n}:N", title=n) for n in names],
            )
            .add_params(nearest)
        )
        markers = (
            alt.Chart(pace)
            .mark_point(size=60, filled=True, stroke=ui.SURFACE, strokeWidth=2)
            .encode(x="day:Q", y="spent:Q", color=colour, opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
        )
        ui.show_chart(alt.layer(lines, dots, crosshair, markers), height=230)

recent = sorted(available_months)[-6:]

with flow_col, st.container(border=True, key="card_flow"):
    st.subheader("Monthly cash flow")
    st.caption(f"{month_name} highlighted. Click a month to switch to it.")
    flow_rows = []
    for m in recent:
        m_income, m_bills, m_spending = month_totals(transactions[transactions["month"] == m])
        for kind, amount in (("Income", m_income), ("Bills", m_bills), ("Spending", m_spending)):
            flow_rows.append(
                {
                    "month": m.strftime("%b"),
                    "month_key": str(m),
                    "kind": kind,
                    "amount": amount,
                    "selected": m == selected_month,
                }
            )
    flow = pd.DataFrame(flow_rows)
    kinds = ["Income", "Bills", "Spending"]
    pick, hover = ui.click_and_hover("month_key")
    flow_chart = (
        alt.Chart(flow)
        .mark_bar(cornerRadiusEnd=3, cursor="pointer")
        .encode(
            x=alt.X(
                "month:N",
                sort=[m.strftime("%b") for m in recent],
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
            # The month under the pointer lifts to full strength, so the chart visibly responds.
            opacity=alt.when(hover)
            .then(alt.value(1))
            .when(alt.datum.selected)
            .then(alt.value(1))
            .otherwise(alt.value(0.4)),
            tooltip=[
                alt.Tooltip("month:N", title="Month"),
                alt.Tooltip("kind:N", title="Type"),
                alt.Tooltip("amount:Q", title="Amount", format="$,.0f"),
            ],
        )
        .add_params(pick, hover)
    )
    # The key carries the month, so each month change hands the chart a clean slate. Otherwise
    # it would remember its last click and ignore the next click on that same month.
    flow_key = f"flow_chart_{selected_month}"
    ui.show_chart(flow_chart, height=230, key=flow_key, selection="pick", on_select=lambda: jump_to_month(flow_key))

with daily_col, st.container(border=True, key="card_daily"):
    st.subheader("Spending per day")
    st.caption("Monthly average, card spending. Click a month to switch to it.")
    monthly_spend = -spend_all.groupby("month")["amount"].sum()
    daily = pd.DataFrame(
        {
            "month": [m.strftime("%b") for m in monthly_spend.index],
            "month_key": [str(m) for m in monthly_spend.index],
            "per_day": [monthly_spend[m] / days_counted(m, today) for m in monthly_spend.index],
            "selected": [m == selected_month for m in monthly_spend.index],
        }
    ).tail(6)
    pick, hover = ui.click_and_hover("month_key")
    this_per_day = daily.loc[daily["selected"], "per_day"]
    if not this_per_day.empty:
        st.caption(
            f"{selected_month.strftime('%B')}: {ui.money(this_per_day.iloc[0], cents=True)} a day".replace("$", "\\$")
        )
    daily_chart = (
        alt.Chart(daily)
        .mark_bar(size=22, cornerRadiusEnd=4, cursor="pointer")
        .encode(
            x=alt.X("month:N", sort=list(daily["month"]), title=None, axis=alt.Axis(labelAngle=0, ticks=False)),
            y=alt.Y("per_day:Q", title=None, axis=alt.Axis(format="$,.0f", tickCount=4, domain=False, ticks=False)),
            color=alt.condition(alt.datum.selected, alt.value(ui.ACCENT), alt.value(ui.DEEMPHASIS)),
            opacity=alt.when(hover)
            .then(alt.value(1))
            .when(alt.datum.selected)
            .then(alt.value(1))
            .otherwise(alt.value(0.75)),
            tooltip=[alt.Tooltip("month:N", title="Month"), alt.Tooltip("per_day:Q", title="Per day", format="$,.2f")],
        )
        .add_params(pick, hover)
    )
    daily_key = f"daily_chart_{selected_month}"
    ui.show_chart(daily_chart, height=205, key=daily_key, selection="pick", on_select=lambda: jump_to_month(daily_key))

# ---------- Transactions ----------
ui.section_label("Transactions")
with st.container(border=True, key="card_transactions"):
    view_name = "All activity" if choice == "All" else choice
    table = filtered_txns.assign(category=filtered_txns["category"].map(category_label))
    narrowed_to = []
    if picked_category:
        table = table[table["category"] == picked_category]
        narrowed_to.append(picked_category)
    if picked_merchant:
        wanted = other_merchants if picked_merchant not in set(table["merchant"]) else [picked_merchant]
        table = table[table["merchant"].isin(wanted)]
        narrowed_to.append(picked_merchant)
    table = table.sort_values("posted", ascending=False)

    st.subheader(f"{view_name}, {month_name}")
    summary = f"{len(table)} transactions, net {ui.money(table['amount'].sum(), cents=True)}"
    if narrowed_to:
        summary += f". Narrowed to {' and '.join(narrowed_to)}. Click the bar again to clear."
    st.caption(summary.replace("$", "\\$"))
    st.dataframe(
        table[["posted", "description", "category", "account_name", "amount"]],
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "posted": st.column_config.DateColumn("Date", format="MMM D", width="small"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "category": st.column_config.TextColumn("Category", width="medium"),
            "account_name": st.column_config.TextColumn("Account", width="medium"),
            "amount": st.column_config.NumberColumn("Amount", format="dollar", width="small"),
        },
    )

last_sync = accounts["updated_at"].max()
age_hours = (pd.Timestamp.now() - last_sync).total_seconds() / 3600
freshness = f"Data as of {last_sync.strftime('%a %b %-d, %-I:%M %p')}"
if age_hours > 12:
    # Four syncs a day are scheduled; a gap this long means the Mac was off or a run failed.
    freshness += f" ({age_hours:.0f} hours ago; the sync runs every 6 hours, so check logs/sync.log)"
st.caption(
    f"{freshness}. Balances and transactions come from the bank feed every 6 hours; the page re-reads them every 5 minutes."
)
