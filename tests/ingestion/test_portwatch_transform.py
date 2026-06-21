from ingestion.clients.portwatch.client import PortWatchReading
from ingestion.sources.portwatch.transform import (
    CONGESTION_ALERT_THRESHOLD,
    transform_reading,
)


def _reading(**overrides) -> PortWatchReading:
    base = dict(
        portwatch_id="PLACEHOLDER-TWKHH",
        port_name="Kaohsiung",
        reading_date="2026-06-20",
        vessels_waiting=10.0,
        average_waiting_time_hours=48.0,
        vessel_count_total=20.0,
    )
    base.update(overrides)
    return PortWatchReading(**base)


def test_unmapped_portwatch_id_returns_none():
    reading = _reading(portwatch_id="UNKNOWN-NOT-IN-MAP")
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=None, routes_for_port=[]
    )
    assert result is None


def test_normal_congestion_no_event_emitted():
    reading = _reading(vessels_waiting=5.0)  # 5/20 = 0.25, well under threshold
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=0.2, routes_for_port=["RT-001"]
    )
    assert result is not None
    assert result.update.port_id == "TWKHH"
    assert abs(result.update.congestion_index - 0.25) < 1e-6
    assert result.event is None
    assert result.affects == []


def test_threshold_crossing_emits_event_with_affects():
    reading = _reading(vessels_waiting=16.0)  # 16/20 = 0.8 >= 0.75 threshold
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=0.5, routes_for_port=["RT-001"]
    )
    assert result is not None
    assert result.update.congestion_index >= CONGESTION_ALERT_THRESHOLD
    assert result.event is not None
    assert result.event.event_type == "logistics"
    assert result.event.source == "portwatch"
    # Port itself + the one route attached to it
    target_labels = {(t, l) for t, l, _ in result.affects}
    assert ("TWKHH", "Port") in target_labels
    assert ("RT-001", "Route") in target_labels


def test_already_above_threshold_does_not_refire():
    # previous reading was ALSO above threshold -> no new event (only fires on crossing)
    reading = _reading(vessels_waiting=16.0)
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=0.85, routes_for_port=[]
    )
    assert result is not None
    assert result.event is None


def test_congestion_index_clamped_to_one():
    reading = _reading(vessels_waiting=100.0)  # way over baseline
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=0.0, routes_for_port=[]
    )
    assert result.update.congestion_index == 1.0


def test_missing_vessels_waiting_returns_none():
    reading = _reading(vessels_waiting=None)
    result = transform_reading(
        reading, baseline_capacity=20.0, previous_congestion_index=None, routes_for_port=[]
    )
    assert result is None
