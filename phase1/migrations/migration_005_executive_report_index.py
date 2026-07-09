"""
Phase 6 — migration_005_executive_report_index.py

Indexes for ExecutiveReport, matching the pattern in
migration_004_impacts_indexes.py. No uniqueness constraint on report_id
is added — Neo4j 5.18 Community Edition supports property existence/type
constraints but not composite uniqueness across the fields that make up
this MERGE key in the way we'd want; idempotency here, as with IMPACTS,
relies entirely on the application-level MERGE in persist_report.py.
"""

CREATE_INDEXES = [
    "CREATE INDEX executive_report_customer_id IF NOT EXISTS "
    "FOR (r:ExecutiveReport) ON (r.customer_id)",

    "CREATE INDEX executive_report_period_start IF NOT EXISTS "
    "FOR (r:ExecutiveReport) ON (r.period_start)",

    "CREATE INDEX executive_report_status IF NOT EXISTS "
    "FOR (r:ExecutiveReport) ON (r.status)",
]


def run_migration(session):
    for statement in CREATE_INDEXES:
        session.run(statement)