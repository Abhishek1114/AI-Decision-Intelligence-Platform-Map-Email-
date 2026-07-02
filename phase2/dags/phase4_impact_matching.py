"""
Airflow DAG — phase4_impact_matching

Runs after phase3_nlp_enrichment. Reads eligible GlobalEvent nodes,
matches them to suppliers/customers via direct mention + geo-proximity,
scores impact, and writes IMPACTS relationships.

NOTE on schedule: this mirrors phase3_nlp_enrichment's 30-minute polling
interval for consistency. The project's architecture decisions record an
event-driven design (Redis Streams, ~30-90s latency) as the target pattern
rather than fixed-interval polling. If Phase 4 alerts need to reach
customers faster than a 30-minute window, swap this DAG's trigger for a
Redis Streams consumer that calls run_impact_matching() directly, rather
than just shortening the cron interval. Left as polling here to match
Phase 3 until that's revisited.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from neo4j import GraphDatabase

sys.path.append("/opt/airflow")

from phase2.phase4.impact_matching import DEFAULT_GEO_DISTANCE_THRESHOLD_M, run_impact_matching

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USER = os.environ["NEO4J_USER"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]


def process_batch(**context):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        result = run_impact_matching(driver, DEFAULT_GEO_DISTANCE_THRESHOLD_M)
    finally:
        driver.close()
    return result


default_args = {
    "owner": "supply_chain",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="phase4_impact_matching",
    default_args=default_args,
    schedule_interval="*/30 * * * *",
    start_date=datetime(2026, 7, 1),
    catchup=False,
    max_active_runs=1,
    tags=["phase4", "impact-matching"],
) as dag:
    process_batch_task = PythonOperator(
        task_id="process_batch",
        python_callable=process_batch,
    )