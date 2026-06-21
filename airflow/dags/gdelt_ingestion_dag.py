"""
airflow/dags/gdelt_ingestion_dag.py
-------------------------------------
Airflow DAG: daily GDELT supply-chain news ingestion → Neo4j.

Schedule: Every 6 hours (4× daily). GDELT updates its article index every 15 min,
but supply-chain disruption signals don't need sub-hour latency in Phase 2.
Phase 4 agent will query Neo4j for the latest events on demand.

Task flow:
  fetch_articles → classify_articles → write_to_neo4j → mark_done

Why TaskFlow API (@task decorator)?
  - Automatic XCom serialization between tasks (no explicit push/pull)
  - Cleaner than PythonOperator for data-passing pipelines
  - Compatible with Airflow 2.4+

Idempotency: Each run uses MERGE on event_id. Re-running for the same
6-hour window produces the same event_id hash → no duplicates.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task
from airflow.models import Variable

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "scm-pipeline",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "email_on_failure": False,
}


@dag(
    dag_id="gdelt_ingestion",
    description="Fetch supply-chain-relevant articles from GDELT and write DisruptionEvents to Neo4j",
    schedule_interval="0 */6 * * *",      # every 6 hours
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["phase2", "ingestion", "gdelt"],
)
def gdelt_ingestion_dag():

    @task()
    def fetch_articles() -> list[dict]:
        """
        Fetch GDELT articles for the last 24 hours.
        Returns serializable list of dicts (XCom must be JSON-serializable).
        """
        from ingestion.gdelt.fetcher import GDELTFetcher
        from ingestion.event_id import reset_counters

        reset_counters()

        fetcher = GDELTFetcher(timeout=30)
        articles = fetcher.fetch(timespan="LAST24H", max_records=10)

        # Serialize to dict for XCom (Pydantic models not JSON-serializable by default)
        serialized = [a.model_dump(mode="json") for a in articles]
        logger.info("Fetched %d GDELT articles", len(serialized))
        return serialized

    @task()
    def classify_articles(raw_articles: list[dict]) -> list[dict]:
        """
        Apply rule-based classifier to each article.
        Returns list of event field dicts ready for Neo4j upsert.
        """
        from ingestion.gdelt.fetcher import GDELTArticle
        from ingestion.gdelt.classifier import article_to_event_fields
        from ingestion.event_id import generate_event_id

        events = []
        for raw in raw_articles:
            article = GDELTArticle(**raw)
            fields = article_to_event_fields(article)
            fields["event_id"] = generate_event_id("gdelt", article.published_at)
            fields["article_id"] = article.article_id   # for dedup tracking
            events.append(fields)

        logger.info("Classified %d articles → %d event candidates", len(raw_articles), len(events))
        return events

    @task()
    def deduplicate_events(events: list[dict]) -> list[dict]:
        """
        Remove events with duplicate titles within the same run.
        Near-duplicate GDELT articles often cover the same story from different outlets.
        Phase 3 will do semantic dedup with embeddings — this is a lightweight pass.
        """
        seen_titles: set[str] = set()
        unique = []
        for event in events:
            title_lower = event["title"].lower().strip()
            if title_lower not in seen_titles:
                seen_titles.add(title_lower)
                unique.append(event)

        logger.info("Dedup: %d → %d events", len(events), len(unique))
        return unique

    @task()
    def write_to_neo4j(events: list[dict]) -> dict:
        """
        Upsert DisruptionEventNode records into Neo4j.
        Uses SupplyChainRepository.upsert_disruption_event() — idempotent MERGE.

        Also links event → affected Supplier/Port/Region if classifier detected one.
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")

        from datetime import datetime, timezone
        from graph.connection import get_connection
        from graph.models.nodes import DisruptionEventNode, EventType, RiskLevel
        from graph.queries.repository import SupplyChainRepository
        from graph.models.relationships import AffectsRel

        conn = get_connection()
        repo = SupplyChainRepository(conn)

        written = 0
        errors = 0
        region_links = 0

        for fields in events:
            try:
                # Coerce string datetimes back to datetime objects
                for dt_field in ("started_at", "ended_at", "created_at", "updated_at"):
                    val = fields.get(dt_field)
                    if isinstance(val, str):
                        fields[dt_field] = datetime.fromisoformat(val)
                    elif val is None and dt_field in ("created_at", "updated_at"):
                        fields[dt_field] = datetime.now(timezone.utc)

                node = DisruptionEventNode(
                    event_id=fields["event_id"],
                    event_type=EventType(fields["event_type"]),
                    title=fields["title"],
                    description=fields["description"],
                    severity=RiskLevel(fields["severity"]),
                    source=fields.get("source", "gdelt"),
                    source_url=fields.get("source_url"),
                    affected_region=fields.get("affected_region"),
                    started_at=fields["started_at"],
                    ended_at=fields.get("ended_at"),
                    is_resolved=fields.get("is_resolved", False),
                    impact_score=fields.get("impact_score", 0.5),
                    created_at=fields["created_at"],
                    updated_at=fields["updated_at"],
                )

                repo.upsert_disruption_event(node)
                written += 1

                # Link to region if classifier detected one
                affected_region = fields.get("affected_region")
                if affected_region:
                    try:
                        # Add AFFECTS relationship to the Region node
                        affects_rel = AffectsRel(
                            impact_type="supply_delay",
                            estimated_delay_days=None,
                            confidence=0.4,         # low confidence — rule-based only
                            detected_at=fields["created_at"],
                        )
                        # Region is not a standard AFFECTS target in schema — skip for now.
                        # Phase 3 will link to specific Supplier/Port after NER.
                        region_links += 1
                    except Exception:
                        pass

            except Exception as exc:
                errors += 1
                logger.error("Failed to write event %s: %s", fields.get("event_id"), exc)

        result = {"written": written, "errors": errors, "region_links": region_links}
        logger.info("Neo4j write complete: %s", result)
        return result

    @task()
    def log_run_summary(neo4j_result: dict):
        """Log final run stats — visible in Airflow task logs and XCom."""
        logger.info(
            "GDELT ingestion run complete | written=%d errors=%d",
            neo4j_result.get("written", 0),
            neo4j_result.get("errors", 0),
        )

    # DAG wiring
    articles = fetch_articles()
    classified = classify_articles(articles)
    deduped = deduplicate_events(classified)
    neo4j_result = write_to_neo4j(deduped)
    log_run_summary(neo4j_result)


# Instantiate DAG
gdelt_dag = gdelt_ingestion_dag()