# phase2/dags/dag_portwatch.py

from __future__ import annotations
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner":            "phase2",
    "depends_on_past":  False,
    "retries":          1,
    "retry_delay":      timedelta(minutes=10),
    "email_on_failure": False,
}

# Only forward ports at or above this congestion index
# 0.3 = just below medium — catches early-stage congestion before it peaks
MIN_CONGESTION_INDEX = 0.3


def fetch_portwatch(**context) -> None:
    from phase2.ingestion.sources.portwatch import fetch_port_congestion
    from phase2.raw_store.raw_event_store import RawEventStore

    # No use_fallback param — our mock function signature is fetch_port_congestion(locodes=None)
    records = fetch_port_congestion()
    RawEventStore().insert_batch("portwatch", records)
    context["ti"].xcom_push(key="raw_records", value=records)
    print(f"[PortWatch] Fetched {len(records)} congestion records")


def filter_portwatch(**context) -> None:
    records = context["ti"].xcom_pull(
        key="raw_records", task_ids="fetch_portwatch"
    ) or []

    filtered = []
    for r in records:
        # congestion_index is nested under record["data"] in our structure
        # not at the top level — this is the bug in the original file
        congestion = float(r.get("data", {}).get("congestion_index") or 0)
        if congestion >= MIN_CONGESTION_INDEX:
            filtered.append(r)

    context["ti"].xcom_push(key="filtered_records", value=filtered)
    print(
        f"[PortWatch] Filter threshold={MIN_CONGESTION_INDEX}: "
        f"{len(records)} → {len(filtered)}"
    )


def normalise_portwatch(**context) -> None:
    from phase2.ingestion.normaliser import normalise_batch

    records = context["ti"].xcom_pull(
        key="filtered_records", task_ids="filter_portwatch"
    ) or []
    if not records:
        print("[PortWatch] No records above congestion threshold")
        return

    events = normalise_batch("portwatch", records)
    context["ti"].xcom_push(
        key="events",
        value=[e.model_dump(mode="json") for e in events]
    )
    print(f"[PortWatch] Normalised {len(events)} events")


def dedup_portwatch(**context) -> None:
    from phase2.ingestion.dedup import dedup_events, reset_seen_ids
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="events", task_ids="normalise_portwatch"
    ) or []
    if not serialised:
        return

    reset_seen_ids()
    events = [GlobalEvent(**e) for e in serialised]
    unique = dedup_events(events)
    context["ti"].xcom_push(
        key="unique_events",
        value=[e.model_dump(mode="json") for e in unique]
    )
    print(f"[PortWatch] Dedup: {len(events)} → {len(unique)} unique")


def write_neo4j_portwatch(**context) -> None:
    from phase2.ingestion.neo4j_writer import write_events
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="unique_events", task_ids="dedup_portwatch"
    ) or []
    if not serialised:
        return

    stats = write_events([GlobalEvent(**e) for e in serialised])
    print(f"[PortWatch] Neo4j stats: {stats}")


def publish_redis_portwatch(**context) -> None:
    from phase2.streams.redis_streams import GlobalEventProducer
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="unique_events", task_ids="dedup_portwatch"
    ) or []
    if not serialised:
        return

    ids = GlobalEventProducer().publish_batch([GlobalEvent(**e) for e in serialised])
    print(f"[PortWatch] Published {len(ids)} events to Redis")


with DAG(
    dag_id="phase2_portwatch",
    description="Ingest PortWatch congestion data into the Phase 2 pipeline",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 */6 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["phase2", "portwatch", "congestion"],
    max_active_runs=1,
) as dag:

    t_fetch     = PythonOperator(task_id="fetch_portwatch",        python_callable=fetch_portwatch)
    t_filter    = PythonOperator(task_id="filter_portwatch",       python_callable=filter_portwatch)
    t_normalise = PythonOperator(task_id="normalise_portwatch",    python_callable=normalise_portwatch)
    t_dedup     = PythonOperator(task_id="dedup_portwatch",        python_callable=dedup_portwatch)
    t_write     = PythonOperator(task_id="write_neo4j_portwatch",  python_callable=write_neo4j_portwatch)
    t_publish   = PythonOperator(task_id="publish_redis_portwatch",python_callable=publish_redis_portwatch)

    t_fetch >> t_filter >> t_normalise >> t_dedup >> [t_write, t_publish]