# phase2/raw_store/raw_event_store.py

import sqlite3
import json
from datetime import datetime
import os

DB_PATH = "/tmp/data/raw_events.db"


class RawEventStore:
    """
    SQLite store for raw payloads before normalisation.
    Survives Neo4j downtime. Provides audit trail.
    Can be replayed if normaliser logic changes.
    """

    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    source      TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload     TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_source ON raw_events(source)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_received ON raw_events(received_at)"
            )

    def save(self, source: str, payload: dict) -> int:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO raw_events (source, received_at, payload) VALUES (?, ?, ?)",
                (source, datetime.utcnow().isoformat(), json.dumps(payload))
            )
            return cursor.lastrowid

    def insert_batch(self, source: str, records: list) -> int:
            """
            Persist a batch of raw records before any processing.
            Returns count of rows inserted.
            Called by every DAG fetch task as the first step.
            """
            now = datetime.utcnow().isoformat()
            with sqlite3.connect(DB_PATH) as conn:
                conn.executemany(
                    "INSERT INTO raw_events (source, received_at, payload) VALUES (?, ?, ?)",
                    [(source, now, json.dumps(r)) for r in records]
                )
            return len(records)