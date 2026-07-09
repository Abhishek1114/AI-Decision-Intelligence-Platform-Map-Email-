"""
Phase 6 — phase6_report_dag.py

Weekly executive report generation, one task per customer — matches the
Phase 4 DAG pattern (independent per-entity tasks under SequentialExecutor,
so one customer's failure/needs_review doesn't block the others).

Scheduled off-peak (Monday 02:00) deliberately: on Groq's free tier,
openai/gpt-oss-120b's rate limits are enforced at the org level, so this
DAG's calls share the same TPM/RPD pool as Phase 5's live alert consumer.
Running overnight minimizes overlap with daytime event-driven traffic.
Revisit this if/when the account moves to a paid tier with higher ceilings.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from neo4j import GraphDatabase

from phase2.phase6.generate_report import generate_customer_report
from phase2.phase7.reports.report_delivery import generate_and_send_report_pdf

NEO4J_URI = "bolt://neo4j:7687"  # matches existing docker-compose service name
NEO4J_AUTH = ("neo4j", "supply_chain_secret")  # placeholder — pull from Airflow Connection/Variable in prod

CUSTOMERS = [
    "cust_apex_001",
    "cust_novara_001",
    "cust_volta_001",
    "cust_skybridge_001",
    "cust_andina_001",
    "cust_cascade_001",
    "cust_monsoon_001",
    "cust_pacrim_001",
]


def _run_report_for_customer(customer_id: str, **context):
    # Weekly window: prior 7 days ending at this run's logical date.
    period_end = context["data_interval_end"].isoformat()
    period_start = (context["data_interval_end"] - timedelta(days=7)).isoformat()

    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    try:
        with driver.session() as session:
            report_id = generate_customer_report(
                session, customer_id, period_start, period_end
            )
            print(f"Generated {report_id} for {customer_id}")
            generate_and_send_report_pdf(session, report_id, customer_id)
    finally:
        driver.close()


with DAG(
    dag_id="phase6_executive_reports",
    description="Weekly per-customer executive report generation (Phase 6)",
    schedule_interval="0 2 * * 1",  # Monday 02:00 UTC — off-peak, see note above
    start_date=datetime(2026, 7, 1),
    catchup=False,
    max_active_runs=1,  # SequentialExecutor; avoid overlapping weekly runs
) as dag:

    for customer_id in CUSTOMERS:
        PythonOperator(
            task_id=f"generate_report_{customer_id}",
            python_callable=_run_report_for_customer,
            op_kwargs={"customer_id": customer_id},
        )