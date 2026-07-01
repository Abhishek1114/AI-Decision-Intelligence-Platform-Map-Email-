# phase2/ingestion/sources/weatherapi.py

import requests
import os
from datetime import datetime
from typing import List

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "")
WEATHERAPI_URL = "http://api.weatherapi.com/v1/current.json"

# Cities near seed customer supply chain nodes
# Expand this list as more customers onboard
MONITORED_LOCATIONS = [
    {"city": "Hsinchu",   "country": "Taiwan",      "note": "TSMC Fab 18"},
    {"city": "Shanghai",  "country": "China",        "note": "Foxconn + Port of Shanghai"},
    {"city": "Zhengzhou", "country": "China",        "note": "Foxconn Zhengzhou"},
    {"city": "Hyderabad", "country": "India",        "note": "BioSynth Hyderabad"},
    {"city": "Rotterdam", "country": "Netherlands",  "note": "Port of Rotterdam"},
    {"city": "Ho Chi Minh City", "country": "Vietnam", "note": "Foxconn Bac Giang area"},

    {"city": "Kumamoto",         "country": "Japan",        "note": "Sony Image Sensors (TSMC supplier)"},
    {"city": "Eindhoven",        "country": "Netherlands",  "note": "ASML EUV Lithography"},
    {"city": "Taichung",         "country": "Taiwan",       "note": "Largan Precision Lenses"},
    {"city": "Gumi",             "country": "South Korea",  "note": "Samsung Display OLED"},
    {"city": "Penang",           "country": "Malaysia",     "note": "Intel Penang Assembly"},
    {"city": "Austin",           "country": "USA",          "note": "Samsung Austin (logic chips)"},
]

# Only alert on these WeatherAPI condition codes — ignore sunny days
SEVERE_CONDITION_CODES = {
    1087: ("weather", "high",     "Thundery outbreaks possible"),
    1117: ("weather", "critical", "Blizzard"),
    1237: ("weather", "high",     "Ice pellets"),
    1273: ("weather", "high",     "Patchy light rain with thunder"),
    1276: ("weather", "critical", "Moderate or heavy rain with thunder"),
    1279: ("weather", "high",     "Patchy light snow with thunder"),
    1282: ("weather", "critical", "Moderate or heavy snow with thunder"),
    1225: ("weather", "high",     "Heavy snow"),
    1195: ("weather", "high",     "Heavy rain"),
    1192: ("weather", "medium",   "Heavy rain at times"),
    1246: ("weather", "critical", "Torrential rain shower"),
}


def fetch_severe_weather() -> List[dict]:
    """
    Check current weather at all monitored supply chain locations.
    Returns only locations experiencing severe conditions.
    """
    if not WEATHERAPI_KEY:
        print("[WeatherAPI] No API key set — skipping weather fetch.")
        return []

    results = []
    for loc in MONITORED_LOCATIONS:
        try:
            response = requests.get(
                WEATHERAPI_URL,
                params={"key": WEATHERAPI_KEY, "q": loc["city"], "aqi": "no"},
                timeout=10,
            )
            if response.status_code != 200:
                continue

            data    = response.json()
            code    = data["current"]["condition"]["code"]
            
            if code in SEVERE_CONDITION_CODES:
                results.append({
                    "location_meta": loc,
                    "weather_data":  data,
                    "condition_code": code,
                })
        except requests.RequestException:
            continue

    return results


def normalise_weatherapi(record: dict) -> dict:
    """
    Normalise a WeatherAPI severe weather record to our internal format.
    """
    loc       = record["location_meta"]
    data      = record["weather_data"]
    code      = record["condition_code"]
    now_iso   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    event_type, severity, condition_text = SEVERE_CONDITION_CODES[code]

    current   = data["current"]
    location  = data["location"]
    lat       = location.get("lat")
    lon       = location.get("lon")

    title = (
        f"Severe Weather — {loc['city']}, {loc['country']}: "
        f"{condition_text}"
    )

    return {
        "event_type":  event_type,
        "title":       title,
        "description": (
            f"WeatherAPI: {condition_text} in {loc['city']}, {loc['country']}. "
            f"Near: {loc['note']}. "
            f"Temp: {current.get('temp_c')}°C. "
            f"Wind: {current.get('wind_kph')} kph. "
            f"Visibility: {current.get('vis_km')} km."
        ),
        "country":     loc["country"],
        "region":      loc["city"],
        "latitude":    lat,
        "longitude":   lon,
        "severity":    severity,
        "source":      "open_meteo",   # Keep enum value — avoids model change
        "source_url":  f"https://www.weatherapi.com/",
        "occurred_at": now_iso,
    }