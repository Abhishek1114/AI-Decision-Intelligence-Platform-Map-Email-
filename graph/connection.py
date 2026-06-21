"""
graph/connection.py
Neo4j driver lifecycle manager.
Usage:
    with Neo4jConnection() as conn:
        conn.run("RETURN 1")

    # Or as a module-level singleton:
    from graph.connection import get_driver
    driver = get_driver()
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver, Session
from neo4j.exceptions import ServiceUnavailable, AuthError

load_dotenv()
logger = logging.getLogger(__name__)


class Neo4jConnection:
    """
    Thread-safe singleton wrapper around the Neo4j driver.
    The driver maintains its own connection pool — create ONE instance per process.
    """

    _driver: Optional[Driver] = None

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ):
        self.uri      = uri      or os.getenv("NEO4J_URI",      "bolt://localhost:7687")
        self.user     = user     or os.getenv("NEO4J_USER",     "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")

    # ── Context manager ──────────────────────────────────────────
    def __enter__(self) -> "Neo4jConnection":
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ── Driver lifecycle ──────────────────────────────────────────
    def connect(self) -> Driver:
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                    max_connection_pool_size=50,
                    connection_acquisition_timeout=30,
                )
                self._driver.verify_connectivity()
                logger.info("✅ Connected to Neo4j at %s", self.uri)
            except AuthError as e:
                raise RuntimeError(f"Neo4j auth failed — check NEO4J_USER/PASSWORD: {e}") from e
            except ServiceUnavailable as e:
                raise RuntimeError(f"Neo4j unreachable at {self.uri} — is Docker running? {e}") from e
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("🔌 Neo4j driver closed")

    # ── Query helpers ─────────────────────────────────────────────
    def session(self, **kwargs) -> Session:
        """Return a new session bound to the configured database."""
        return self._driver.session(database=self.database, **kwargs)

    def run(self, query: str, parameters: Optional[dict] = None) -> list[dict]:
        """
        Execute a Cypher query and return all records as plain dicts.
        For write queries, wraps in an explicit transaction.
        """
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def run_write(self, query: str, parameters: Optional[dict] = None) -> list[dict]:
        """Execute a write transaction (auto-commit on success, rollback on error)."""
        def _tx(tx):
            return [r.data() for r in tx.run(query, parameters or {})]
        with self.session() as session:
            return session.execute_write(_tx)

    def run_many(self, statements: list[tuple[str, dict]]) -> None:
        """
        Execute multiple (query, params) pairs in a single write transaction.
        Useful for bulk seeding.
        """
        def _tx(tx):
            for query, params in statements:
                tx.run(query, params)
        with self.session() as session:
            session.execute_write(_tx)


# Module-level singleton — import this in application code
_global_conn: Optional[Neo4jConnection] = None


def get_connection() -> Neo4jConnection:
    """Return the module-level singleton connection (connect on first call)."""
    global _global_conn
    if _global_conn is None or _global_conn._driver is None:
        _global_conn = Neo4jConnection()
        _global_conn.connect()
    return _global_conn


def close_connection():
    global _global_conn
    if _global_conn:
        _global_conn.close()
        _global_conn = None