# phase2/ingestion/dedup.py  ← new file

import hashlib
from typing import List
from phase2.models.global_event import GlobalEvent

# In-memory set for within-batch dedup.
# Cross-run dedup is handled by Neo4j MERGE (unique constraint on event_id).
_seen_ids: set = set()


def reset_seen_ids() -> None:
    """Call at the start of each DAG run to clear the in-memory set."""
    global _seen_ids
    _seen_ids = set()


def dedup_events(events: List[GlobalEvent]) -> List[GlobalEvent]:
    """
    Remove duplicates within a single batch using event_id.
    Cross-run duplicates are handled by Neo4j's MERGE + unique constraint.
    """
    global _seen_ids
    unique = []
    for event in events:
        if event.event_id not in _seen_ids:
            _seen_ids.add(event.event_id)
            unique.append(event)
    return unique