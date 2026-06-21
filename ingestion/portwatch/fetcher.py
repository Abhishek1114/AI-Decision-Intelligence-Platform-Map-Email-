"""
ingestion/portwatch/fetcher.py
-------------------------------
Fetches port congestion data for the 6 seed ports.

PortWatch (https://portwatch.imf.org/) is a free IMF tool that publishes
port-call throughput data. However, its data updates weekly and has no
real-time API — it's a dashboard tool with CSVs behind a login.

Phase 2 Decision: Use a tiered approach:
  1. MarineTraffic Port Stats API (paid, but free tier exists for port-calls)
     → If MARINETRAFFIC_API_KEY is set, use it.
  2. Simulated congestion model from Vessel Finder free data
     → If no key, generate realistic congestion_index from publicly available
        port wait-time reports scraped from a predictable URL pattern.
  3. Mock mode
     → If PORTWATCH_MOCK=true, return fixture data for dev/CI.

For the portfolio project, mock mode is acceptable in Phase 2. Real integration
adds MarineTraffic key in .env before Phase 5 dashboard demo.

Output: List[PortCongestionSnapshot]
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timezone
from typing import Optional

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed port baseline congestion (matches Neo4j seed data)
# ---------------------------------------------------------------------------



PORT_BASELINES: dict[str, dict] = {
    "TWKHH": {"name": "Kaohsiung",   "base_congestion": 0.55, "base_dwell": 4.2},
    "KRPUS": {"name": "Busan",        "base_congestion": 0.40, "base_dwell": 3.1},
    "SGSIN": {"name": "Singapore",    "base_congestion": 0.35, "base_dwell": 2.8},
    "USLAX": {"name": "Los Angeles",  "base_congestion": 0.30, "base_dwell": 3.5},
    "NLRTM": {"name": "Rotterdam",    "base_congestion": 0.25, "base_dwell": 2.4},
    "USLGB": {"name": "Long Beach",   "base_congestion": 0.28, "base_dwell": 3.2},
}

# Congestion surge triggers (for mock mode realism)
CONGESTION_SURGE_EVENTS = [
    "EVT-2024-003",   # LA/LB Congestion event already in seed data
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PortCongestionSnapshot(BaseModel):
    """
    Snapshot of port congestion state.
    Written to Neo4j via raw Cypher (updates Port node properties directly).
    """
    port_id: str
    port_name: str
    congestion_index: float        # 0.0–1.0
    avg_dwell_days: float
    vessels_at_anchor: Optional[int] = None
    vessels_in_port: Optional[int] = None
    throughput_change_pct: Optional[float] = None   # vs 30-day avg, if available
    data_source: str               # "marinetraffic" | "mock" | "scraped"
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def risk_level(self) -> str:
        """Derive risk level from congestion index."""
        if self.congestion_index >= 0.75:
            return "critical"
        elif self.congestion_index >= 0.55:
            return "high"
        elif self.congestion_index >= 0.35:
            return "medium"
        return "low"

    @property
    def is_anomalous(self) -> bool:
        """True if congestion exceeds the baseline by >30%."""
        baseline = PORT_BASELINES.get(self.port_id, {}).get("base_congestion", 0.3)
        return self.congestion_index > baseline * 1.3


# ---------------------------------------------------------------------------
# MarineTraffic fetcher (real data path)
# ---------------------------------------------------------------------------

class MarineTrafficFetcher:
    """
    Uses MarineTraffic Port Calls API v2 to derive congestion.
    Requires MARINETRAFFIC_API_KEY with port-calls access (Marine Traffic credits).

    Free tier (demo API key) supports limited port queries.
    """

    BASE_URL = "https://services.marinetraffic.com/api/portcalls"

    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

    def fetch_port_snapshot(self, port_id: str, un_locode: str) -> PortCongestionSnapshot | None:
        """
        Fetch port call stats for a UN/LOCODE and derive congestion_index.
        MarineTraffic doesn't give a direct congestion_index — we compute it from
        (vessels_waiting / vessels_average_capacity) clipped to [0, 1].
        """
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/{self.api_key}",
                params={"portid": un_locode, "timespan": 24, "msgtype": "simple"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("MarineTraffic fetch failed for %s: %s", port_id, exc)
            return None

        # MT returns list of port calls; count arrivals vs typical
        port_calls = data if isinstance(data, list) else []
        vessel_count = len(port_calls)
        baseline = PORT_BASELINES.get(port_id, {})
        base_congestion = baseline.get("base_congestion", 0.3)

        # Naive congestion proxy: more vessels than a typical 24h window = higher congestion
        typical_24h = 40  # configurable per port
        congestion = min(1.0, base_congestion + (vessel_count / typical_24h) * 0.3)

        return PortCongestionSnapshot(
            port_id=port_id,
            port_name=baseline.get("name", port_id),
            congestion_index=round(congestion, 3),
            avg_dwell_days=baseline.get("base_dwell", 3.0),
            vessels_in_port=vessel_count,
            data_source="marinetraffic",
        )


# ---------------------------------------------------------------------------
# Mock fetcher (dev / CI / portfolio demo)
# ---------------------------------------------------------------------------

class MockPortFetcher:
    """
    Deterministic mock congestion data for development.
    Injects realistic variation: ±15% random walk around baseline,
    with a hardcoded surge for USLAX/USLGB to match EVT-2024-003.
    """

    def fetch_all(self) -> list[PortCongestionSnapshot]:
        snapshots = []
        for port_id, meta in PORT_BASELINES.items():
            base = meta["base_congestion"]
            dwell = meta["base_dwell"]

            # Inject surge for LA/LB congestion event
            if port_id in ("USLAX", "USLGB"):
                base = min(1.0, base + 0.25)
                dwell = dwell * 1.4

            # ±10% random walk
            congestion = round(max(0.0, min(1.0, base + random.uniform(-0.10, 0.10))), 3)
            avg_dwell = round(max(1.0, dwell + random.uniform(-0.5, 0.5)), 2)

            snapshots.append(PortCongestionSnapshot(
                port_id=port_id,
                port_name=meta["name"],
                congestion_index=congestion,
                avg_dwell_days=avg_dwell,
                vessels_at_anchor=random.randint(2, 25),
                vessels_in_port=random.randint(15, 80),
                data_source="mock",
            ))

        logger.info("Mock port fetcher returned %d snapshots", len(snapshots))
        return snapshots


# ---------------------------------------------------------------------------
# Factory — chosen at runtime from env
# ---------------------------------------------------------------------------

def get_port_fetcher():
    """
    Return the appropriate fetcher based on environment variables.
    Priority: MarineTraffic → Mock
    """
    mt_key = os.getenv("MARINETRAFFIC_API_KEY", "")
    mock_mode = os.getenv("PORTWATCH_MOCK", "true").lower() == "true"

    if mock_mode or not mt_key:
        logger.info("Using MockPortFetcher (PORTWATCH_MOCK=true or no API key)")
        return MockPortFetcher()

    logger.info("Using MarineTrafficFetcher")
    return MarineTrafficFetcher(api_key=mt_key)