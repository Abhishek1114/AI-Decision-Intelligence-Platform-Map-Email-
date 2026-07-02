"""
Migration 004 — Phase 4 IMPACTS relationship indexes.

Neo4j 5.18 Community Edition does not support relationship uniqueness/key
constraints (Enterprise-only), so IMPACTS relationships rely entirely on
the application-level MERGE key (event_id + customer_id + supplier_id) in
phase4/cypher_queries.py::WRITE_IMPACTS for idempotency -- there is no
schema-level constraint backing this, unlike GlobalEvent.event_id or
Supplier.supplier_id. Worth remembering if IMPACTS ever looks duplicated:
the fix is in the Cypher MERGE pattern, not a constraint you can add here.

This migration adds relationship property indexes to support the query
patterns Phase 4 (and any downstream dashboard) will run most: filtering
to triggered alerts, and time-windowed audit queries.
"""

import os

from neo4j import Driver, GraphDatabase

MIGRATION_QUERIES = [
    """
    CREATE INDEX impacts_alert_triggered IF NOT EXISTS
    FOR ()-[r:IMPACTS]-() ON (r.alert_triggered)
    """,
    """
    CREATE INDEX impacts_calculated_at IF NOT EXISTS
    FOR ()-[r:IMPACTS]-() ON (r.calculated_at)
    """,
    """
    CREATE INDEX impacts_supplier_id IF NOT EXISTS
    FOR ()-[r:IMPACTS]-() ON (r.supplier_id)
    """,
]

VERIFICATION_QUERY = """
SHOW INDEXES WHERE type = 'RANGE' AND entityType = 'RELATIONSHIP'
"""


def run_migration(driver: Driver) -> None:
    with driver.session() as session:
        for query in MIGRATION_QUERIES:
            session.run(query)


def verify(driver: Driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(VERIFICATION_QUERY)
        return [dict(record) for record in result]


if __name__ == "__main__":
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI","bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER","neo4j"), os.getenv("NEO4J_PASSWORD","supply_chain_secret"))
    )
    try:
        run_migration(driver)
        print("Migration 004 applied.")
        for row in verify(driver):
            print(row)
    finally:
        driver.close()