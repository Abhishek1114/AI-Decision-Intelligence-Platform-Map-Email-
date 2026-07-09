"""
Migration 006: Phase 7 alert/acknowledgment tracking on AgentAssessment.
Backfills booleans explicitly — a missing property is null, and null is falsy
in WHERE clauses, so every existing row needs alert_sent/acknowledged set to
false rather than left absent (same class of trap as the datetime bug).
"""
from neo4j import GraphDatabase
import os

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://sc_neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

BACKFILL = """
MATCH (a:AgentAssessment)
WHERE a.alert_sent IS NULL
SET a.alert_sent = false,
    a.acknowledged = false
RETURN count(a) AS updated
"""

INDEXES = [
    "CREATE INDEX assessment_alert_sent   IF NOT EXISTS FOR (a:AgentAssessment) ON (a.alert_sent)",
    "CREATE INDEX assessment_severity     IF NOT EXISTS FOR (a:AgentAssessment) ON (a.severity)",
    "CREATE INDEX assessment_acknowledged IF NOT EXISTS FOR (a:AgentAssessment) ON (a.acknowledged)",
]

def run():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        for stmt in INDEXES:
            session.run(stmt)
        result = session.run(BACKFILL).single()
        print(f"Backfilled alert/ack fields on {result['updated']} AgentAssessment nodes")
    driver.close()

if __name__ == "__main__":
    run()