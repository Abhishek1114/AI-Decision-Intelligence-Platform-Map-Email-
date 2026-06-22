"""
nlp/enricher/neo4j_enricher.py
--------------------------------
Writes Phase 3 NLP results back to Neo4j:
  1. Updates DisruptionEvent nodes with refined fields (event_type, severity,
     impact_score, description, embedding)
  2. Writes [:AFFECTS] relationships for GDELT events (using EntityLinker output)
  3. Semantic dedup: skips writing events whose embeddings are already in the graph

All writes use the existing Phase 1/2 schema — no new nodes or relationship types.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class Neo4jEnricher:
    """
    Writes NLP enrichment results to Neo4j using the existing connection.

    Args:
        conn: Neo4jConnection from graph/connection.py
    """

    def __init__(self, conn):
        self.conn = conn

    # ------------------------------------------------------------------
    # Core update: overwrite placeholder fields from Phase 2
    # ------------------------------------------------------------------

    def update_event_nlp_fields(
        self,
        event_id: str,
        event_type: str,
        severity: str,
        impact_score: float,
        description: str,
        embedding: list[float],
        org_mentions: list[str],
        location_mentions: list[str],
    ) -> bool:
        """
        Update DisruptionEvent node with Phase 3 NLP-computed values.
        Overwrites the Phase 2 placeholders for description, severity, impact_score.

        New properties added to DisruptionEvent in Phase 3:
          - embedding          List<Float>  length=384
          - nlp_processed      Boolean      true after Phase 3 runs
          - org_mentions       List<String>
          - location_mentions  List<String>
          - nlp_processed_at   DateTime
        """
        try:
            self.conn.run_write(
                """
                MATCH (e:DisruptionEvent {event_id: $event_id})
                SET e.event_type        = $event_type,
                    e.severity          = $severity,
                    e.impact_score      = $impact_score,
                    e.description       = $description,
                    e.embedding         = $embedding,
                    e.org_mentions      = $org_mentions,
                    e.location_mentions = $location_mentions,
                    e.nlp_processed     = true,
                    e.nlp_processed_at  = datetime(),
                    e.updated_at        = datetime()
                """,
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "severity": severity,
                    "impact_score": impact_score,
                    "description": description,
                    "embedding": embedding,
                    "org_mentions": org_mentions,
                    "location_mentions": location_mentions,
                },
            )
            return True
        except Exception as exc:
            logger.error("Failed to update event %s NLP fields: %s", event_id, exc)
            return False

    # ------------------------------------------------------------------
    # Entity link writes — GDELT [:AFFECTS] relationships
    # ------------------------------------------------------------------

    def write_affects_links(self, links: list) -> tuple[int, int]:
        """
        Write [:AFFECTS] relationships for entity-linked nodes.
        Skips links with confidence < 0.45 (country-level guesses are too noisy).

        Args:
            links: list of EntityLink from entity_linker.py

        Returns:
            (written, skipped) counts
        """
        from graph.models.relationships import AffectsRel

        CONFIDENCE_THRESHOLD = 0.45
        written = 0
        skipped = 0
        now = datetime.now(timezone.utc)

        for link in links:
            if link.confidence < CONFIDENCE_THRESHOLD:
                skipped += 1
                logger.debug(
                    "Skipping low-confidence link %s→%s (%.2f)",
                    link.event_id, link.target_id, link.confidence,
                )
                continue

            try:
                # Use the existing repo method via raw Cypher to set rel properties
                self.conn.run_write(
                    f"""
                    MATCH (e:DisruptionEvent {{event_id: $event_id}})
                    MATCH (t:{link.target_label} {{{self._pk_field(link.target_label)}: $target_id}})
                    MERGE (e)-[r:AFFECTS]->(t)
                    ON CREATE SET
                        r.impact_type          = $impact_type,
                        r.estimated_delay_days = null,
                        r.confidence           = $confidence,
                        r.detected_at          = datetime($detected_at),
                        r.resolved_at          = null
                    ON MATCH SET
                        r.confidence = CASE WHEN $confidence > r.confidence
                                       THEN $confidence ELSE r.confidence END
                    """,
                    {
                        "event_id": link.event_id,
                        "target_id": link.target_id,
                        "impact_type": link.impact_type,
                        "confidence": link.confidence,
                        "detected_at": now.isoformat(),
                    },
                )
                written += 1
                logger.debug(
                    "Wrote AFFECTS link %s→%s:%s (conf=%.2f, method=%s)",
                    link.event_id, link.target_label, link.target_id,
                    link.confidence, link.link_method,
                )
            except Exception as exc:
                logger.error(
                    "Failed to write AFFECTS link %s→%s: %s",
                    link.event_id, link.target_id, exc,
                )
                skipped += 1

        return written, skipped

    # ------------------------------------------------------------------
    # Semantic dedup helper
    # ------------------------------------------------------------------

    def get_recent_embeddings(self, hours: int = 48) -> list[tuple[str, list[float]]]:
        """
        Fetch (event_id, embedding) for events processed in the last N hours.
        Used to skip semantic duplicates within the dedup window.
        Returns [] if no embeddings exist yet (first run).
        """
        try:
            rows = self.conn.run(
                """
                MATCH (e:DisruptionEvent)
                WHERE e.nlp_processed = true
                  AND e.nlp_processed_at >= datetime() - duration({hours: $hours})
                  AND e.embedding IS NOT NULL
                RETURN e.event_id AS event_id, e.embedding AS embedding
                """,
                {"hours": hours},
            )
            return [(r["event_id"], r["embedding"]) for r in rows]
        except Exception as exc:
            logger.warning("Could not fetch recent embeddings: %s", exc)
            return []

    def get_unprocessed_events(self, limit: int = 500) -> list[dict]:
        """
        Fetch DisruptionEvents not yet processed by Phase 3 NLP.
        Ordered by started_at DESC so newest events are enriched first.
        """
        rows = self.conn.run(
            """
            MATCH (e:DisruptionEvent)
            WHERE (e.nlp_processed IS NULL OR e.nlp_processed = false)
              AND e.is_resolved = false
            RETURN e.event_id      AS event_id,
                   e.title         AS title,
                   e.description   AS description,
                   e.severity      AS severity,
                   e.source        AS source,
                   e.affected_region AS affected_region
            ORDER BY e.started_at DESC
            LIMIT $limit
            """,
            {"limit": limit},
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pk_field(label: str) -> str:
        """Return the primary key property name for a given node label."""
        return {
            "Supplier": "supplier_id",
            "Facility": "facility_id",
            "Port":     "port_id",
            "Route":    "route_id",
        }.get(label, "supplier_id")