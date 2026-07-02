# phase2/ingestion/normaliser.py

from datetime import datetime
from typing import Optional
from phase2.models.global_event import GlobalEvent, make_event_id
from phase2.streams.redis_streams import EventProducer
from phase2.ingestion.neo4j_writer import GlobalEventWriter
from phase2.raw_store.raw_event_store import RawEventStore
from phase2.migrations.migration_002_global_events_schema import SOURCE_TIER_MAP
from typing import List


class EventNormaliser:
    """
    Converts source-specific raw dicts → GlobalEvent → Neo4j node.
    Also publishes normalised event to events.enriched Redis stream.
    """

    def __init__(self):
        self.producer  = EventProducer()
        self.writer    = GlobalEventWriter()
        self.raw_store = RawEventStore()

    def process(self, source: str, raw_dict: dict) -> Optional[GlobalEvent]:
        """
        Main entry point. Called by each Airflow DAG after fetching.
        Returns GlobalEvent if successful, None if skipped (e.g. below threshold).
        """
        # 1. Persist raw payload first — audit trail before any processing
        self.raw_store.save(source=source, payload=raw_dict)

        # 2. Build event_id deterministically
        title       = raw_dict.get("title", "")
        occurred_at = raw_dict.get("occurred_at", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
        event_id    = make_event_id(source, title, occurred_at)

        # 3. Check dedup — skip if already in Neo4j
        if self.writer.exists(event_id):
            return None  # Already processed — DAG re-run, not a new event

        # 4. Build GlobalEvent model — Pydantic validation runs here
        try:
            source_tier = SOURCE_TIER_MAP.get(source, "tier_2")

            event = GlobalEvent(
                event_id    = event_id,
                ingested_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                processed   = False,
                source_tier = source_tier,
                **{k: v for k, v in raw_dict.items() if k not in ("event_id", "ingested_at")},
            )
        except Exception as e:
            print(f"[normaliser] Validation failed for {source} event: {e}")
            return None

        # 5. Write to Neo4j
        self.writer.upsert(event)

        # 6. Publish to events.enriched stream for downstream workers
        self.producer.publish_normalised(event.model_dump())

        return event

def normalise_batch(source: str, raw_records: list) -> List[GlobalEvent]:
    """
    Batch normalise raw records from a given source into GlobalEvent models.
    Skips records that fail validation. Used by all Airflow DAGs.
    """
    from phase2.ingestion.sources.weatherapi import normalise_weatherapi
    from phase2.ingestion.sources.portwatch import normalise_portwatch

    NORMALISERS = {
        "open_meteo": normalise_weatherapi,   # WeatherAPI replaced Open-Meteo
        "portwatch":  normalise_portwatch,
    }

    normalise_fn = NORMALISERS.get(source)
    if not normalise_fn:
        print(f"[normalise_batch] No normaliser registered for source: {source}")
        return []

    events = []
    for record in raw_records:
        try:
            raw_dict = normalise_fn(record)
            if raw_dict is None:
                continue   # Below threshold — normaliser explicitly skipped it

            title       = raw_dict.get("title", "")
            occurred_at = raw_dict.get("occurred_at", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
            event_id    = make_event_id(source, title, occurred_at)
            source_tier = SOURCE_TIER_MAP.get(source, "tier2")

            event = GlobalEvent(
                event_id    = event_id,
                ingested_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                processed   = False,
                source_tier = source_tier,
                **{k: v for k, v in raw_dict.items()
                   if k not in ("event_id", "ingested_at", "source_tier")},
            )
            events.append(event)
        except Exception as e:
            print(f"[normalise_batch] Skipping record from {source}: {e}")
    return events