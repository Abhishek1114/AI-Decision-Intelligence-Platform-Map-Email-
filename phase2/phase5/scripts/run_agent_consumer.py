"""
Phase 5 — Consumer entrypoint. Run this as a long-lived process (separate
container or Airflow-managed process) that drains the Redis Stream and
invokes the LangGraph agent per alert.
"""
import os
import logging
from neo4j import GraphDatabase
from groq import Groq
import chromadb

from phase2.phase5.agent.graph import run_agent_for_impact
from phase2.phase5.streaming.redis_stream import get_redis_client, consume_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phase5.consumer")


def main():
    neo4j_driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    chroma_client = chromadb.HttpClient(
        host=os.environ.get("CHROMADB_HOST", "chromadb"),
        port=int(os.environ.get("CHROMADB_PORT", 8000)),
    )
    redis_client = get_redis_client(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
    )

    def handler(customer_id: str, event_id: str, supplier_id: str, title: str, event_text: str):
        result = run_agent_for_impact(
            neo4j_driver, chroma_client, groq_client, customer_id, event_id,
            supplier_id, title, event_text,
        )
        if result.status.value == "needs_review":
            logger.warning(f"needs_review: customer={customer_id} event={event_id}")
        elif result.status.value == "duplicate_skipped":
            logger.info(
                f"duplicate_skipped: customer={customer_id} event={event_id} "
                f"-> existing assessment {result.assessment_id}"
            )
        else:
            logger.info(
                f"OK: customer={customer_id} event={event_id} "
                f"severity={result.prediction.severity} "
                f"affected_products={len(result.observed.affected_products)} "
                f"assessment_id={result.assessment_id}"
            )
        # Persistence now happens inside the graph itself (agent/graph.py's
        # "persist" node writes AgentAssessment) — nothing further needed here.

    consume_loop(redis_client, handler)


if __name__ == "__main__":
    main()