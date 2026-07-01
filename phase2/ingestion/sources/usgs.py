# phase2/ingestion/sources/usgs.py

import requests
from datetime import datetime, timedelta
from typing import List

USGS_FEED_1HR = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
USGS_API      = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# Only earthquakes at or above this magnitude get ingested
MIN_MAGNITUDE = 5.0


def fetch_recent_earthquakes(hours_back: int = 1) -> List[dict]:
    """
    Try the real-time feed first (significant earthquakes, last hour).
    Fall back to FDSNWS query for historical windows.
    """
    if hours_back <= 1:
        # Real-time feed — no params, always fresh
        response = requests.get(USGS_FEED_1HR, timeout=15)

        print("Status:", response.status_code)
        print("URL:", response.url)

        data = response.json()
        print("Features:", len(data.get("features", [])))

        if response.status_code == 200:
            data = response.json()
            features = data.get("features", [])
            # Feed includes all significant EQs — still apply magnitude filter
            return [f for f in features
                    if f["properties"].get("mag", 0) >= MIN_MAGNITUDE]

    # Fallback: parameterised historical query (original code unchanged below)
    end_time   = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours_back)
    params = {
        "format":       "geojson",
        "starttime":    start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime":      end_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": MIN_MAGNITUDE,
        "orderby":      "time",
    }
    response = requests.get(USGS_API, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])

def normalise_usgs(feature: dict) -> dict:
    """
    Normalise a single USGS GeoJSON feature to our internal format.
    Returns a dict ready for GlobalEvent Pydantic model construction.
    """
    props = feature["properties"]
    coords = feature["geometry"]["coordinates"]  # [lon, lat, depth]
    longitude, latitude = coords[0], coords[1]

    magnitude = props.get("mag", 0.0)
    place     = props.get("place", "Unknown")
    title     = f"Earthquake M{magnitude} — {place}"
    occurred  = datetime.utcfromtimestamp(
        props["time"] / 1000
    ).strftime("%Y-%m-%dT%H:%M:%S")

    # Severity mapping: USGS magnitude → our enum
    if magnitude >= 7.0:
        severity = "critical"
    elif magnitude >= 6.0:
        severity = "high"
    elif magnitude >= 5.5:
        severity = "medium"
    else:
        severity = "low"

    # Extract country from place string (best-effort — Phase 3 NLP improves this)
    country = _extract_country_from_place(place)

    return {
        "event_type":  "earthquake",
        "title":       title,
        "description": f"USGS: {title}. Magnitude {magnitude}. Depth {coords[2]}km. "
                       f"Location: {place}.",
        "country":     country,
        "region":      place,
        "latitude":    latitude,
        "longitude":   longitude,
        "severity":    severity,
        "source":      "usgs",
        "source_url":  props.get("url", ""),
        "occurred_at": occurred,
    }


def _extract_country_from_place(place: str) -> str:
    """
    USGS place strings end with the country name after the last comma.
    e.g. '12km NE of Hsinchu, Taiwan' → 'Taiwan'
    Falls back to 'Unknown'.
    """
    if "," in place:
        return place.split(",")[-1].strip()
    return "Unknown"