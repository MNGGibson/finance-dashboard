"""Entry point: shared page setup. The dashboard itself lives in views/overview.py.

Run with: .venv/bin/streamlit run app.py
"""

import streamlit as st

import ui

st.set_page_config(
    page_title="Finance dashboard",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
    initial_sidebar_state="collapsed",
)
ui.apply_page_style()

# A single page, so the navigation menu is hidden rather than listing one item.
st.navigation([st.Page("views/overview.py", title="Overview", default=True)], position="hidden").run()
