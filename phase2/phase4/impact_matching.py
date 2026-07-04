"""
Phase 4 — Customer Impact Matching Engine.

Orchestration layer: pulls eligible GlobalEvent nodes, runs Path A (direct
mention) and Path B (geo-proximity) matching, walks each matched supplier
up to its owning Customer(s), applies the alert rule, scores the impact,
and writes IMPACTS relationships.

Depends on:
    phase4.cypher_queries  -- all Cypher, parameterized
    phase4.scoring         -- pure scoring/alert-rule functions, no Neo4j dependency
    phase2.phase5.streaming.redis_stream -- produce_alert() (added this session)

Follows Phase 1-3 conventions:
    - explicit params dicts, never **model_dump()
    - datetimes serialized via .isoformat()
    - enums passed as plain lowercase strings, already validated upstream

Phase 5 integration (added this session): every triggered IMPACTS write now
also calls produce_alert() onto the Redis stream, so Phase 5's LangGraph
agent picks it up within its normal poll interval. This is the one wiring
point Phase 5 was missing -- IMPACTS was being written correctly the whole
time, nothing downstream was ever being notified.

The redis client is optional (redis_client=None) and threaded through every
layer as a plain parameter, matching the existing driver-injection style --
this keeps process_event/run_impact_matching testable without a live Redis
connection, and makes the Phase 5 dependency explicit rather than a hidden
module-level singleton.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import Driver
import redis

from phase2.phase4 import cypher_queries as q
from phase2.phase4 import scoring
from phase2.phase5.streaming.redis_stream import produce_alert

# Confirmed this session: closest true-positive supplier sat at 1.5km,
# next-closest unrelated supplier at 465km -- 100km leaves wide margin
# on both sides without being tested against a close call.
DEFAULT_GEO_DISTANCE_THRESHOLD_M = 100_000


def fetch_eligible_events(driver: Driver) -> list[dict[str, Any]]:
    with driver.session() as session:
        result = session.run(q.FETCH_ELIGIBLE_EVENTS)
        return [dict(record) for record in result]


def match_path_a(driver: Driver, event_id: str) -> list[dict[str, Any]]:
    with driver.session() as session:
        result = session.run(q.PATH_A_DIRECT_MENTION, parameters={"event_id": event_id})
        return [dict(record) for record in result]


def match_path_b(
    driver: Driver,
    event_id: str,
    distance_threshold_m: int = DEFAULT_GEO_DISTANCE_THRESHOLD_M,
) -> list[dict[str, Any]]:
    with driver.session() as session:
        result = session.run(
            q.PATH_B_GEO_PROXIMITY,
            parameters={"event_id": event_id, "distance_threshold_m": distance_threshold_m},
        )
        matches = [dict(record) for record in result]

    # Path A carries confidence straight from MENTIONS; Path B has to
    # derive it from distance since geo-proximity is a weaker signal.
    for m in matches:
        m["match_confidence"] = scoring.geo_match_confidence(m["distance_m"], distance_threshold_m)
    return matches


def dedupe_supplier_matches(
    path_a_matches: list[dict[str, Any]],
    path_b_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    If the same supplier is hit by both paths, keep the mention match --
    it's grounded in actual NLP-confirmed evidence rather than a distance
    decay, so it wins when both fire for the same supplier_id.
    """
    by_supplier: dict[str, dict[str, Any]] = {}
    for m in path_b_matches:
        by_supplier[m["supplier_id"]] = m
    for m in path_a_matches:
        by_supplier[m["supplier_id"]] = m  # mention overwrites geo for the same supplier
    return list(by_supplier.values())


def walk_up_to_customers(driver: Driver, supplier_match: dict[str, Any]) -> list[dict[str, Any]]:
    tier = supplier_match["tier"]
    with driver.session() as session:
        if tier == "tier_1":
            result = session.run(
                q.WALK_UP_TIER_1, parameters={"supplier_id": supplier_match["supplier_id"]}
            )
        elif tier == "tier_2":
            result = session.run(
                q.WALK_UP_TIER_2, parameters={"supplier_id": supplier_match["supplier_id"]}
            )
        else:
            raise ValueError(
                f"Unknown supplier tier: {tier!r} (supplier_id={supplier_match['supplier_id']})"
            )
        return [dict(record) for record in result]


def write_impact(
    driver: Driver,
    event_id: str,
    customer_id: str,
    supplier_id: str,
    score: float,
    triggered: bool,
    match_method: str,
    match_confidence: float,
    severity: str,
    tier: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    redis_client: Optional[redis.Redis] = None,
) -> None:
    params = {
        "event_id": event_id,
        "customer_id": customer_id,
        "supplier_id": supplier_id,
        "score": score,
        "alert_triggered": triggered,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "match_method": match_method,
        "match_confidence": match_confidence,
        "severity": severity,
        "tier": tier,
    }
    with driver.session() as session:
        session.run(q.WRITE_IMPACTS, parameters=params)

    # Notify Phase 5 -- only for triggered alerts, and only if a redis_client
    # was actually provided (keeps this function usable in tests/backfills
    # without a live Redis connection). A failure here must never break the
    # Neo4j write above, which already succeeded -- log and move on rather
    # than raise, so one bad alert-produce doesn't stall the whole DAG run.
    if triggered and redis_client is not None:
        try:
            event_text = f"{title or ''}. {description or ''}".strip()
            produce_alert(
                redis_client,
                customer_id=customer_id,
                event_id=event_id,
                supplier_id=supplier_id,
                title=title or "",
                event_text=event_text,
            )
        except Exception:
            import logging
            logging.getLogger("phase4.impact_matching").exception(
                f"produce_alert failed for event={event_id} customer={customer_id} "
                f"supplier={supplier_id} -- IMPACTS was written successfully, "
                f"but Phase 5 was not notified. Re-run scripts/backfill_alerts_to_stream.py "
                f"in phase5 to pick this up manually."
            )


def process_event(
    driver: Driver,
    event: dict[str, Any],
    distance_threshold_m: int = DEFAULT_GEO_DISTANCE_THRESHOLD_M,
    redis_client: Optional[redis.Redis] = None,
) -> dict[str, int]:
    event_id = event["event_id"]
    severity = event["severity"]
    title = event.get("title")
    description = event.get("description")

    path_a = match_path_a(driver, event_id)
    path_b = match_path_b(driver, event_id, distance_threshold_m)
    supplier_matches = dedupe_supplier_matches(path_a, path_b)

    impacts_written = 0
    alerts_triggered = 0

    for sm in supplier_matches:
        tier = sm["tier"]
        component_criticality = sm.get("component_criticality")
        is_sole_source = bool(sm.get("is_sole_source", False))

        customers = walk_up_to_customers(driver, sm)
        if not customers:
            # Supplier has no OWNS/FEEDS path to any customer -- not an
            # error, just nothing to score (e.g. an orphaned tier_2 node).
            continue

        triggered = scoring.alert_triggered(
            tier=tier,
            severity=severity,
            component_criticality=component_criticality if tier == "tier_2" else None,
        )

        score = scoring.impact_score(
            severity=severity,
            tier=tier,
            is_sole_source=is_sole_source,
            match_confidence=sm["match_confidence"],
        )

        for cust in customers:
            write_impact(
                driver,
                event_id=event_id,
                customer_id=cust["customer_id"],
                supplier_id=sm["supplier_id"],
                score=score,
                triggered=triggered,
                match_method=sm["match_method"],
                match_confidence=sm["match_confidence"],
                severity=severity,
                tier=tier,
                title=title,
                description=description,
                redis_client=redis_client,
            )
            impacts_written += 1
            if triggered:
                alerts_triggered += 1

    return {"impacts_written": impacts_written, "alerts_triggered": alerts_triggered}


def run_impact_matching(
    driver: Driver,
    distance_threshold_m: int = DEFAULT_GEO_DISTANCE_THRESHOLD_M,
    redis_client: Optional[redis.Redis] = None,
) -> dict[str, int]:
    events = fetch_eligible_events(driver)

    total_impacts = 0
    total_alerts = 0
    for event in events:
        result = process_event(driver, event, distance_threshold_m, redis_client=redis_client)
        total_impacts += result["impacts_written"]
        total_alerts += result["alerts_triggered"]

    return {
        "events_processed": len(events),
        "impacts_written": total_impacts,
        "alerts_triggered": total_alerts,
    }