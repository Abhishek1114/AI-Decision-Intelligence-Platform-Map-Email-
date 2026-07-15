"""
Phase 7 — Standalone real-time alert consumer.

Drains supply_chain:assessments_created (Phase 5 -> Phase 7), filters to
initial_severity in {high, critical} (Phase 4's pre-LLM severity, which is
the authoritative trigger signal per persist.py's own trigger/display split —
AgentAssessment.severity is display-only and is None for every needs_review row).

Re-fetches full context from Neo4j rather than trusting the stream payload —
the graph is the single source of truth, the stream is just a pointer.
Idempotent against XAUTOCLAIM redelivery via the alert_sent flag.
"""
import os
import logging
from neo4j import GraphDatabase
import redis

from phase2.phase7.delivery.email_delivery import EmailDelivery

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phase7_alert_consumer")

STREAM_NAME = "supply_chain:assessments_created"
GROUP_NAME = "phase7_alert_workers"
CONSUMER_NAME = os.environ.get("HOSTNAME", "alert_consumer_1")
ALERTABLE_SEVERITIES = {"high", "critical"}

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

FETCH_CONTEXT_QUERY = """
MATCH (a:AgentAssessment {assessment_id: $assessment_id})-[:FOR_CUSTOMER]->(c:Customer)
MATCH (e:GlobalEvent {event_id: $event_id})
OPTIONAL MATCH (e)-[imp:IMPACTS]->(c)
WHERE imp.supplier_id = a.supplier_id
RETURN a.assessment_id AS assessment_id,
       a.customer_id AS customer_id,
       a.supplier_id AS supplier_id,      
       a.severity AS severity,
       a.confidence AS confidence,
       a.predicted_business_impact AS predicted_business_impact,
       a.evidence AS evidence,
       a.recommended_actions_json AS recommended_actions_json,
       a.affected_product_ids AS affected_product_ids,
       a.updated_at AS updated_at,
       a.initial_severity AS initial_severity,
       a.status AS status,
       a.alert_sent AS alert_sent,
       c.company_name AS company_name,
       c.contact_email AS contact_email,
       e.title AS event_title,
       e.description AS event_description,
       imp.severity AS impact_severity
"""

MARK_ALERT_SENT_QUERY = """
MATCH (a:AgentAssessment {assessment_id: $assessment_id})
SET a.alert_sent = true, a.alert_sent_at = datetime()
"""


def ensure_group(r: redis.Redis):
    try:
        r.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def process_message(driver, delivery, msg_id, fields, r):
    assessment_id = fields.get("assessment_id")
    event_id = fields.get("event_id")

    if fields.get("initial_severity") not in ALERTABLE_SEVERITIES:
        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    with driver.session() as session:
        record = session.run(FETCH_CONTEXT_QUERY,
                              parameters={"assessment_id": assessment_id, "event_id": event_id}).single()

    if record is None:
        logger.warning(f"{assessment_id}/{event_id} not found in Neo4j — acking, likely stale test data")
        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    if record["alert_sent"]:
        logger.info(f"{assessment_id} already alert_sent=true — redelivery, acking")
        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    if record["initial_severity"] not in ALERTABLE_SEVERITIES:
        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        return

    if not record["contact_email"]:
        logger.error(f"Customer {record['customer_id']} has no contact_email — leaving in PEL for manual fix")
        return  # don't ack — data problem, not transient

    ctx = {
        "assessment_id": assessment_id,
        "customer_id": record["customer_id"],
        "supplier_id": record["supplier_id"],
        "initial_severity": record["initial_severity"],
        "severity": record["severity"],
        "company_name": record["company_name"],
        "contact_email": record["contact_email"],
        "confidence": record["confidence"],
        "predicted_business_impact": record["predicted_business_impact"],
        "evidence": record["evidence"],
        "recommended_actions_json": record["recommended_actions_json"],
        "affected_product_ids": record["affected_product_ids"],
        "updated_at": record["updated_at"],
        "event_titles": [record["event_title"] or "Untitled event"],
        "event_title": record["event_title"] or "Untitled event",
    }

    needs_review = record["status"] == "needs_review"
    try:
        delivery.send_alert(ctx, needs_review=needs_review)
    except Exception as exc:
        logger.error(f"Send failed for {assessment_id}: {exc}")
        return  # don't ack — retried via XAUTOCLAIM

    with driver.session() as session:
        session.run(MARK_ALERT_SENT_QUERY, parameters={"assessment_id": assessment_id})
    r.xack(STREAM_NAME, GROUP_NAME, msg_id)
    logger.info(f"Alert sent (needs_review={needs_review}) + acked for {assessment_id}")


def reclaim_stale(r: redis.Redis, min_idle_ms=60_000):
    try:
        _, claimed, _ = r.xautoclaim(STREAM_NAME, GROUP_NAME, CONSUMER_NAME, min_idle_ms, "0-0", count=50)
        return claimed
    except redis.ResponseError:
        return []


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    delivery = EmailDelivery()
    ensure_group(r)
    logger.info("Phase 7 alert consumer started")

    while True:
        for msg_id, fields in reclaim_stale(r):
            process_message(driver, delivery, msg_id, fields, r)
        resp = r.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_NAME: ">"}, count=10, block=5000)
        if not resp:
            continue
        for _, messages in resp:
            for msg_id, fields in messages:
                process_message(driver, delivery, msg_id, fields, r)


if __name__ == "__main__":
    main()