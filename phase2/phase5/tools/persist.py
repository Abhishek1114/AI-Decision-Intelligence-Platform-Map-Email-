"""
Phase 5 — Persistence for agent runs.

Confirmed decision: agent output IS persisted as a new node, AgentAssessment —
distinct from the idea note's incorrect "CustomerImpact" reference, and distinct
from the Phase 4 IMPACTS relationship (which stays a relationship, unchanged).

Schema:
  (AgentAssessment {assessment_id, customer_id, supplier_id, source_event_ids[], status, severity,
                     confidence, predicted_business_impact, evidence,
                     recommended_actions_json, affected_product_ids,
                     narrowing_method, model_used, created_at, updated_at})
    -[:REGARDING]->(GlobalEvent)  -- one edge per source event, incl. duplicates
    -[:FOR_CUSTOMER]->(Customer)

assessment_id is keyed on (customer_id, supplier_id, dedup_key) where dedup_key
is a hash of the normalized event title. supplier_id is included deliberately —
Phase 4's WRITE_IMPACTS treats (event_id, customer_id, supplier_id) as its merge
key, meaning one real-world event hitting one customer via two different
suppliers is two distinct impact paths kept separate for audit/tuning. Phase 5's
title-hash dedup must not collapse that: it only exists to catch upstream
duplicate GlobalEvent *nodes* (same real event, same supplier, distinct node id).

recommended_actions is a list of objects (action, rationale, urgency) and
Neo4j cannot store a list of maps as a property, so it's serialized to a
JSON string (recommended_actions_json). Deliberate tradeoff to avoid a separate
RecommendedAction node for what's expected to be a small, read-mostly list.
"""
from __future__ import annotations
import json
from neo4j import Driver
import logging

logger = logging.getLogger(__name__)

from phase2.phase5.models import AgentOutput


def build_assessment_id(dedup_key: str, customer_id: str, supplier_id: str) -> str:
    return f"assess_{dedup_key}_{customer_id}_{supplier_id}"


def persist_agent_assessment(driver: Driver, output: AgentOutput, dedup_key: str, supplier_id: str) -> str:
    observed = output.observed
    prediction = output.prediction

    assessment_id = build_assessment_id(dedup_key, observed.customer_id, supplier_id)
    affected_product_ids = [p.product_id for p in observed.affected_products]

    if prediction is not None:
        severity = prediction.severity.value
        confidence = prediction.confidence
        predicted_business_impact = prediction.predicted_business_impact
        evidence = prediction.evidence
        recommended_actions_json = json.dumps(
            [a.model_dump() for a in prediction.recommended_actions]
        )
    else:
        severity = None
        confidence = None
        predicted_business_impact = None
        evidence = []
        recommended_actions_json = "[]"

    # Severity-override rule (locked): AgentAssessment.severity is authoritative
    # for DISPLAY once available; IMPACTS.severity remains authoritative for
    # alert TRIGGERING (already computed in Phase 4 before this runs). We never
    # silently show one without the other — log the delta explicitly.
    initial_severity = observed.initial_severity
    severity_reassessed = bool(
        initial_severity and severity and initial_severity.lower() != severity.lower()
    )
    if severity_reassessed:
        logger.info(
            f"Severity reassessed by agent: event={observed.event_id} "
            f"customer={observed.customer_id} supplier={supplier_id} "
            f"initial={initial_severity} -> final={severity}"
        )

    query = """
    MATCH (e:GlobalEvent {event_id: $event_id})
    MATCH (c:Customer {customer_id: $customer_id})
    MERGE (a:AgentAssessment {assessment_id: $assessment_id})
    ON CREATE SET a.created_at = datetime(), a.source_event_ids = []
    SET a.customer_id = $customer_id,
        a.supplier_id = $supplier_id,
        a.status = $status,
        a.severity = $severity,
        a.initial_severity = $initial_severity,
        a.severity_reassessed = $severity_reassessed,
        a.confidence = $confidence,
        a.predicted_business_impact = $predicted_business_impact,
        a.evidence = $evidence,
        a.recommended_actions_json = $recommended_actions_json,
        a.affected_product_ids = $affected_product_ids,
        a.narrowing_method = $narrowing_method,
        a.model_used = $model_used,
        a.raw_llm_output = $raw_llm_output,
        a.updated_at = datetime(),
        a.source_event_ids = CASE
            WHEN $event_id IN a.source_event_ids THEN a.source_event_ids
            ELSE a.source_event_ids + $event_id
        END
    MERGE (a)-[:REGARDING]->(e)
    MERGE (a)-[:FOR_CUSTOMER]->(c)
    RETURN a.assessment_id AS assessment_id
    """

    params = {
        "event_id": observed.event_id,
        "customer_id": observed.customer_id,
        "supplier_id": supplier_id,
        "assessment_id": assessment_id,
        "status": output.status.value,
        "severity": severity,
        "initial_severity": initial_severity,
        "severity_reassessed": severity_reassessed,
        "confidence": confidence,
        "predicted_business_impact": predicted_business_impact,
        "evidence": evidence,
        "recommended_actions_json": recommended_actions_json,
        "affected_product_ids": affected_product_ids,
        "narrowing_method": observed.narrowing_method.value,
        "model_used": "openai/gpt-oss-120b",
        "raw_llm_output": output.raw_llm_output,
    }

    with driver.session() as session:
        result = session.run(query, **params)
        record = result.single()
        return record["assessment_id"]