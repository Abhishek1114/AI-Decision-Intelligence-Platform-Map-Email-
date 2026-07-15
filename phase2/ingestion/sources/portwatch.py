# phase2/ingestion/sources/mock_portwatch.py

from datetime import datetime
import random
from typing import List

# Realistic mock data for seed customer ports
# Values rotate slightly each call to simulate real congestion fluctuation
MOCK_PORT_DATA = [
    {
        "locode":       "TWKHH",
        "port_name":    "Port of Kaohsiung",
        "country":      "Taiwan",
        "latitude":     22.5519,
        "longitude":    120.3497,
        "base_congestion": 0.45,   # Normally moderate
    },
    {
        "locode":       "CNSHA",
        "port_name":    "Port of Shanghai",
        "country":      "China",
        "latitude":     31.2304,
        "longitude":    121.4737,
        "base_congestion": 0.60,   # Typically busier
    },
    {
        "locode":       "USLAX",
        "port_name":    "Port of Los Angeles",
        "country":      "United States",
        "latitude":     33.7395,
        "longitude":    -118.2707,
        "base_congestion": 0.50,
    },
    {
        "locode":       "NLRTM",
        "port_name":    "Port of Rotterdam",
        "country":      "Netherlands",
        "latitude":     51.9225,
        "longitude":    4.4792,
        "base_congestion": 0.35,
    },
    {
        "locode":       "INMAA",
        "port_name":    "Chennai Port",
        "country":      "India",
        "latitude":     13.0827,
        "longitude":    80.2707,
        "base_congestion": 0.50,   # TEST: "medium" band midpoint (Novara Pharma)
    },

    # ── Added for Phase 7 customers (Andina Copper, Cascade Memory,
    #    Monsoon Apparel, Pacific Rim AgriFoods) ──────────────────────────────
    {
        "locode":       "CLANF",
        "port_name":    "Puerto Antofagasta",
        "country":      "Chile",
        "latitude":     -23.6509,
        "longitude":    -70.3975,
        "base_congestion": 0.30,   # Bulk mineral port, usually low congestion
    },
    {
        "locode":       "TWTXG",
        "port_name":    "Port of Taichung",
        "country":      "Taiwan",
        "latitude":     24.2833,
        "longitude":    120.5167,
        "base_congestion": 0.70,   # TEST: "high" band midpoint (Cascade Memory)
    },
    {
        "locode":       "USOAK",
        "port_name":    "Port of Oakland",
        "country":      "United States",
        "latitude":     37.7955,
        "longitude":    -122.2781,
        "base_congestion": 0.38,
    },
    {
        "locode":       "BDCGP",
        "port_name":    "Chittagong Port",
        "country":      "Bangladesh",
        "latitude":     22.3569,
        "longitude":    91.7832,
        "base_congestion": 0.95,   # TEST: guaranteed "critical" even at -0.15 noise (Monsoon Apparel)
    },
    {
        "locode":       "GBFXT",
        "port_name":    "Port of Felixstowe",
        "country":      "United Kingdom",
        "latitude":     51.9539,
        "longitude":    1.3512,
        "base_congestion": 0.40,
    },
    {
        "locode":       "IDDUM",
        "port_name":    "Port of Dumai",
        "country":      "Indonesia",
        "latitude":     1.6667,
        "longitude":    101.4500,
        "base_congestion": 0.35,
    },
    {
        "locode":       "SGSIN",
        "port_name":    "Port of Singapore",
        "country":      "Singapore",
        "latitude":     1.2644,
        "longitude":    103.8200,
        "base_congestion": 0.55,   # High-throughput global hub
    },
]


def fetch_port_congestion(locodes: List[str] = None) -> List[dict]:
    """
    Returns mock congestion data that realistically fluctuates.
    Drop-in replacement for real PortWatch API.
    """
    results = []
    for port in MOCK_PORT_DATA:
        if locodes and port["locode"] not in locodes:
            continue

        # Add ±15% random fluctuation to simulate real-world variation
        noise      = random.uniform(-0.15, 0.15)
        congestion = max(0.0, min(1.0, port["base_congestion"] + noise))
        wait_hours = int(congestion * 48)  # Scale: 0→0h, 1.0→48h

        results.append({
            "locode": port["locode"],
            "data": {
                "port_name":         port["port_name"],
                "country":           port["country"],
                "latitude":          port["latitude"],
                "longitude":         port["longitude"],
                "congestion_index":  round(congestion, 2),
                "average_wait_hours": wait_hours,
            }
        })
    return results

def normalise_portwatch(record: dict) -> dict:
    """
    Normalise a PortWatch congestion record.
    """
    locode  = record["locode"]
    data    = record["data"]
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    congestion_index = data.get("congestion_index", 0.0)  # 0.0–1.0
    avg_wait_hours   = data.get("average_wait_hours", 0)
    port_name        = data.get("port_name", locode)
    country          = data.get("country", "Unknown")
    lat              = data.get("latitude")
    lon              = data.get("longitude")

    if congestion_index >= 0.8:
        severity = "critical"
    elif congestion_index >= 0.6:
        severity = "high"
    elif congestion_index >= 0.4:
        severity = "medium"
    else:
        return None  # Not congested enough to ingest

    title = f"Port Congestion — {port_name} ({locode})"

    return {
        "event_type":  "port_congestion",
        "title":       title,
        "description": (
            f"PortWatch: {port_name} congestion index {congestion_index:.2f}. "
            f"Average vessel wait: {avg_wait_hours}h. UN/LOCODE: {locode}."
        ),
        "country":     country,
        "region":      locode,
        "latitude":    lat,
        "longitude":   lon,
        "severity":    severity,
        "source":      "portwatch",
        "source_url":  f"https://portwatch.imf.org/ports/{locode}",
        "occurred_at": now_iso,
    }