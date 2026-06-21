"""
airflow/dags/weather_ingestion_dag.py
---------------------------------------
Airflow DAG: hourly WeatherAPI ingestion → Neo4j.

Polls 12 port/facility locations every hour for:
  1. Active weather alerts (formal warnings)
  2. Threshold breaches in current conditions (wind/precip/visibility)

When either condition triggers, a DisruptionEventNode is created AND the
corresponding Port or Facility node gets an :AFFECTS relationship.

Schedule: Hourly (weather conditions change fast; alerts issued with ~1hr notice).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "scm-pipeline",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "email_on_failure": False,
}


@dag(
    dag_id="weather_ingestion",
    description="Poll WeatherAPI for port/facility weather alerts and write DisruptionEvents to Neo4j",
    schedule_interval="@hourly",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["phase2", "ingestion", "weather"],
)
def weather_ingestion_dag():

    @task()
    def fetch_weather_data() -> dict:
        """
        Fetch alerts + threshold conditions from WeatherAPI for all monitored locations.
        Returns dict with "alerts" and "conditions" lists (JSON-serializable).
        """
        import os
        from ingestion.weather.fetcher import WeatherAPIFetcher, SEED_MONITORED_LOCATIONS
        from ingestion.event_id import reset_counters

        reset_counters()

        api_key = os.environ["WEATHERAPI_KEY"]
        fetcher = WeatherAPIFetcher(api_key=api_key)
        alerts, conditions = fetcher.fetch_all_locations(SEED_MONITORED_LOCATIONS)

        return {
            "alerts": [a.model_dump(mode="json") for a in alerts],
            "conditions": [c.model_dump(mode="json") for c in conditions],
        }

    @task()
    def build_event_records(weather_data: dict) -> list[dict]:
        """
        Convert WeatherAlert and WeatherCondition objects into DisruptionEvent field dicts.
        Attaches the target_id and target_label for AFFECTS relationship linking.
        """
        from ingestion.weather.fetcher import (
            WeatherAlert, WeatherCondition,
            alert_to_event_fields, condition_to_event_fields,
            SEED_MONITORED_LOCATIONS,
        )
        from ingestion.event_id import generate_event_id

        # Build location_id → region_id lookup
        location_region = {loc.location_id: loc.region_id for loc in SEED_MONITORED_LOCATIONS}
        location_type = {loc.location_id: loc.location_type for loc in SEED_MONITORED_LOCATIONS}

        events = []

        for raw_alert in weather_data.get("alerts", []):
            alert = WeatherAlert(**raw_alert)
            fields = alert_to_event_fields(alert)
            fields["event_id"] = generate_event_id("weatherapi", alert.effective)
            fields["affected_region"] = location_region.get(alert.location_id)

            # Determine AFFECTS target — Port or Facility
            loc_type = location_type.get(alert.location_id, "port")
            fields["affects_target_id"] = alert.location_id
            fields["affects_target_label"] = "Port" if loc_type == "port" else "Facility"
            fields["confidence"] = 0.9       # formal alert → high confidence

            events.append(fields)

        for raw_cond in weather_data.get("conditions", []):
            cond = WeatherCondition(**raw_cond)
            region_id = location_region.get(cond.location_id, "")
            fields = condition_to_event_fields(cond, region_id)
            fields["event_id"] = generate_event_id("weatherapi")
            fields["affects_target_id"] = cond.location_id
            fields["affects_target_label"] = "Port" if location_type.get(cond.location_id) == "port" else "Facility"
            fields["confidence"] = 0.65      # threshold-based → moderate confidence

            events.append(fields)

        logger.info("Built %d weather event records", len(events))
        return events

    @task()
    def write_weather_events(events: list[dict]) -> dict:
        """
        Upsert DisruptionEventNode + AFFECTS relationship for each weather event.
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")

        from datetime import datetime, timezone
        from graph.connection import get_connection
        from graph.models.nodes import DisruptionEventNode, EventType, RiskLevel
        from graph.queries.repository import SupplyChainRepository
        from graph.models.relationships import AffectsRel

        conn = get_connection()
        repo = SupplyChainRepository(conn)

        written = 0
        linked = 0
        errors = 0

        for fields in events:
            try:
                # Coerce datetimes
                for dt_field in ("started_at", "ended_at", "created_at", "updated_at"):
                    val = fields.get(dt_field)
                    if isinstance(val, str):
                        fields[dt_field] = datetime.fromisoformat(val)
                    elif val is None and dt_field in ("created_at", "updated_at"):
                        fields[dt_field] = datetime.now(timezone.utc)

                node = DisruptionEventNode(
                    event_id=fields["event_id"],
                    event_type=EventType("weather"),
                    title=fields["title"],
                    description=fields["description"],
                    severity=RiskLevel(fields["severity"]),
                    source="weatherapi",
                    source_url=fields.get("source_url"),
                    affected_region=fields.get("affected_region"),
                    started_at=fields["started_at"],
                    ended_at=fields.get("ended_at"),
                    is_resolved=False,
                    impact_score=fields.get("impact_score", 0.45),
                    created_at=fields["created_at"],
                    updated_at=fields["updated_at"],
                )

                repo.upsert_disruption_event(node)
                written += 1

                # Link AFFECTS → Port or Facility
                target_id = fields.get("affects_target_id")
                target_label = fields.get("affects_target_label", "Port")
                if target_id:
                    affects_rel = AffectsRel(
                        impact_type="supply_delay",
                        estimated_delay_days=None,
                        confidence=fields.get("confidence", 0.8),
                        detected_at=fields["created_at"],
                    )
                    repo.link_event_affects(
                        event_id=fields["event_id"],
                        target_id=target_id,
                        target_label=target_label,
                        rel=affects_rel,
                    )
                    linked += 1

            except Exception as exc:
                errors += 1
                logger.error("Weather event write failed for %s: %s", fields.get("event_id"), exc)

        result = {"written": written, "linked": linked, "errors": errors}
        logger.info("Weather Neo4j write complete: %s", result)
        return result

    @task()
    def update_port_congestion_from_weather(weather_data: dict) -> dict:
        """
        If a weather alert affects a port, bump its congestion_index by +0.15
        (capped at 1.0) to reflect the expected knock-on effect.
        This is a simple heuristic; Phase 4 agent applies more nuanced scoring.
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")

        from graph.connection import get_connection
        from ingestion.weather.fetcher import WeatherAlert, SEED_MONITORED_LOCATIONS

        conn = get_connection()
        location_type = {loc.location_id: loc.location_type for loc in SEED_MONITORED_LOCATIONS}

        updated = 0
        for raw_alert in weather_data.get("alerts", []):
            alert = WeatherAlert(**raw_alert)
            if location_type.get(alert.location_id) != "port":
                continue
            if alert.severity not in ("high", "critical"):
                continue

            bump = 0.15 if alert.severity == "high" else 0.25
            try:
                conn.run_write(
                    """
                    MATCH (p:Port {port_id: $port_id})
                    SET p.congestion_index = min(1.0, p.congestion_index + $bump),
                        p.updated_at = datetime()
                    """,
                    {"port_id": alert.location_id, "bump": bump},
                )
                updated += 1
                logger.info("Bumped congestion for %s by +%.2f (weather alert)", alert.location_id, bump)
            except Exception as exc:
                logger.error("Failed to update port congestion for %s: %s", alert.location_id, exc)

        return {"ports_updated": updated}

    # DAG wiring
    weather_data = fetch_weather_data()
    event_records = build_event_records(weather_data)
    neo4j_result = write_weather_events(event_records)
    update_port_congestion_from_weather(weather_data)


weather_dag = weather_ingestion_dag()