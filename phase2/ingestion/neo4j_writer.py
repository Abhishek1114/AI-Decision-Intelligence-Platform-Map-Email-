# phase2/ingestion/neo4j_writer.py

import os
from neo4j import GraphDatabase
from phase2.models.global_event import GlobalEvent

from typing import List
from phase2.models.global_event import GlobalEvent


URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "supply_chain_secret")

# Cypher: MERGE on event_id (unique constraint) → idempotent
UPSERT_CYPHER = """
MERGE (e:GlobalEvent {event_id: $event_id})
ON CREATE SET
    e.event_type  = $event_type,
    e.title       = $title,
    e.description = $description,
    e.country     = $country,
    e.region      = $region,
    e.city        = $city,
    e.severity    = $severity,
    e.source      = $source,
    e.source_tier = $source_tier,
    e.source_url  = $source_url,
    e.occurred_at = $occurred_at,
    e.ingested_at = $ingested_at,
    e.processed   = false
ON MATCH SET
    e.severity    = $severity,
    e.source_tier = $source_tier,
    e.ingested_at = $ingested_at
"""

# Separate SET for location — only when lat/lon are present
SET_LOCATION_CYPHER = """
MATCH (e:GlobalEvent {event_id: $event_id})
SET e.location = point({latitude: $latitude, longitude: $longitude})
"""

EXISTS_CYPHER = """
MATCH (e:GlobalEvent {event_id: $event_id}) RETURN count(e) AS n
"""


class GlobalEventWriter:

    def __init__(self):
        self.driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    def upsert(self, event: GlobalEvent) -> None:
        params = event.model_dump()
        # Remove lat/lon — stored as point(), handled separately
        lat = params.pop("latitude", None)
        lon = params.pop("longitude", None)

        with self.driver.session() as session:
            session.run(UPSERT_CYPHER, **params)

            # Only set location if we have coordinates
            if lat is not None and lon is not None:
                session.run(SET_LOCATION_CYPHER,
                            event_id=event.event_id,
                            latitude=lat,
                            longitude=lon)

    def exists(self, event_id: str) -> bool:
        with self.driver.session() as session:
            result = session.run(EXISTS_CYPHER, event_id=event_id)
            return result.single()["n"] > 0

    def close(self):
        self.driver.close()

def write_events(events: List[GlobalEvent]) -> dict:
    """
    Batch write GlobalEvent list to Neo4j.
    Returns stats dict for DAG logging.
    Used by all Airflow DAGs.
    """
    writer  = GlobalEventWriter()
    created = 0
    skipped = 0
    errors  = 0

    for event in events:
        try:
            if writer.exists(event.event_id):
                skipped += 1
            else:
                writer.upsert(event)
                created += 1
        except Exception as e:
            print(f"[write_events] Failed to write {event.event_id}: {e}")
            errors += 1

    writer.close()
    return {"created": created, "skipped": skipped, "errors": errors}