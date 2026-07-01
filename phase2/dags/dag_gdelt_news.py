# phase2/dags/dag_gdelt_news.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

from phase2.ingestion.sources.google_news import fetch_google_news,normalise_google_news
from phase2.ingestion.normaliser import EventNormaliser

with DAG(
    dag_id="dag_gdelt_news",
    description="Ingest GDELT supply-chain-relevant news into GlobalEvent nodes",
    schedule_interval="*/30 * * * *",  # Every 30 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["phase2", "ingestion", "gdelt"],
    default_args={
        "owner": "supply_chain_platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
) as dag:

    def ingest_gdelt(**context):
        queries = [
            "factory shutdown",
            "port congestion shipping delay",
            "semiconductor shortage",
            "export ban trade restriction",
            "labor strike factory",
        ]
        articles   = fetch_google_news(max_per_feed=10)
        normaliser = EventNormaliser()
        ingested, skipped, invalid = 0, 0, 0

        for article in articles:
            raw_normalised = normalise_google_news(article)
            if raw_normalised is None:
                invalid += 1
                continue
            result = normaliser.process(source="gdelt", raw_dict=raw_normalised)
            if result:
                ingested += 1
            else:
                skipped += 1

        print(f"[GDELT DAG] Articles: {len(articles)} | "
              f"Ingested: {ingested} | Dedup skipped: {skipped} | Invalid: {invalid}")

    ingest_task = PythonOperator(
        task_id="ingest_gdelt_news",
        python_callable=ingest_gdelt,
    )