# phase2/dags/dag_usgs_earthquakes.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

from phase2.ingestion.sources.usgs import fetch_recent_earthquakes, normalise_usgs
from phase2.ingestion.normaliser import EventNormaliser

default_args = {
    "owner":            "supply_chain_platform",
    "retries":          1,
    "retry_delay":      timedelta(minutes=2),
    "email_on_failure": False,
}

with DAG(
    dag_id="dag_usgs_earthquakes",
    description="Ingest USGS earthquake events ≥ M5.0 into GlobalEvent nodes",
    schedule_interval="*/15 * * * *",   # Every 15 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["phase2", "ingestion", "usgs"],
    default_args=default_args,
) as dag:

    def ingest_usgs(**context):
        features    = fetch_recent_earthquakes(hours_back=1)
        normaliser  = EventNormaliser()
        ingested, skipped = 0, 0

        for feature in features:
            raw_normalised = normalise_usgs(feature)
            result = normaliser.process(source="usgs", raw_dict=raw_normalised)
            if result:
                ingested += 1
            else:
                skipped += 1

        
        print(f"[USGS DAG] Features found: {len(features)} | "
              f"Ingested: {ingested} | Skipped (dedup): {skipped}")
        return {"ingested": ingested, "skipped": skipped}

    ingest_task = PythonOperator(
        task_id="ingest_usgs_earthquakes",
        python_callable=ingest_usgs,
    )