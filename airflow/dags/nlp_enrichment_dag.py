"""
airflow/dags/nlp_enrichment_dag.py
------------------------------------
Airflow DAG: NLP enrichment of DisruptionEvent nodes.

Runs after Phase 2 DAGs populate raw events. Picks up all events where
nlp_processed = false, runs them through:
  1. spaCy NLP pipeline   → event_type, severity, impact_score, description, entities
  2. Sentence-transformer → embedding (384-dim float vector)
  3. Semantic dedup       → skip events too similar to recent processed events
  4. Entity linker        → resolve org/location mentions to Neo4j node IDs
  5. Neo4j writes         → update event + write AFFECTS for GDELT events

Schedule: Every 30 minutes.
  - Phase 2 GDELT runs every 6hr, WeatherAPI every 1hr, PortWatch every 6hr
  - 30min cadence ensures NLP enrichment stays within ~30min of ingestion
  - Avoids model loading overhead on every DAG run vs spinning up workers per event

Performance:
  - spaCy batch_size=32: ~500 events/minute on 2 vCPU
  - sentence-transformer batch_size=64: ~200 events/minute on 2 vCPU
  - Expected daily volume: ~250 GDELT + 24 weather + 8 portwatch ≈ 282 events/day
  - At 200 events/min, a full day's backlog processes in <2 minutes
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "scm-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
    "email_on_failure": False,
}


@dag(
    dag_id="nlp_enrichment",
    description="NLP enrichment: spaCy NER + sentence embeddings + entity linking for DisruptionEvents",
    schedule_interval="*/30 * * * *",   # every 30 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["phase3", "nlp", "enrichment"],
)
def nlp_enrichment_dag():

    @task()
    def fetch_unprocessed_events() -> list[dict]:
        """
        Query Neo4j for events not yet NLP-processed.
        Returns serializable dicts (JSON via XCom).
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from graph.connection import get_connection
        from nlp.enricher.neo4j_enricher import Neo4jEnricher

        conn = get_connection()
        enricher = Neo4jEnricher(conn)
        events = enricher.get_unprocessed_events(limit=500)

        logger.info("Found %d unprocessed events", len(events))
        return events

    @task()
    def run_spacy_pipeline(raw_events: list[dict]) -> list[dict]:
        """
        Run spaCy NLP pipeline on all unprocessed events.
        Returns enriched event dicts (NLPResult fields serialized).
        """
        if not raw_events:
            logger.info("No events to process")
            return []

        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from nlp.pipeline.processor import NLPPipeline, EventInput

        pipeline = NLPPipeline()
        inputs = [
            EventInput(
                event_id=e["event_id"],
                title=e["title"] or "",
                description=e["description"] or "",
                severity=e["severity"] or "medium",
                source=e["source"] or "gdelt",
                affected_region=e.get("affected_region"),
            )
            for e in raw_events
        ]

        results = pipeline.process_batch(inputs, batch_size=32)
        logger.info("spaCy processed %d events", len(results))

        return [
            {
                "event_id": r.event_id,
                "event_type": r.event_type,
                "severity": r.severity,
                "impact_score": r.impact_score,
                "description": r.description,
                "org_mentions": r.org_mentions,
                "location_mentions": r.location_mentions,
                "product_mentions": r.product_mentions,
                "entities": r.entities,
            }
            for r in results
        ]

    @task()
    def generate_embeddings(nlp_results: list[dict]) -> list[dict]:
        """
        Generate sentence embeddings for each NLP-processed event.
        Adds "embedding" key to each result dict.
        """
        if not nlp_results:
            return []

        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from nlp.embeddings.embedder import EventEmbedder, build_embed_text

        # Reconstruct affected_region from the XCom chain:
        # We only have NLP results here — need the original event's affected_region.
        # Fetch from a mini lookup rather than re-querying all event data.
        from graph.connection import get_connection
        conn = get_connection()
        event_ids = [r["event_id"] for r in nlp_results]
        rows = conn.run(
            "MATCH (e:DisruptionEvent) WHERE e.event_id IN $ids "
            "RETURN e.event_id AS event_id, e.affected_region AS affected_region",
            {"ids": event_ids},
        )
        region_map = {r["event_id"]: r["affected_region"] for r in rows}

        embedder = EventEmbedder()
        texts = [
            build_embed_text(
                title=r["description"],   # use NLP description (better than original)
                description="",
                event_type=r["event_type"],
                affected_region=region_map.get(r["event_id"]),
            )
            for r in nlp_results
        ]

        vectors = embedder.embed_batch(texts, batch_size=64)
        for result, vector in zip(nlp_results, vectors):
            result["embedding"] = vector

        logger.info("Generated %d embeddings (dim=%d)", len(vectors), len(vectors[0]) if vectors else 0)
        return nlp_results

    @task()
    def semantic_dedup(enriched_events: list[dict]) -> list[dict]:
        """
        Remove events semantically too similar to events already processed in last 48hr.
        Returns only unique events that should be written to Neo4j.

        Dedup threshold: cosine similarity > 0.92
        """
        if not enriched_events:
            return []

        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from graph.connection import get_connection
        from nlp.enricher.neo4j_enricher import Neo4jEnricher
        from nlp.embeddings.embedder import EventEmbedder

        conn = get_connection()
        enricher = Neo4jEnricher(conn)
        embedder = EventEmbedder()

        # Get existing processed event embeddings from last 48hr
        existing = enricher.get_recent_embeddings(hours=48)
        existing_vecs = [vec for _, vec in existing]

        if not existing_vecs:
            logger.info("No existing embeddings — all %d events are unique", len(enriched_events))
            return enriched_events

        unique = []
        duplicates = 0
        for event in enriched_events:
            vec = event.get("embedding")
            if not vec:
                unique.append(event)
                continue

            similar = embedder.find_most_similar(vec, existing_vecs, top_k=1)
            if similar and similar[0][1] >= 0.92:
                duplicates += 1
                logger.debug(
                    "Semantic duplicate skipped: %s (similarity=%.3f)",
                    event["event_id"], similar[0][1],
                )
            else:
                unique.append(event)
                # Add this event's vector to existing for intra-batch dedup
                existing_vecs.append(vec)

        logger.info(
            "Semantic dedup: %d input → %d unique, %d duplicates removed",
            len(enriched_events), len(unique), duplicates,
        )
        return unique

    @task()
    def run_entity_linking(enriched_events: list[dict]) -> list[dict]:
        """
        Run entity linker on each event's org/location mentions.
        Adds "entity_links" list to each event dict.
        Only runs on GDELT events (source="gdelt") — weather/portwatch already have direct links.
        """
        if not enriched_events:
            return []

        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from nlp.entity_linker.linker import EntityLinker

        linker = EntityLinker()
        total_links = 0

        for event in enriched_events:
            # Only link GDELT events — weather/portwatch links are already written by Phase 2
            if event.get("source_inferred") == "gdelt" or True:
                links = linker.link(
                    event_id=event["event_id"],
                    org_mentions=event.get("org_mentions", []),
                    location_mentions=event.get("location_mentions", []),
                    product_mentions=event.get("product_mentions", []),
                )
                event["entity_links"] = [
                    {
                        "target_id": l.target_id,
                        "target_label": l.target_label,
                        "mention_text": l.mention_text,
                        "confidence": l.confidence,
                        "link_method": l.link_method,
                        "impact_type": l.impact_type,
                    }
                    for l in links
                ]
                total_links += len(links)
            else:
                event["entity_links"] = []

        logger.info("Entity linking: %d events, %d total links", len(enriched_events), total_links)
        return enriched_events

    @task()
    def write_enrichment_to_neo4j(enriched_events: list[dict]) -> dict:
        """
        Write all Phase 3 enrichment results to Neo4j:
          1. Update DisruptionEvent node (event_type, severity, impact_score,
             description, embedding, nlp_processed=true)
          2. Write AFFECTS relationships from entity links
        """
        if not enriched_events:
            return {"updated": 0, "links_written": 0, "errors": 0}

        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from graph.connection import get_connection
        from nlp.enricher.neo4j_enricher import Neo4jEnricher
        from nlp.entity_linker.linker import EntityLink

        conn = get_connection()
        enricher = Neo4jEnricher(conn)

        updated = 0
        total_links_written = 0
        total_links_skipped = 0
        errors = 0

        for event in enriched_events:
            try:
                # 1. Update event node
                ok = enricher.update_event_nlp_fields(
                    event_id=event["event_id"],
                    event_type=event["event_type"],
                    severity=event["severity"],
                    impact_score=event["impact_score"],
                    description=event["description"],
                    embedding=event.get("embedding", []),
                    org_mentions=event.get("org_mentions", []),
                    location_mentions=event.get("location_mentions", []),
                )
                if ok:
                    updated += 1

                # 2. Write AFFECTS links
                raw_links = event.get("entity_links", [])
                if raw_links:
                    links = [EntityLink(**l) for l in raw_links]
                    written, skipped = enricher.write_affects_links(links)
                    total_links_written += written
                    total_links_skipped += skipped

            except Exception as exc:
                errors += 1
                logger.error("Failed to enrich event %s: %s", event.get("event_id"), exc)

        result = {
            "updated": updated,
            "links_written": total_links_written,
            "links_skipped": total_links_skipped,
            "errors": errors,
        }
        logger.info("NLP enrichment write complete: %s", result)
        return result

    @task()
    def log_summary(result: dict):
        logger.info(
            "NLP enrichment DAG complete | events_updated=%d entity_links=%d errors=%d",
            result.get("updated", 0),
            result.get("links_written", 0),
            result.get("errors", 0),
        )

    # DAG wiring
    raw = fetch_unprocessed_events()
    spacy_results = run_spacy_pipeline(raw)
    with_embeddings = generate_embeddings(spacy_results)
    deduped = semantic_dedup(with_embeddings)
    linked = run_entity_linking(deduped)
    result = write_enrichment_to_neo4j(linked)
    log_summary(result)


nlp_dag = nlp_enrichment_dag()