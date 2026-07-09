"""
Phase 6 — persist_report.py

ExecutiveReport node + COVERS edges to the AgentAssessment nodes it draws
on. MERGE key is (customer_id, period_start, period_end) — idempotent
re-runs, same pattern as WRITE_IMPACTS and Phase 5's assessment writes.

Note: no relationship uniqueness constraint exists in Neo4j 5.18
Community Edition (Enterprise-only, per NEO4J_SCHEMA_REFERENCE.md) — same
caveat as IMPACTS applies here: idempotency is entirely on the
application-level MERGE pattern below, not schema-enforced.
"""

from neo4j import Session


WRITE_EXECUTIVE_REPORT = """
MERGE (r:ExecutiveReport {
    report_id: $report_id
})
ON CREATE SET
    r.customer_id = $customer_id,
    r.period_start = $period_start,
    r.period_end = $period_end,
    r.status = $status,
    r.content = $content,
    r.model_used = $model_used,
    r.escalation_rate = $escalation_rate,
    r.theme_count = $theme_count,
    r.incident_count = $incident_count,
    r.source_assessment_ids = $source_assessment_ids,
    r.created_at = datetime()
ON MATCH SET
    r.status = $status,
    r.content = $content,
    r.model_used = $model_used,
    r.escalation_rate = $escalation_rate,
    r.theme_count = $theme_count,
    r.incident_count = $incident_count,
    r.source_assessment_ids = $source_assessment_ids,
    r.updated_at = datetime()
RETURN r.report_id AS report_id
"""

LINK_COVERS = """
MATCH (r:ExecutiveReport {report_id: $report_id})
MATCH (a:AgentAssessment {assessment_id: $assessment_id})
MERGE (r)-[:COVERS]->(a)
"""


def build_report_id(customer_id: str, period_start: str, period_end: str) -> str:
    return f"report_{customer_id}_{period_start}_{period_end}"


def persist_report(
    session: Session,
    customer_id: str,
    period_start: str,
    period_end: str,
    content: str,
    status: str,
    model_used: str,
    escalation_rate: dict,
    theme_count: int,
    assessments: list[dict],
) -> str:
    report_id = build_report_id(customer_id, period_start, period_end)
    assessment_ids = [a["assessment_id"] for a in assessments]

    session.run(
        WRITE_EXECUTIVE_REPORT,
        {
            "report_id": report_id,
            "customer_id": customer_id,
            "period_start": period_start,
            "period_end": period_end,
            "status": status,
            "content": content,
            "model_used": model_used,
            "escalation_rate": escalation_rate.get("rate", 0.0),
            "theme_count": theme_count,
            "incident_count": len(assessments),
            "source_assessment_ids": assessment_ids,
        },
    )

    for assessment_id in assessment_ids:
        session.run(
            LINK_COVERS,
            {"report_id": report_id, "assessment_id": assessment_id},
        )

    return report_id