"""
airflow/dags/portwatch_ingestion_dag.py
-----------------------------------------
Airflow DAG: 4× daily port congestion update → Neo4j.

Fetches congestion snapshots for all 6 seed ports and:
  1. Updates Port node properties (congestion_index, avg_dwell_days)
  2. Creates a DisruptionEventNode if congestion exceeds "anomalous" threshold
  3. Links the event to the Port via [:AFFECTS]

Schedule: Every 6 hours — port congestion data from MarineTraffic/mock
updates at this cadence. More frequent than needed for mock mode,
but keeps the pipeline realistic for production swap-in.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "scm-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}


@dag(
    dag_id="portwatch_ingestion",
    description="Update port congestion metrics in Neo4j and generate congestion DisruptionEvents",
    schedule_interval="0 */6 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["phase2", "ingestion", "portwatch"],
)
def portwatch_ingestion_dag():

    @task()
    def fetch_port_snapshots() -> list[dict]:
        """Fetch congestion snapshots for all monitored ports."""
        from ingestion.portwatch.fetcher import get_port_fetcher, MockPortFetcher
        from ingestion.event_id import reset_counters

        reset_counters()
        fetcher = get_port_fetcher()

        if isinstance(fetcher, MockPortFetcher):
            snapshots = fetcher.fetch_all()
        else:
            from ingestion.portwatch.fetcher import PORT_BASELINES
            snapshots = []
            for port_id in PORT_BASELINES:
                snap = fetcher.fetch_port_snapshot(port_id, port_id)
                if snap:
                    snapshots.append(snap)

        return [s.model_dump(mode="json") for s in snapshots]

    @task()
    def update_port_nodes(snapshots: list[dict]) -> dict:
        """
        Write congestion_index and avg_dwell_days to Port nodes via raw Cypher.
        Uses the exact Cypher pattern from Phase 1 data contracts.
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")
        from graph.connection import get_connection

        conn = get_connection()
        updated = 0
        errors = 0

        for snap in snapshots:
            try:
                conn.run_write(
                    """
                    MATCH (p:Port {port_id: $port_id})
                    SET p.congestion_index = $congestion_index,
                        p.avg_dwell_days   = $avg_dwell_days,
                        p.updated_at       = datetime()
                    """,
                    {
                        "port_id": snap["port_id"],
                        "congestion_index": snap["congestion_index"],
                        "avg_dwell_days": snap["avg_dwell_days"],
                    },
                )
                updated += 1
                logger.info(
                    "Updated port %s: congestion=%.3f dwell=%.1f",
                    snap["port_id"], snap["congestion_index"], snap["avg_dwell_days"],
                )
            except Exception as exc:
                errors += 1
                logger.error("Failed to update port %s: %s", snap["port_id"], exc)

        return {"updated": updated, "errors": errors}

    @task()
    def detect_and_write_congestion_events(snapshots: list[dict]) -> dict:
        """
        For ports with anomalous congestion (>30% above baseline), create a
        DisruptionEventNode and link it to the Port via [:AFFECTS].
        """
        import sys
        sys.path.insert(0, "/opt/airflow/supply-chain-monitor")

        from datetime import datetime, timezone
        from graph.connection import get_connection
        from graph.models.nodes import DisruptionEventNode, EventType, RiskLevel
        from graph.queries.repository import SupplyChainRepository
        from graph.models.relationships import AffectsRel
        from ingestion.portwatch.fetcher import PortCongestionSnapshot
        from ingestion.event_id import generate_event_id

        conn = get_connection()
        repo = SupplyChainRepository(conn)

        written = 0
        skipped = 0

        for raw_snap in snapshots:
            snap = PortCongestionSnapshot(**raw_snap)

            if not snap.is_anomalous:
                skipped += 1
                continue

            now = datetime.now(timezone.utc)
            event_id = generate_event_id("portwatch", now)

            severity = snap.risk_level
            impact_score = round(snap.congestion_index * 0.9, 3)   # scale to 0–0.9

            try:
                node = DisruptionEventNode(
                    event_id=event_id,
                    event_type=EventType("logistics"),
                    title=f"Port congestion anomaly at {snap.port_name}",
                    description=(
                        f"Congestion index reached {snap.congestion_index:.2f} "
                        f"(avg dwell {snap.avg_dwell_days:.1f} days). "
                        f"Vessels at anchor: {snap.vessels_at_anchor}, in port: {snap.vessels_in_port}. "
                        f"Source: {snap.data_source}."
                    ),
                    severity=RiskLevel(severity),
                    source="portwatch",
                    source_url=None,
                    affected_region=None,
                    started_at=now,
                    ended_at=None,
                    is_resolved=False,
                    impact_score=impact_score,
                    created_at=now,
                    updated_at=now,
                )
                repo.upsert_disruption_event(node)

                affects_rel = AffectsRel(
                    impact_type="reroute",
                    estimated_delay_days=snap.avg_dwell_days,
                    confidence=0.75,
                    detected_at=now,
                )
                repo.link_event_affects(
                    event_id=event_id,
                    target_id=snap.port_id,
                    target_label="Port",
                    rel=affects_rel,
                )
                written += 1
                logger.info("Created congestion event %s for port %s", event_id, snap.port_id)

            except Exception as exc:
                logger.error("Failed to write congestion event for %s: %s", snap.port_id, exc)

        return {"events_written": written, "ports_skipped": skipped}

    # DAG wiring
    snapshots = fetch_port_snapshots()
    port_update_result = update_port_nodes(snapshots)
    congestion_event_result = detect_and_write_congestion_events(snapshots)


portwatch_dag = portwatch_ingestion_dag()