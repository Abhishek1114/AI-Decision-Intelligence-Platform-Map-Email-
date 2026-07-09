import json
import streamlit as st
from phase2.phase7.dashboard.neo4j_client import get_driver
from phase2.phase7.dashboard.graph_path import fetch_graph_path

if "customer_id" not in st.session_state:
    st.warning("Please log in from the main page.")
    st.stop()

customer_id = st.session_state["customer_id"]
driver = get_driver()

FETCH_ALERTS = """
MATCH (a:AgentAssessment {customer_id: $customer_id})
WHERE a.severity IN ['high', 'critical']
RETURN a.assessment_id AS assessment_id, a.severity AS severity, a.status AS status,
       a.predicted_business_impact AS impact, a.recommended_actions_json AS actions_json,
       a.acknowledged AS acknowledged, a.created_at AS created_at
ORDER BY a.created_at DESC LIMIT 100
"""
ACK_QUERY = """
MATCH (a:AgentAssessment {assessment_id: $assessment_id})
SET a.acknowledged = true, a.acknowledged_at = datetime(), a.acknowledged_by = $acknowledged_by
"""

st.title("Alerts")
with driver.session() as session:
    records = list(session.run(FETCH_ALERTS, parameters={"customer_id": customer_id}))

for rec in records:
    with st.container(border=True):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{rec['severity'].upper()}** — {rec['impact']}")
            st.caption(f"{rec['assessment_id']} · {rec['created_at']}")
            for a in json.loads(rec["actions_json"] or "[]"):
                st.write(f"- {a}")

            with st.expander("🔍 Why — show supply chain path"):
                with driver.session() as path_session:
                    path = fetch_graph_path(path_session, rec["assessment_id"])
                if path is None:
                    st.caption("No graph path found for this assessment.")
                else:
                    chain = []
                    for t2 in path["tier2_suppliers"]:
                        chain.append(f"**{t2['name']}** ({t2['country']}) — Tier 2")
                    sole_flag = " ⚠️ sole-sourced" if path["supplier_sole_source"] else ""
                    chain.append(f"**{path['supplier_name']}** ({path['supplier_country']}, "
                                 f"{path['supplier_tier']}){sole_flag}")
                    for comp in path["components"]:
                        comp_flag = " ⚠️ sole-sourced component" if comp["sole_sourced"] else ""
                        chain.append(f"**{comp['name']}**{comp_flag} "
                                     f"(lead time: {comp['lead_time']}d, buffer: {comp['buffer']}d)")
                    for prod in path["products"]:
                        chain.append(f"**{prod['name']}** ({prod['category']})")

                    st.markdown(" → ".join(chain))
                    if not path["products"]:
                        st.caption("⚠️ No downstream products resolved — check narrowing_method on this assessment.")
        with col2:
            if rec["acknowledged"]:
                st.success("Acknowledged")
            elif st.button("Acknowledge", key=rec["assessment_id"]):
                with driver.session() as session:
                    session.run(ACK_QUERY, parameters={
                        "assessment_id": rec["assessment_id"],
                        "acknowledged_by": st.session_state["username"],
                    })
                st.rerun()