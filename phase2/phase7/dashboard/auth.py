import os
import streamlit as st

CUSTOMER_LOGINS = {
    "apex": {
        "password": os.environ["DASHBOARD_PW_APEX"],
        "customer_id": "cust_apex_001"
    },
    "novara": {
        "password": os.environ["DASHBOARD_PW_NOVARA"],
        "customer_id": "cust_novara_001"
    },
    "volta": {
        "password": os.environ["DASHBOARD_PW_VOLTA"],
        "customer_id": "cust_volta_001"
    },
    "skybridge": {
        "password": os.environ["DASHBOARD_PW_SKYBRIDGE"],
        "customer_id": "cust_skybridge_001"
    },
    "monsoon": {
        "password": os.environ["DASHBOARD_PW_APPARELL"],
        "customer_id": "cust_monsoon_001"
    },
    "pacrim": {
        "password": os.environ["DASHBOARD_PW_PACIFIC_RIM"],
        "customer_id": "cust_pacrim_001"
    },
    "cascade": {
        "password": os.environ["DASHBOARD_PW_CASCADE"],
        "customer_id": "cust_cascade_001"
    },
    "andina": {
        "password": os.environ["DASHBOARD_PW_ANDINA"],
        "customer_id": "cust_andina_001"
    }
}

def login_form():
    if "customer_id" in st.session_state:
        return st.session_state["customer_id"]
    st.title("Supply Chain Dashboard — Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Log in"):
        record = CUSTOMER_LOGINS.get(username)
        if record and record["password"] == password:
            st.session_state["customer_id"] = record["customer_id"]
            st.session_state["username"] = username
            st.rerun()
        else:
            st.error("Invalid credentials")
    return None