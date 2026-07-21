"""Overview page: current balances, and income/spending for a selected month.

Run with: .venv/bin/streamlit run app.py
"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from finance_data import cash_on_hand_for_month, load_accounts, load_transactions

st.set_page_config(page_title="Overview", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 2rem; padding-bottom: 2rem; }

.kpi-card {
    background: var(--secondary-background-color);
    border-radius: 10px;
    border-left: 3px solid var(--accent, rgba(128,128,128,0.4));
    padding: 10px 12px 8px 12px;
    margin-bottom: 2px;
}
.kpi-label {
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.6;
    margin: 0 0 3px 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.kpi-value {
    font-size: 1.05rem;
    font-weight: 700;
    margin: 0;
    white-space: nowrap;
}

div[data-testid="stButton"] > button {
    font-size: 0.68rem;
    padding: 2px 0;
    min-height: 26px;
    border-radius: 0 0 8px 8px;
    border-top: none;
    opacity: 0.7;
}
div[data-testid="stButton"] > button:hover { opacity: 1; }

hr { margin: 0.6rem 0 1rem 0; opacity: 0.2; }
h3 { margin-top: 0; padding-top: 0.2rem; }
</style>
""", unsafe_allow_html=True)


def kpi_card(col, label, value, key, filter_value, accent):
    with col:
        st.markdown(
            f'<div class="kpi-card" style="--accent:{accent}">'
            f'<p class="kpi-label">{label}</p>'
            f'<p class="kpi-value">{value}</p>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("Details", key=key, use_container_width=True):
            st.session_state.kpi_filter = filter_value


st.title("Overview")

accounts = load_accounts()
transactions = load_transactions(months=12)

net_worth = accounts["last_balance"].sum()
total_debt = -accounts.loc[accounts["last_balance"] < 0, "last_balance"].sum()
cash_on_hand_current = accounts.loc[accounts["account_type"].isin(["checking", "savings"]), "last_balance"].sum()

# ---------- Month selector ----------
transactions["month"] = transactions["posted"].dt.to_period("M")
available_months = sorted(transactions["month"].unique(), reverse=True)
month_labels = {m: m.strftime("%B %Y") for m in available_months}

selected_month = st.selectbox(
    "Month", options=available_months, format_func=lambda m: month_labels[m], index=0,
)
month_txns = transactions[transactions["month"] == selected_month]

month_income = month_txns.loc[month_txns["amount"] > 0, "amount"].sum()
month_spending = -month_txns.loc[month_txns["category"] == "spending:discretionary", "amount"].sum()
month_bills = -month_txns.loc[month_txns["category"].str.startswith("bill:", na=False), "amount"].sum()

# Cash on hand is snapshotted per month (closest daily sync to the 15th), not
# today's live balance -- so past/future months show what cash actually was then.
cash_snapshot = cash_on_hand_for_month(selected_month, snapshot_day=15)
if cash_snapshot is not None:
    cash_on_hand, cash_snapshot_date = cash_snapshot
    cash_label = f"Cash on hand (as of {cash_snapshot_date.strftime('%b %-d')})"
else:
    cash_on_hand = None
    cash_label = "Cash on hand"

# ---------- KPI row (click "Details" under any KPI to filter everything below) ----------
if "kpi_filter" not in st.session_state:
    st.session_state.kpi_filter = None

cols = st.columns(7)
kpi_card(cols[0], "Net worth", f"${net_worth:,.0f}", "btn_networth", None, "#639922" if net_worth >= 0 else "#E24B4A")
kpi_card(cols[1], "Cash (current)", f"${cash_on_hand_current:,.0f}", "btn_cash_current", "cash", "#378ADD")
kpi_card(cols[2], cash_label.replace("Cash on hand", "Cash"), f"${cash_on_hand:,.0f}" if cash_on_hand is not None else "n/a", "btn_cash", "cash", "#378ADD")
kpi_card(cols[3], "Total debt", f"${total_debt:,.0f}", "btn_debt", "debt", "#E24B4A")
kpi_card(cols[4], "Income", f"${month_income:,.0f}", "btn_income", "income", "#639922")
kpi_card(cols[5], "Bills", f"${month_bills:,.0f}", "btn_bills", "bills", "#D85A30")
kpi_card(cols[6], "Spending", f"${month_spending:,.0f}", "btn_spending", "spending", "#378ADD")

kpi_filter = st.session_state.kpi_filter
filter_names = {
    None: "All accounts & transactions",
    "cash": "Cash on hand",
    "debt": "Total debt",
    "income": f"Income — {month_labels[selected_month]}",
    "bills": f"Bills — {month_labels[selected_month]}",
    "spending": f"Spending — {month_labels[selected_month]}",
}
fc1, fc2 = st.columns([6, 1])
if kpi_filter is not None and fc2.button("Clear filter"):
    st.session_state.kpi_filter = None
    st.rerun()
fc1.caption(f"Showing: **{filter_names[kpi_filter]}**")

# ---------- Single source of truth: every visual below filters off this ----------
filtered_txns = month_txns.copy()
if kpi_filter == "income":
    filtered_txns = filtered_txns[filtered_txns["amount"] > 0]
elif kpi_filter == "bills":
    filtered_txns = filtered_txns[filtered_txns["category"].str.startswith("bill:", na=False)]
elif kpi_filter == "spending":
    filtered_txns = filtered_txns[filtered_txns["category"] == "spending:discretionary"]
elif kpi_filter == "cash":
    filtered_txns = filtered_txns[filtered_txns["account_type"].isin(["checking", "savings"])]
elif kpi_filter == "debt":
    filtered_txns = filtered_txns[filtered_txns["account_type"] == "credit_card"]

filtered_accounts = accounts.copy()
if kpi_filter == "cash":
    filtered_accounts = filtered_accounts[filtered_accounts["account_type"].isin(["checking", "savings"])]
elif kpi_filter == "debt":
    filtered_accounts = filtered_accounts[filtered_accounts["account_type"] == "credit_card"]
elif kpi_filter in ("income", "bills", "spending"):
    touched = filtered_txns["account_name"].unique()
    filtered_accounts = filtered_accounts[filtered_accounts["name"].isin(touched)]

st.markdown("---")

left, right = st.columns([1, 1])

with left:
    chart_config = {
        "income": ("Income by source", filtered_txns[filtered_txns["amount"] > 0], "#639922"),
        "bills": ("Bills by type", filtered_txns[filtered_txns["category"].str.startswith("bill:", na=False)], "#D85A30"),
        "spending": ("Spending by category", filtered_txns[filtered_txns["category"] == "spending:discretionary"], "#378ADD"),
    }
    chart_title, cat_subset, bar_color = chart_config.get(
        kpi_filter, ("Outflows by category", filtered_txns[filtered_txns["amount"] < 0], "#378ADD")
    )
    st.subheader(chart_title)
    cat_subset = cat_subset.copy()
    cat_subset["category_label"] = cat_subset["category"].apply(
        lambda c: c.split(":", 1)[1].replace("_", " ") if pd.notna(c) and ":" in c else "uncategorized"
    )
    by_cat = cat_subset.groupby("category_label")["amount"].sum().abs().sort_values(ascending=True)
    if by_cat.empty:
        st.caption("Nothing to show for this filter.")
    else:
        fig, ax = plt.subplots(figsize=(6, max(2, 0.4 * len(by_cat))))
        fig.patch.set_alpha(0)
        ax.patch.set_alpha(0)
        ax.barh(by_cat.index, by_cat.values, color=bar_color)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlabel("$")
        st.pyplot(fig, use_container_width=True)
        st.caption(f"Total: ${by_cat.sum():,.2f}")

with right:
    st.subheader("Account balances")
    bal_table = filtered_accounts[["name", "org_name", "account_type", "last_balance"]].copy()
    bal_table.columns = ["Account", "Institution", "Type", "Balance"]
    bal_table = bal_table.sort_values("Balance", ascending=False)
    st.dataframe(
        bal_table.style.format({"Balance": "${:,.2f}"}),
        hide_index=True, use_container_width=True,
    )
    st.caption(f"Total: ${filtered_accounts['last_balance'].sum():,.2f} across {len(filtered_accounts)} accounts")

st.markdown("---")


def days_counted(period):
    """Full days in the month, or days elapsed so far if it's the current month."""
    start = period.to_timestamp()
    end = start + pd.offsets.MonthEnd(1)
    current_period = pd.Timestamp.today().to_period("M")
    if period == current_period:
        return (pd.Timestamp.today().normalize() - start).days + 1
    return end.day


st.subheader("Daily spend average")
disc_all = transactions[transactions["category"] == "spending:discretionary"].copy()
monthly_spend = disc_all.groupby("month")["amount"].sum().abs()
monthly_days = pd.Series({m: days_counted(m) for m in monthly_spend.index})
monthly_avg = (monthly_spend / monthly_days).sort_index()

dc1, dc2 = st.columns([1, 3])
with dc1:
    this_month_avg = monthly_avg.get(selected_month, 0)
    days_this = days_counted(selected_month)
    st.markdown(
        f'<div class="kpi-card" style="--accent:#378ADD">'
        f'<p class="kpi-label">{month_labels[selected_month]} avg/day</p>'
        f'<p class="kpi-value">${this_month_avg:,.2f}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"${monthly_spend.get(selected_month, 0):,.2f} over {days_this} days")

with dc2:
    fig3, ax3 = plt.subplots(figsize=(7, 2.8))
    fig3.patch.set_alpha(0)
    ax3.patch.set_alpha(0)
    labels = [m.strftime("%b %Y") for m in monthly_avg.index]
    colors = ["#0F6E56" if m == selected_month else "#9FE1CB" for m in monthly_avg.index]
    ax3.bar(labels, monthly_avg.values, color=colors)
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.set_ylabel("$/day")
    st.pyplot(fig3, use_container_width=True)

st.markdown("---")

st.subheader(f"Transactions — {filter_names[kpi_filter]}")
st.caption(f"{len(filtered_txns)} transactions, totaling ${filtered_txns['amount'].sum():,.2f}")
txn_table = filtered_txns[["posted", "account_name", "description", "category", "amount"]].copy()
txn_table["category"] = txn_table["category"].fillna("uncategorized")
txn_table = txn_table.sort_values("posted", ascending=False)
txn_table.columns = ["Date", "Account", "Description", "Category", "Amount"]
st.dataframe(
    txn_table.style.format({"Amount": "${:,.2f}", "Date": lambda d: d.strftime("%Y-%m-%d")}),
    hide_index=True, use_container_width=True, height=400,
)

st.caption("Data refreshes every 5 minutes from the local Postgres database, synced daily via scripts/sync.py.")
