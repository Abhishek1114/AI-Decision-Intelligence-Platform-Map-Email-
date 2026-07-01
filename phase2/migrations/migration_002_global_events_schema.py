# phase2/migrations/002_global_events_schema.py

from neo4j import GraphDatabase
import os

URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "supply_chain_secret")

# ─────────────────────────────────────────────
# CONSTRAINTS
# ─────────────────────────────────────────────
CONSTRAINTS = [
    (
        "GlobalEvent uniqueness on event_id",
        "CREATE CONSTRAINT global_event_id IF NOT EXISTS "
        "FOR (e:GlobalEvent) REQUIRE e.event_id IS UNIQUE"
    ),
]

# ─────────────────────────────────────────────
# STANDARD INDEXES
# ─────────────────────────────────────────────
# Every index here has a documented reason.
# Phase 4 query patterns drive every decision.
INDEXES = [
    (
        "country — Phase 4 first-pass filter: which events are in the same "
        "country as a customer's factory/port?",
        "CREATE INDEX global_event_country IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.country)"
    ),
    (
        "event_type — Phase 4 filters by type before running geo match "
        "(earthquakes only matched against factories, not ports)",
        "CREATE INDEX global_event_type IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.event_type)"
    ),
    (
        "severity — Phase 4 tier2_alert_threshold: only propagate to "
        "Tier 2 suppliers when severity = high | critical",
        "CREATE INDEX global_event_severity IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.severity)"
    ),
    (
        "processed — real-time pipeline queries 'unprocessed events in last "
        "5 min'. Without this, full scan across all GlobalEvent nodes.",
        "CREATE INDEX global_event_processed IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.processed)"
    ),
    (
        "occurred_at — event ordering, dedup sweep, and time-window queries",
        "CREATE INDEX global_event_occurred_at IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.occurred_at)"
    ),
    (
        "source — dedup DAG filters by source frequently. "
        "Without this, full scan across potentially millions of events.",
        "CREATE INDEX global_event_source IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.source)"
    ),
    (
        "ingested_at — real-time pipeline queries 'ingested in last 5 min "
        "that have not been processed yet'. Gets slower every day without this.",
        "CREATE INDEX global_event_ingested_at IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.ingested_at)"
    ),
    (
        "source_tier — Phase 4 alert threshold logic: Tier 2 suppliers only "
        "alert when source_tier = tier1 AND severity = high | critical",
        "CREATE INDEX global_event_source_tier IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.source_tier)"
    ),
]

# ─────────────────────────────────────────────
# POINT INDEX
# ─────────────────────────────────────────────
# Requires special syntax — CREATE POINT INDEX, not CREATE INDEX.
# Phase 4's core geo query:
#   "Which of this customer's factories are within 100km of this event?"
# Without this, every geo query does a full node scan.
# Same pattern used in Phase 1 for Factory and Port nodes.
POINT_INDEXES = [
    (
        "location POINT index — Phase 4 geo-proximity matching within 100km radius",
        "CREATE POINT INDEX global_event_location IF NOT EXISTS "
        "FOR (e:GlobalEvent) ON (e.location)"
    ),
]

# ─────────────────────────────────────────────
# source_tier DOCUMENTATION
# ─────────────────────────────────────────────
# Not an index — a schema contract for Phase 4.
#
# Property: source_tier (string, lowercase enum)
# Values:   "tier1" | "tier2"
#
# tier1 events  → always propagate to Phase 4 customer matching,
#                 regardless of severity.
#                 Sources: usgs, portwatch, open_meteo
#                 Rationale: precise, structured, geo-tagged data.
#                 A M5.0 earthquake is always worth checking.
#
# tier2 events  → only propagate to Phase 4 when severity = "high" | "critical"
#                 Sources: gdelt, newsapi, google_news
#                 Rationale: news articles are noisy. A "medium" severity
#                 Google News article about vague supply chain tension should
#                 not trigger a customer alert. Only high/critical news events
#                 are worth the Phase 4 matching compute.
#
# Set in normaliser.py — not hardcoded on the model — because the same
# source can theoretically produce both tier1 and tier2 events in future.
SOURCE_TIER_MAP = {
    "usgs":        "tier1",
    "portwatch":   "tier1",
    "open_meteo":  "tier1",
    "gdelt":       "tier2",
    "newsapi":     "tier2",
    "google_news": "tier2",
    "manual":      "tier1",   # manually entered events always propagate
}


def run_migration():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    errors = []

    print("\n── Phase 2 migration: GlobalEvent schema ──\n")

    with driver.session() as session:

        print("Constraints:")
        for label, stmt in CONSTRAINTS:
            try:
                session.run(stmt)
                print(f"  ✓ {label}")
            except Exception as e:
                print(f"  ✗ {label}")
                print(f"    Error: {e}")
                errors.append((label, e))

        print("\nStandard indexes:")
        for label, stmt in INDEXES:
            try:
                session.run(stmt)
                print(f"  ✓ {label[:70]}")
            except Exception as e:
                print(f"  ✗ {label[:70]}")
                print(f"    Error: {e}")
                errors.append((label, e))

        print("\nPoint indexes:")
        for label, stmt in POINT_INDEXES:
            try:
                session.run(stmt)
                print(f"  ✓ {label}")
            except Exception as e:
                print(f"  ✗ {label}")
                print(f"    Error: {e}")
                errors.append((label, e))

    driver.close()

    print(f"\n── Migration complete ──")
    print(f"   Statements run : {len(CONSTRAINTS) + len(INDEXES) + len(POINT_INDEXES)}")
    print(f"   Errors         : {len(errors)}")

    if errors:
        print("\nFailed statements (schema may be partial — review before continuing):")
        for label, err in errors:
            print(f"  • {label}: {err}")
        raise RuntimeError(
            f"Migration finished with {len(errors)} error(s). "
            "Review output above before running Phase 3."
        )


if __name__ == "__main__":
    run_migration()