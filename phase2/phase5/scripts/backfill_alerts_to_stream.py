"""
Phase 5 — One-off backfill: push existing alert_triggered=true IMPACTS
relationships onto the Redis stream.

This does NOT replace wiring produce_alert() into Phase 4's write path —
it's a stopgap so you can test Phase 5 end-to-end against real, already-matched
events right now, without waiting for that Phase 4 edit. Once Phase 4 is wired,
new alerts flow automatically; this script is only for the backlog that
accumulated before that wiring existed.

Safe to re-run: check_duplicate in agent/graph.py will skip anything already
assessed (title-hash dedup), so pushing the same event twice just costs one
extra Redis message, not a duplicate Groq call.

Usage:
    docker compose exec phase5_agent_consumer python -m phase2.phase5.scripts.backfill_alerts_to_stream
"""
from __future__ import annotations
import os
import logging
from neo4j import GraphDatabase


from phase2.phase5.streaming.redis_stream import get_redis_client, produce_alert

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phase5.backfill_alerts")


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    )
    redis_client = get_redis_client(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
    )

    query = """
    MATCH (e:GlobalEvent)-[r:IMPACTS {alert_triggered: true}]->(c:Customer)
    RETURN e.event_id AS event_id, e.title AS title, e.description AS description,
           c.customer_id AS customer_id, r.supplier_id AS supplier_id
    """

    count = 0
    with driver.session() as session:
        for record in session.run(query):
            event_text = f"{record['title'] or ''}. {record['description'] or ''}".strip()
            produce_alert(
                redis_client,
                customer_id=record["customer_id"],
                event_id=record["event_id"],
                supplier_id=record["supplier_id"],
                title=record["title"] or "",
                event_text=event_text,
            )
            count += 1
            logger.info(
                f"Queued event={record['event_id']} customer={record['customer_id']} "
                f"supplier={record['supplier_id']}"
            )

    logger.info(f"Done — queued {count} alert(s) onto the stream.")


if __name__ == "__main__":
    main()