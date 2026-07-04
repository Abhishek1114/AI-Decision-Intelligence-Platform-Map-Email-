"""
Airflow DAG — phase4_impact_matching

Runs after phase3_nlp_enrichment. Reads eligible GlobalEvent nodes,
matches them to suppliers/customers via direct mention + geo-proximity,
scores impact, and writes IMPACTS relationships.

Phase 5 integration (added this session): also passes a Redis client into
run_impact_matching() so triggered IMPACTS writes notify Phase 5's agent
via produce_alert() -- see phase2/phase4/impact_matching.py's write_impact().
The client is created fresh per task run (Airflow's PythonOperator runs in
a new process each invocation, so there's no long-lived connection to reuse
or leak) and reuses the "redis" service hostname already reachable on the
same Docker network -- no new env vars needed.

NOTE on schedule: this mirrors phase3_nlp_enrichment's 30-minute polling
interval for consistency. The project's architecture decisions record an
event-driven design (Redis Streams, ~30-90s latency) as the target pattern
rather than fixed-interval polling. If Phase 4 alerts need to reach
customers faster than a 30-minute window, swap this DAG's trigger for a
Redis Streams consumer that calls run_impact_matching() directly, rather
than just shortening the cron interval. Left as polling here to match
Phase 3 until that's revisited. Note this also caps how fresh Phase 5's
alerts can ever be -- Phase 5 reacts within its own poll interval, but only
to what this DAG has already written, so end-to-end latency is still
bounded by this 30-minute cycle, not the ~30-90s target, until this is
revisited.
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
from phase2.phase5.streaming.redis_stream import get_redis_client

NEO4J_URI = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]


def process_batch(**context):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    redis_client = get_redis_client(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
    )
    try:
        result = run_impact_matching(
            driver, DEFAULT_GEO_DISTANCE_THRESHOLD_M, redis_client=redis_client
        )
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