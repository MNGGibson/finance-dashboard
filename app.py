"""Entry point: shared page setup and navigation. The pages themselves live in views/.

Run with: .venv/bin/streamlit run app.py
"""
import streamlit as st

import ui

st.set_page_config(page_title="Finance dashboard", page_icon=":material/account_balance_wallet:", layout="wide")
ui.apply_page_style()

st.navigation([
    st.Page("views/overview.py", title="Overview", icon=":material/space_dashboard:", default=True),
    st.Page("views/forecasting.py", title="Forecasting", icon=":material/trending_up:", url_path="Forecasting"),
]).run()
