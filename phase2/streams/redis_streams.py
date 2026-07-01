# phase2/streams/redis_streams.py

import redis
import json
from datetime import datetime
from typing import Optional

from typing import List
from phase2.models.global_event import GlobalEvent
import json

REDIS_URL = "redis://redis:6379"

# Named topics — order is the processing pipeline
TOPIC_RAW       = "events.raw"
TOPIC_ENRICHED  = "events.enriched"
TOPIC_MATCHED   = "alerts.matched"
TOPIC_DELIVERED = "alerts.delivered"

# Consumer group names
GROUP_NORMALISER = "normaliser-workers"
GROUP_MATCHER    = "customer-matcher-workers"


def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


class EventProducer:
    """Writes raw events to events.raw stream."""

    def __init__(self):
        self.r = get_redis()

    def publish_raw(self, source: str, raw_payload: dict) -> str:
        """
        Publish a raw event dict to events.raw.
        Returns the Redis stream entry ID.
        """
        message = {
            "source": source,
            "received_at": datetime.utcnow().isoformat(),
            "payload": json.dumps(raw_payload),
        }
        entry_id = self.r.xadd(TOPIC_RAW, message, maxlen=50_000, approximate=True)
        return entry_id

    def publish_normalised(self, event_dict: dict) -> str:
        """Write a normalised GlobalEvent dict to events.enriched."""
        message = {
            "event": json.dumps(event_dict),
            "normalised_at": datetime.utcnow().isoformat(),
        }
        return self.r.xadd(TOPIC_ENRICHED, message, maxlen=50_000, approximate=True)


class EventConsumer:
    """Reads from a Redis stream topic using consumer groups."""

    def __init__(self, topic: str, group: str, consumer_name: str):
        self.r = get_redis()
        self.topic = topic
        self.group = group
        self.consumer_name = consumer_name
        self._ensure_group()

    def _ensure_group(self):
        try:
            self.r.xgroup_create(self.topic, self.group, id="0", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def read(self, count: int = 10, block_ms: int = 5000):
        """
        Read up to `count` unacknowledged messages.
        Blocks for `block_ms` ms if stream is empty.
        Returns list of (entry_id, fields_dict) tuples.
        """
        results = self.r.xreadgroup(
            groupname=self.group,
            consumername=self.consumer_name,
            streams={self.topic: ">"},
            count=count,
            block=block_ms,
        )
        if not results:
            return []
        entries = []
        for _stream, messages in results:
            for entry_id, fields in messages:
                entries.append((entry_id, fields))
        return entries

    def ack(self, entry_id: str):
        self.r.xack(self.topic, self.group, entry_id)

class GlobalEventProducer:
    """
    Publishes GlobalEvent objects to the events.enriched Redis stream.
    Used by all Airflow DAGs after dedup.
    """

    def __init__(self):
        self.producer = EventProducer()

    def publish_batch(self, events: List[GlobalEvent]) -> List[str]:
        """
        Publish a list of GlobalEvent objects to events.enriched.
        Returns list of Redis stream entry IDs.
        """
        ids = []
        for event in events:
            try:
                entry_id = self.producer.publish_normalised(event.model_dump())
                ids.append(entry_id)
            except Exception as e:
                print(f"[GlobalEventProducer] Failed to publish {event.event_id}: {e}")
        return ids