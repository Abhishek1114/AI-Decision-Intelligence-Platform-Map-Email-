import streamlit as st
from phase2.phase7.dashboard.neo4j_client import get_driver

if "customer_id" not in st.session_state:
    st.warning("Please log in from the main page.")
    st.stop()

customer_id = st.session_state["customer_id"]
driver = get_driver()

FETCH_REPORTS = """
MATCH (r:ExecutiveReport {customer_id: $customer_id})
RETURN r.report_id AS report_id, r.period_start AS period_start, r.period_end AS period_end,
       r.status AS status, r.incident_count AS incident_count, r.theme_count AS theme_count,
       r.escalation_rate AS escalation_rate, r.pdf_path AS pdf_path
ORDER BY r.created_at DESC
"""

st.title("Weekly Reports")
with driver.session() as session:
    records = list(session.run(FETCH_REPORTS, parameters={"customer_id": customer_id}))

for rec in records:
    with st.container(border=True):
        st.markdown(f"**{rec['period_start']} → {rec['period_end']}** ({rec['status']})")
        st.caption(f"Incidents: {rec['incident_count']} | Themes: {rec['theme_count']} | Escalation rate: {rec['escalation_rate']}")
        if rec["pdf_path"]:
            try:
                with open(rec["pdf_path"], "rb") as f:
                    st.download_button("Download PDF", f.read(), file_name=f"{rec['report_id']}.pdf",
                                        mime="application/pdf", key=rec["report_id"])
            except FileNotFoundError:
                st.error("PDF file missing on disk")
        else:
            st.info("No PDF for this report yet")