"""
ingestion/gdelt/classifier.py
------------------------------
Lightweight rule-based classifier for GDELT articles.

Phase 3 (spaCy + embeddings) will do the heavy NLP.
This module handles Phase 2's job: produce a valid DisruptionEventNode
from raw text without any ML inference, so Airflow can write to Neo4j
immediately and Phase 3 can enrich later.

Design decision: no LLM in Phase 2. Keep ingestion fast and deterministic.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ingestion.gdelt.fetcher import GDELTArticle

# ---------------------------------------------------------------------------
# Keyword → EventType mapping  (order matters — first match wins)
# ---------------------------------------------------------------------------

EVENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("weather",          ["typhoon", "hurricane", "flood", "storm", "cyclone", "drought",
                          "earthquake", "tsunami", "wildfire", "blizzard", "weather"]),
    ("natural_disaster", ["earthquake", "tsunami", "volcanic", "landslide"]),
    ("geopolitical",     ["sanction", "tariff", "war", "conflict", "blockade", "embargo",
                          "strait", "tension", "geopolit", "military", "taiwan strait",
                          "south china sea", "red sea", "suez"]),
    ("labor",            ["strike", "union", "walkout", "labor dispute", "worker",
                          "dock worker", "port worker", "protest"]),
    ("cyber",            ["cyber", "ransomware", "hack", "malware", "data breach",
                          "it outage", "system outage"]),
    ("logistics",        ["congestion", "delay", "backlog", "shortage", "bottleneck",
                          "port closure", "shipping", "freight", "logistics", "supply chain"]),
]

# Country / city → region_id  (extend to match your seed Region nodes)
LOCATION_TO_REGION: dict[str, str] = {
    # APAC
    "taiwan": "APAC", "china": "APAC", "japan": "APAC", "south korea": "APAC",
    "korea": "APAC", "singapore": "APAC", "malaysia": "APAC", "vietnam": "APAC",
    "thailand": "APAC", "philippines": "APAC", "indonesia": "APAC", "australia": "APAC",
    "hong kong": "APAC", "kaohsiung": "APAC", "busan": "APAC", "shanghai": "APAC",
    # EU
    "europe": "EU", "germany": "EU", "netherlands": "EU", "rotterdam": "EU",
    "france": "EU", "uk": "EU", "united kingdom": "EU", "spain": "EU",
    "italy": "EU", "poland": "EU", "belgium": "EU",
    # NA
    "united states": "NA", "usa": "NA", "canada": "NA", "mexico": "NA",
    "los angeles": "NA", "long beach": "NA", "new york": "NA", "houston": "NA",
    # LATAM
    "latin america": "LATAM", "brazil": "LATAM", "chile": "LATAM",
    "colombia": "LATAM", "argentina": "LATAM", "peru": "LATAM",
}

# Severity based on event_type + keywords  (default: medium)
SEVERITY_RULES: dict[str, str] = {
    "natural_disaster": "critical",
    "weather":          "high",
    "geopolitical":     "high",
    "labor":            "medium",
    "cyber":            "high",
    "logistics":        "medium",
}

CRITICAL_KEYWORDS = ["shutdown", "closure", "blockade", "war", "critical shortage",
                     "forced closure", "evacuation", "tsunami", "earthquake"]


def classify_event_type(text: str) -> str:
    """Return best-match event_type from title+description text."""
    lower = text.lower()
    for event_type, keywords in EVENT_TYPE_RULES:
        if any(kw in lower for kw in keywords):
            return event_type
    return "logistics"   # safe default for supply-chain context


def infer_region(text: str) -> str | None:
    """Return region_id from location mentions in text, or None."""
    lower = text.lower()
    for location, region_id in LOCATION_TO_REGION.items():
        if location in lower:
            return region_id
    return None


def infer_severity(event_type: str, text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in CRITICAL_KEYWORDS):
        return "critical"
    return SEVERITY_RULES.get(event_type, "medium")


def article_to_event_fields(article: GDELTArticle) -> dict:
    """
    Convert a GDELTArticle into the field dict needed to build a DisruptionEventNode.
    Phase 3 will overwrite: event_type, severity, impact_score, description.

    Returns a plain dict (not the Pydantic model) — the DAG assembles the final node.
    """
    combined_text = f"{article.title}"

    event_type = classify_event_type(combined_text)
    region_hint = infer_region(combined_text)
    severity = infer_severity(event_type, combined_text)

    return {
        "event_type": event_type,
        "title": article.title[:200],          # Neo4j String — cap length
        "description": article.title,          # Phase 3 will replace with summary
        "severity": severity,
        "source": "gdelt",
        "source_url": article.url,
        "affected_region": region_hint,
        "started_at": article.published_at,
        "ended_at": None,
        "is_resolved": False,
        "impact_score": 0.5,                   # Phase 3 NLP will compute real score
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }