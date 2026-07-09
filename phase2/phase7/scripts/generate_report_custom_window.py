# phase2/phase7/scripts/generate_report_custom_window.py
import os
from neo4j import GraphDatabase
from phase2.phase6.generate_report import generate_customer_report
from phase2.phase7.reports.report_delivery import generate_and_send_report_pdf

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

customer_id = "cust_monsoon_001"
period_start = "2026-07-03T00:00:00+00:00"
period_end = "2026-07-09T00:00:00+00:00"

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
with driver.session() as session:
    report_id = generate_customer_report(session, customer_id, period_start, period_end)
    print(f"Generated {report_id}")
    generate_and_send_report_pdf(session, report_id, customer_id)
driver.close()