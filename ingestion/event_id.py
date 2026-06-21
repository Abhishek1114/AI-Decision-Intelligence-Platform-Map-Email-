"""
ingestion/event_id.py
----------------------
Centralized event_id generation for all Phase 2 sources.

Convention: EVT-{YYYYMMDD}-{SOURCE_PREFIX}-{SEQ}
  - EVT-20240815-GD-001  (GDELT)
  - EVT-20240815-WX-001  (WeatherAPI)
  - EVT-20240815-PW-001  (PortWatch)

The seq is a per-run counter stored in Airflow XCom (or a simple shared counter
when running outside Airflow). Using MERGE in Neo4j means duplicate event_ids
from re-runs are idempotent — they update rather than duplicate.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


_COUNTERS: dict[str, int] = {}
_LOCK = threading.Lock()

SOURCE_PREFIXES = {
    "gdelt":      "GD",
    "weatherapi": "WX",
    "portwatch":  "PW",
    "manual":     "MN",
}


def generate_event_id(source: str, date: datetime | None = None) -> str:
    """
    Generate a unique, sortable event_id.

    Args:
        source:  One of "gdelt" | "weatherapi" | "portwatch" | "manual"
        date:    Datetime for the YYYYMMDD portion (defaults to UTC now)

    Returns:
        str: e.g. "EVT-20240815-GD-042"
    """
    if date is None:
        date = datetime.now(timezone.utc)

    prefix = SOURCE_PREFIXES.get(source, "XX")
    date_str = date.strftime("%Y%m%d")
    counter_key = f"{date_str}-{prefix}"

    with _LOCK:
        _COUNTERS[counter_key] = _COUNTERS.get(counter_key, 0) + 1
        seq = _COUNTERS[counter_key]

    return f"EVT-{date_str}-{prefix}-{seq:03d}"


def reset_counters():
    """Call at the start of each Airflow DAG run to reset per-run sequence numbers."""
    with _LOCK:
        _COUNTERS.clear()