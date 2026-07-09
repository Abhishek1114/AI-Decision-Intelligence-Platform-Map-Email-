"""
Phase 6 — fetch_assessments.py

Pulls AgentAssessment nodes for a single customer within a reporting period.
Duplicate-collapsed assessments (Phase 5 dedup) are the unit here — we never
re-surface duplicate GlobalEvent nodes as separate incidents, since Phase 5
already collapsed them onto source_event_ids.
"""

from neo4j import Session


FETCH_PERIOD_ASSESSMENTS = """
MATCH (a:AgentAssessment {customer_id: $customer_id})
WHERE a.created_at >= datetime($period_start)
  AND a.created_at < datetime($period_end)
  AND a.status <> 'duplicate_skipped'
RETURN a.assessment_id        AS assessment_id,
       a.supplier_id          AS supplier_id,
       a.affected_product_ids AS affected_product_ids,
       a.severity             AS severity,
       a.confidence           AS confidence,
       a.initial_severity     AS initial_severity,
       a.severity_reassessed  AS severity_reassessed,
       a.evidence             AS evidence,
       a.predicted_business_impact AS predicted_business_impact,
       a.recommended_actions_json  AS recommended_actions_json,
       a.source_event_ids     AS source_event_ids
ORDER BY a.created_at ASC
"""


def fetch_period_assessments(
    session: Session,
    customer_id: str,
    period_start: str,
    period_end: str,
) -> list[dict]:
    """
    period_start / period_end: ISO 8601 strings, e.g. '2026-06-29T00:00:00Z'.
    period_end is exclusive.
    """
    params = {
        "customer_id": customer_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    result = session.run(FETCH_PERIOD_ASSESSMENTS, params)
    return [dict(record) for record in result]