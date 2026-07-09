import streamlit as st
from phase2.phase7.dashboard.auth import login_form

st.set_page_config(page_title="Supply Chain Dashboard", layout="wide")
customer_id = login_form()
if customer_id is None:
    st.stop()

st.sidebar.success(f"Logged in as {st.session_state['username']}")
if st.sidebar.button("Log out"):
    del st.session_state["customer_id"]
    del st.session_state["username"]
    st.rerun()
st.write("Use the pages in the sidebar: Alerts / Reports")