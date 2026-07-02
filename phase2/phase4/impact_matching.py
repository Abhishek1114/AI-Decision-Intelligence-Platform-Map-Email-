"""
Phase 4 — Customer Impact Matching Engine.

Orchestration layer: pulls eligible GlobalEvent nodes, runs Path A (direct
mention) and Path B (geo-proximity) matching, walks each matched supplier
up to its owning Customer(s), applies the alert rule, scores the impact,
and writes IMPACTS relationships.

Depends on:
    phase4.cypher_queries  -- all Cypher, parameterized
    phase4.scoring         -- pure scoring/alert-rule functions, no Neo4j dependency

Follows Phase 1-3 conventions:
    - explicit params dicts, never **model_dump()
    - datetimes serialized via .isoformat()
    - enums passed as plain lowercase strings, already validated upstream
"""

from datetime import datetime, timezone
from typing import Any

from neo4j import Driver

from phase2.phase4 import cypher_queries as q
from phase2.phase4 import scoring

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


def process_event(
    driver: Driver,
    event: dict[str, Any],
    distance_threshold_m: int = DEFAULT_GEO_DISTANCE_THRESHOLD_M,
) -> dict[str, int]:
    event_id = event["event_id"]
    severity = event["severity"]

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
            )
            impacts_written += 1
            if triggered:
                alerts_triggered += 1

    return {"impacts_written": impacts_written, "alerts_triggered": alerts_triggered}


def run_impact_matching(
    driver: Driver,
    distance_threshold_m: int = DEFAULT_GEO_DISTANCE_THRESHOLD_M,
) -> dict[str, int]:
    events = fetch_eligible_events(driver)

    total_impacts = 0
    total_alerts = 0
    for event in events:
        result = process_event(driver, event, distance_threshold_m)
        total_impacts += result["impacts_written"]
        total_alerts += result["alerts_triggered"]

    return {
        "events_processed": len(events),
        "impacts_written": total_impacts,
        "alerts_triggered": total_alerts,
    }