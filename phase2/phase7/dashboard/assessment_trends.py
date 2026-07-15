"""
Phase 7 — Assessment trend query. Buckets AgentAssessment by week and
severity, off created_at (confirmed real Neo4j datetime type per schema
doc). Same shape of aggregation as Phase 6's escalation_rate calc, just
grouped by week instead of by report period.
"""

FETCH_WEEKLY_SEVERITY_COUNTS_QUERY = """
MATCH (a:AgentAssessment {customer_id: $customer_id})
WHERE a.created_at IS NOT NULL
WITH date.truncate('week', a.created_at) AS week_start,
     coalesce(a.severity, 'needs_review') AS severity
RETURN toString(week_start) AS week_start, severity, count(*) AS assessment_count
ORDER BY week_start
"""


def fetch_weekly_severity_counts(session, customer_id: str) -> list[dict]:
    records = session.run(FETCH_WEEKLY_SEVERITY_COUNTS_QUERY, parameters={"customer_id": customer_id})
    return [dict(r) for r in records]