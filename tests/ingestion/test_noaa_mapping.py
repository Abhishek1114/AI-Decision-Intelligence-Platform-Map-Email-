from ingestion.sources.noaa.mapping import map_noaa_severity, severity_to_impact_score


def test_noaa_severity_mapping():
    assert map_noaa_severity("Extreme") == "critical"
    assert map_noaa_severity("Severe") == "high"
    assert map_noaa_severity("Moderate") == "medium"
    assert map_noaa_severity("Minor") == "low"


def test_noaa_unknown_severity_defaults_to_medium_not_low():
    # Conservative default per schema doc 4.5 — never silently downgraded
    assert map_noaa_severity("Unknown") == "medium"
    assert map_noaa_severity("SomethingNOAANeverSent") == "medium"


def test_severity_to_impact_score_bands():
    assert severity_to_impact_score("critical") == 0.9
    assert severity_to_impact_score("high") == 0.7
    assert severity_to_impact_score("medium") == 0.5
    assert severity_to_impact_score("low") == 0.25
