"""
Phase 2 — Supply Chain Global Event Ingestion Pipeline

Modules
-------
models      : Pydantic v2 GlobalEvent canonical schema
ingestion   : Source fetchers, normaliser, dedup, Neo4j writer
streams     : Redis Streams producer / consumer
webhooks    : FastAPI push receivers
raw_store   : SQLite audit trail
migrations  : Neo4j schema migration scripts
dags        : Apache Airflow DAG definitions
tests       : pytest test suite
"""
