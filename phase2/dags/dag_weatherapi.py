# phase2/dags/dag_weatherapi.py  ← rename from dag_open_meteo.py

from __future__ import annotations
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner":            "phase2",
    "depends_on_past":  False,
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
    "email_on_failure": False,
}


def fetch_weatherapi(**context) -> None:
    from phase2.ingestion.sources.weatherapi import fetch_severe_weather
    from phase2.raw_store.raw_event_store import RawEventStore

    # fetch_severe_weather returns only severe locations — already filtered
    records = fetch_severe_weather()
    RawEventStore().insert_batch("open_meteo", records)
    context["ti"].xcom_push(key="severe_records", value=records)
    print(f"[WeatherAPI] Fetched {len(records)} severe weather locations")


def normalise_weatherapi(**context) -> None:
    from phase2.ingestion.normaliser import normalise_batch

    records = context["ti"].xcom_pull(
        key="severe_records", task_ids="fetch_weatherapi"
    ) or []
    if not records:
        print("[WeatherAPI] No severe weather records — nothing to normalise")
        return

    events = normalise_batch("open_meteo", records)
    context["ti"].xcom_push(
        key="events",
        value=[e.model_dump(mode="json") for e in events]
    )
    print(f"[WeatherAPI] Normalised {len(events)} events")


def dedup_weatherapi(**context) -> None:
    from phase2.ingestion.dedup import dedup_events, reset_seen_ids
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="events", task_ids="normalise_weatherapi"
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
    print(f"[WeatherAPI] Dedup: {len(events)} → {len(unique)} unique")


def write_neo4j_weatherapi(**context) -> None:
    from phase2.ingestion.neo4j_writer import write_events
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="unique_events", task_ids="dedup_weatherapi"
    ) or []
    if not serialised:
        return

    stats = write_events([GlobalEvent(**e) for e in serialised])
    print(f"[WeatherAPI] Neo4j stats: {stats}")


def publish_redis_weatherapi(**context) -> None:
    from phase2.streams.redis_streams import GlobalEventProducer
    from phase2.models.global_event import GlobalEvent

    serialised = context["ti"].xcom_pull(
        key="unique_events", task_ids="dedup_weatherapi"
    ) or []
    if not serialised:
        return

    ids = GlobalEventProducer().publish_batch([GlobalEvent(**e) for e in serialised])
    print(f"[WeatherAPI] Published {len(ids)} events to Redis")


with DAG(
    dag_id="phase2_weatherapi",
    description="Ingest WeatherAPI severe weather events into the Phase 2 pipeline",
    default_args=DEFAULT_ARGS,
    schedule_interval="*/30 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["phase2", "weather", "weatherapi"],
    max_active_runs=1,
) as dag:

    t_fetch     = PythonOperator(task_id="fetch_weatherapi",         python_callable=fetch_weatherapi)
    t_normalise = PythonOperator(task_id="normalise_weatherapi",     python_callable=normalise_weatherapi)
    t_dedup     = PythonOperator(task_id="dedup_weatherapi",         python_callable=dedup_weatherapi)
    t_write     = PythonOperator(task_id="write_neo4j_weatherapi",   python_callable=write_neo4j_weatherapi)
    t_publish   = PythonOperator(task_id="publish_redis_weatherapi", python_callable=publish_redis_weatherapi)

    t_fetch >> t_normalise >> t_dedup >> [t_write, t_publish]