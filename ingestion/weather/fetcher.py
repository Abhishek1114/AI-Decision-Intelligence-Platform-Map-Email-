"""
ingestion/weather/fetcher.py
-----------------------------
Fetches weather alerts and current conditions for port and facility locations
using WeatherAPI (https://www.weatherapi.com/).

API choice: WeatherAPI over NOAA because:
  - Single REST endpoint covers global locations (NOAA is US-only)
  - Alerts endpoint available on Free plan (1M calls/month)
  - Returns structured JSON with severity + headline — no parsing needed
  - Supports lat/lon queries → matches our Neo4j Point type directly

Endpoints used:
  - /v1/current.json     → current conditions (wind, precip, visibility)
  - /v1/alerts.json      → active weather alerts at a location (Free plan)
  - /v1/forecast.json    → 3-day forecast (used to detect upcoming risk windows)

Free plan limits: 1,000,000 calls/month, 1M req/day max.
For 12 locations × 3 endpoints × 24 runs/day = 864 calls/day — well within limits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

WEATHERAPI_BASE = "https://api.weatherapi.com/v1"

# Severity mapping from WeatherAPI alert severity strings → our RiskLevel enum
SEVERITY_MAP = {
    "extreme":   "critical",
    "severe":    "high",
    "moderate":  "medium",
    "minor":     "low",
    "unknown":   "medium",
}

# Wind speed thresholds (kph) that trigger a "weather" disruption event
WIND_THRESHOLD_KPH = 65.0        # Tropical storm force
PRECIP_THRESHOLD_MM = 50.0       # 50mm/hr = heavy flooding risk
VISIBILITY_THRESHOLD_KM = 1.0    # Dense fog / severe reduction


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class WeatherAlert(BaseModel):
    """A single active weather alert at a monitored location."""
    alert_id: str                          # WeatherAPI msgtype+headline hash
    location_id: str                       # port_id or facility_id from our graph
    location_name: str
    latitude: float
    longitude: float
    headline: str
    severity: str                          # "low"|"medium"|"high"|"critical"
    certainty: str                         # WeatherAPI: "Observed"|"Likely"|"Possible"
    event_description: str                 # WeatherAPI "event" field
    effective: Optional[datetime] = None
    expires: Optional[datetime] = None
    areas: str = ""
    raw_severity: str = ""                 # original WeatherAPI severity string
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("effective", "expires", mode="before")
    @classmethod
    def parse_dt(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(v[:19], fmt[:len(fmt)])
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return v


class WeatherCondition(BaseModel):
    """Current weather conditions snapshot (used for threshold-based disruption detection)."""
    location_id: str
    location_name: str
    latitude: float
    longitude: float
    temp_c: float
    wind_kph: float
    precip_mm: float
    visibility_km: float
    condition_text: str
    is_disruption_risk: bool = False       # True if any threshold exceeded
    risk_reason: Optional[str] = None     # Human-readable reason for flag
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MonitoredLocation(BaseModel):
    """A port or facility location we poll WeatherAPI for."""
    location_id: str          # port_id or facility_id
    location_type: str        # "port" | "facility"
    name: str
    latitude: float
    longitude: float
    region_id: str


# ---------------------------------------------------------------------------
# Seed monitored locations (matches Neo4j seed data exactly)
# Phase 2 DAG will also query Neo4j for dynamic locations via repo.
# ---------------------------------------------------------------------------

SEED_MONITORED_LOCATIONS: list[MonitoredLocation] = [
    MonitoredLocation(location_id="TWKHH",  location_type="port",     name="Kaohsiung",         latitude=22.6163,  longitude=120.2647, region_id="APAC"),
    MonitoredLocation(location_id="KRPUS",  location_type="port",     name="Busan",              latitude=35.1796,  longitude=129.0756, region_id="APAC"),
    MonitoredLocation(location_id="SGSIN",  location_type="port",     name="Singapore",          latitude=1.2644,   longitude=103.8222, region_id="APAC"),
    MonitoredLocation(location_id="USLAX",  location_type="port",     name="Los Angeles",        latitude=33.7395,  longitude=-118.2726, region_id="NA"),
    MonitoredLocation(location_id="NLRTM",  location_type="port",     name="Rotterdam",          latitude=51.9225,  longitude=4.4792,  region_id="EU"),
    MonitoredLocation(location_id="USLGB",  location_type="port",     name="Long Beach",         latitude=33.7701,  longitude=-118.1937, region_id="NA"),
    MonitoredLocation(location_id="FAC-001", location_type="facility", name="TSMC Phoenix",      latitude=33.4484,  longitude=-112.0740, region_id="NA"),
    MonitoredLocation(location_id="FAC-002", location_type="facility", name="TSMC Hsinchu",      latitude=24.8138,  longitude=120.9675, region_id="APAC"),
    MonitoredLocation(location_id="FAC-003", location_type="facility", name="Samsung SDI Ulsan", latitude=35.5384,  longitude=129.3114, region_id="APAC"),
    MonitoredLocation(location_id="FAC-004", location_type="facility", name="LG Display Gumi",   latitude=36.1195,  longitude=128.3446, region_id="APAC"),
    MonitoredLocation(location_id="FAC-005", location_type="facility", name="Albemarle Silver",  latitude=35.2271,  longitude=-80.8431, region_id="NA"),
    MonitoredLocation(location_id="FAC-006", location_type="facility", name="SQM Atacama",       latitude=-23.5,    longitude=-68.0,    region_id="LATAM"),
]


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class WeatherAPIFetcher:
    """
    Fetches weather alerts and conditions from WeatherAPI.com.

    Args:
        api_key: WeatherAPI key from WEATHERAPI_KEY env var
        timeout: HTTP timeout in seconds
    """

    def __init__(self, api_key: str, timeout: int = 15):
        if not api_key:
            raise ValueError("WEATHERAPI_KEY is required")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, endpoint: str, params: dict) -> dict:
        params["key"] = self.api_key
        url = f"{WEATHERAPI_BASE}/{endpoint}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_alerts(self, location: MonitoredLocation) -> list[WeatherAlert]:
        """
        Fetch active weather alerts for a specific port/facility location.
        Returns [] if no alerts or if the free plan doesn't return alert data.
        """
        q = f"{location.latitude},{location.longitude}"
        try:
            data = self._get("alerts.json", {"q": q, "alerts": "yes"})
        except requests.RequestException as exc:
            logger.warning("WeatherAPI alerts failed for %s: %s", location.location_id, exc)
            return []

        raw_alerts = data.get("alerts", {}).get("alert", [])
        alerts = []
        for raw in raw_alerts:
            try:
                raw_sev = raw.get("severity", "unknown").lower()
                alert = WeatherAlert(
                    alert_id=_alert_id(location.location_id, raw.get("headline", "")),
                    location_id=location.location_id,
                    location_name=location.name,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    headline=raw.get("headline", ""),
                    severity=SEVERITY_MAP.get(raw_sev, "medium"),
                    raw_severity=raw_sev,
                    certainty=raw.get("certainty", ""),
                    event_description=raw.get("event", ""),
                    effective=raw.get("effective"),
                    expires=raw.get("expires"),
                    areas=raw.get("areas", ""),
                )
                alerts.append(alert)
            except Exception as exc:
                logger.debug("Skipping malformed alert for %s: %s", location.location_id, exc)

        logger.info("Location %s: %d active weather alerts", location.location_id, len(alerts))
        return alerts

    def fetch_current(self, location: MonitoredLocation) -> WeatherCondition | None:
        """
        Fetch current weather conditions and flag disruption risk via thresholds.
        Used when no formal alerts are issued but conditions exceed safety thresholds.
        """
        q = f"{location.latitude},{location.longitude}"
        try:
            data = self._get("current.json", {"q": q})
        except requests.RequestException as exc:
            logger.warning("WeatherAPI current failed for %s: %s", location.location_id, exc)
            return None

        current = data.get("current", {})
        wind_kph = float(current.get("wind_kph", 0))
        precip_mm = float(current.get("precip_mm", 0))
        vis_km = float(current.get("vis_km", 10))

        risk_flags = []
        if wind_kph >= WIND_THRESHOLD_KPH:
            risk_flags.append(f"wind {wind_kph:.0f} kph ≥ threshold {WIND_THRESHOLD_KPH}")
        if precip_mm >= PRECIP_THRESHOLD_MM:
            risk_flags.append(f"precipitation {precip_mm:.0f} mm/hr ≥ threshold {PRECIP_THRESHOLD_MM}")
        if vis_km <= VISIBILITY_THRESHOLD_KM:
            risk_flags.append(f"visibility {vis_km:.1f} km ≤ threshold {VISIBILITY_THRESHOLD_KM}")

        return WeatherCondition(
            location_id=location.location_id,
            location_name=location.name,
            latitude=location.latitude,
            longitude=location.longitude,
            temp_c=float(current.get("temp_c", 0)),
            wind_kph=wind_kph,
            precip_mm=precip_mm,
            visibility_km=vis_km,
            condition_text=current.get("condition", {}).get("text", ""),
            is_disruption_risk=bool(risk_flags),
            risk_reason="; ".join(risk_flags) if risk_flags else None,
        )

    def fetch_all_locations(
        self,
        locations: list[MonitoredLocation] | None = None,
    ) -> tuple[list[WeatherAlert], list[WeatherCondition]]:
        """
        Poll all monitored locations. Called by Airflow DAG.
        Returns (alerts, conditions_with_risk).
        """
        if locations is None:
            locations = SEED_MONITORED_LOCATIONS

        all_alerts: list[WeatherAlert] = []
        risk_conditions: list[WeatherCondition] = []

        for loc in locations:
            alerts = self.fetch_alerts(loc)
            all_alerts.extend(alerts)

            # Only fetch current conditions if no formal alerts exist (avoid double-counting)
            if not alerts:
                cond = self.fetch_current(loc)
                if cond and cond.is_disruption_risk:
                    risk_conditions.append(cond)

        logger.info(
            "Weather fetch complete: %d alerts, %d threshold-breach conditions",
            len(all_alerts), len(risk_conditions),
        )
        return all_alerts, risk_conditions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alert_id(location_id: str, headline: str) -> str:
    """Stable dedup key for a weather alert."""
    import hashlib
    raw = f"{location_id}:{headline}"
    return "WX-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()


def alert_to_event_fields(alert: WeatherAlert) -> dict:
    """
    Convert WeatherAlert → field dict for DisruptionEventNode.
    Called by the Airflow DAG before writing to Neo4j.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return {
        "event_type": "weather",
        "title": alert.headline[:200],
        "description": f"Weather alert at {alert.location_name}: {alert.event_description}. Areas: {alert.areas}",
        "severity": alert.severity,
        "source": "weatherapi",
        "source_url": None,
        "affected_region": None,          # set by DAG from location.region_id
        "started_at": alert.effective or now,
        "ended_at": alert.expires,
        "is_resolved": False,
        "impact_score": _severity_to_score(alert.severity),
        "created_at": now,
        "updated_at": now,
    }


def condition_to_event_fields(cond: WeatherCondition, region_id: str) -> dict:
    """
    Convert a threshold-breach WeatherCondition → field dict for DisruptionEventNode.
    Used when conditions exceed thresholds but no formal alert was issued.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return {
        "event_type": "weather",
        "title": f"Adverse weather conditions at {cond.location_name}",
        "description": f"Threshold breach: {cond.risk_reason}. Condition: {cond.condition_text}",
        "severity": "medium",
        "source": "weatherapi",
        "source_url": None,
        "affected_region": region_id,
        "started_at": now,
        "ended_at": None,
        "is_resolved": False,
        "impact_score": 0.4,
        "created_at": now,
        "updated_at": now,
    }


def _severity_to_score(severity: str) -> float:
    return {"low": 0.2, "medium": 0.45, "high": 0.70, "critical": 0.90}.get(severity, 0.45)