from neo4j import GraphDatabase
import os
from .config import BATCH_SIZE


class Phase3Pipeline:
    def __init__(self):
        self.driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI"),
            auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")),
        )

    def close(self):
        self.driver.close()

    def fetch_unprocessed_events(self, limit=BATCH_SIZE):
        query = """
        MATCH (e:GlobalEvent {processed: false})
        RETURN e.event_id AS event_id, e.description AS description
        LIMIT $limit
        """
        with self.driver.session() as session:
            return [dict(r) for r in session.run(query, limit=limit)]

    def fetch_known_suppliers(self):
            query = """
            MATCH (s:Supplier)
            RETURN s.supplier_id AS supplier_id, s.company_name AS name
            """
            with self.driver.session() as session:
                return [dict(r) for r in session.run(query)]

    def write_mentions_relationship(self, event_id, supplier_id, confidence, method):
        query = """
        MATCH (e:GlobalEvent {event_id: $event_id})
        MATCH (s:Supplier {supplier_id: $supplier_id})
        MERGE (e)-[m:MENTIONS]->(s)
        SET m.confidence = $confidence, m.method = $method, m.linked_at = datetime()
        """
        with self.driver.session() as session:
            session.run(query, event_id=event_id, supplier_id=supplier_id, confidence=confidence, method=method)

    def mark_processed(self, event_id):
        query = "MATCH (e:GlobalEvent {event_id: $event_id}) SET e.processed = true"
        with self.driver.session() as session:
            session.run(query, event_id=event_id)