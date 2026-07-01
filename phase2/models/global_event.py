# phase2/models/global_event.py

from pydantic import BaseModel, Field, model_validator
from typing import Optional
from enum import Enum
import hashlib


class EventType(str, Enum):
    earthquake    = "earthquake"
    flood         = "flood"
    port_congestion = "port_congestion"
    labor_strike  = "labor_strike"
    export_ban    = "export_ban"
    cyber         = "cyber"
    weather       = "weather"
    political     = "political"
    fire          = "fire"
    pandemic      = "pandemic"


class SeverityLevel(str, Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class EventSource(str, Enum):
    usgs      = "usgs"
    gdelt     = "gdelt"
    portwatch = "portwatch"
    open_meteo = "open_meteo"
    newsapi   = "newsapi"
    manual    = "manual"


class GlobalEvent(BaseModel):
    event_id: str = Field(..., description="Deterministic MD5 hash — never uuid4()")
    event_type: EventType
    title: str
    description: str
    country: str
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    severity: SeverityLevel
    source: EventSource
    source_tier: str = "tier1" 
    source_url: Optional[str] = None
    occurred_at: str   # ISO 8601
    ingested_at: str   # ISO 8601
    processed: bool = False   # False until Phase 3 NLP runs

    @model_validator(mode="before")
    @classmethod
    def validate_event_id_is_deterministic(cls, values):
        """
        Guard: event_id must look like a 32-char hex string (MD5).
        Reject anything that looks like a uuid4 (contains hyphens in uuid4 format)
        or a raw datetime string.
        """
        eid = values.get("event_id", "")
        if len(eid) != 32 or not all(c in "0123456789abcdef" for c in eid):
            raise ValueError(
                f"event_id must be a 32-character lowercase hex MD5 hash. Got: {eid!r}"
            )
        return values


def make_event_id(source: str, title: str, occurred_at: str) -> str:
    """
    Canonical deterministic ID function.
    Use this everywhere — never inline the MD5 call.
    """
    raw = f"{source}::{title}::{occurred_at}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()