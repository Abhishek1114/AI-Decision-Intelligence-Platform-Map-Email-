"""
tests/ingestion/test_gdelt_mapping.py

Pure unit tests, no network/Neo4j required. Mirrors the derivation tables
in Phase2_ingestion_schema_reference.md sections 4.2/4.3.
"""
from ingestion.sources.gdelt.mapping import (
    map_theme_to_event_type,
    map_tone_to_severity,
    parse_v2locations,
    tone_to_impact_score,
)


def test_theme_mapping_strike_to_labor():
    assert map_theme_to_event_type("USPEC_POLICY1;LABOR_STRIKE;ECON") == "labor"


def test_theme_mapping_cyber():
    assert map_theme_to_event_type("CYBER_ATTACK;TAX_FNCACT_HACKER") == "cyber"


def test_theme_mapping_default_to_geopolitical():
    assert map_theme_to_event_type("UNRELATED_THEME_XYZ") == "geopolitical"


def test_theme_mapping_first_match_wins():
    # STRIKE appears before MARITIME in the lookup order -> labor wins
    assert map_theme_to_event_type("MARITIME_STRIKE") == "labor"


def test_tone_to_severity_bands():
    assert map_tone_to_severity(-8.0) == "critical"
    assert map_tone_to_severity(-7.0) == "critical"
    assert map_tone_to_severity(-6.9) == "high"
    assert map_tone_to_severity(-4.0) == "high"
    assert map_tone_to_severity(-3.9) == "medium"
    assert map_tone_to_severity(-2.1) == "medium"


def test_tone_to_impact_score_clamped():
    assert tone_to_impact_score(-10.0) == 1.0
    assert tone_to_impact_score(-15.0) == 1.0  # clamped even if GDELT sends extreme values
    assert tone_to_impact_score(-5.0) == 0.5
    assert tone_to_impact_score(0.0) == 0.0


def test_parse_v2locations_extracts_country_codes():
    raw = "1#Taipei, Taiwan#TAW#TW00#TW001#25.03#121.56#-123;2#Seoul#SKO#KS11##37.5#127.0#-456"
    assert parse_v2locations(raw) == ["TAW", "SKO"]


def test_parse_v2locations_empty_string():
    assert parse_v2locations("") == []


def test_parse_v2locations_malformed_entry_skipped():
    raw = "garbage;1#Taipei#TAW#TW00#TW001#25.03#121.56#-123"
    assert parse_v2locations(raw) == ["TAW"]
