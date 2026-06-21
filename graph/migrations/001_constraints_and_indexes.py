"""
graph/migrations/001_constraints_and_indexes.py
Idempotent schema migration — safe to re-run.
Creates:
  - Uniqueness constraints (each node label's primary key)
  - Node property existence constraints (required fields)
  - Indexes for high-cardinality lookup fields
  - Composite indexes for common query patterns

Run: python -m graph.migrations.001_constraints_and_indexes
"""
import logging
from graph.connection import Neo4jConnection

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# UNIQUENESS CONSTRAINTS (implicitly creates an index too)
# ──────────────────────────────────────────────────────────────────
UNIQUENESS_CONSTRAINTS = [
    ("Supplier",        "supplier_id",   "constraint_supplier_id_unique"),
    ("Facility",        "facility_id",   "constraint_facility_id_unique"),
    ("Port",            "port_id",       "constraint_port_id_unique"),
    ("Product",         "product_id",    "constraint_product_id_unique"),
    ("Component",       "component_id",  "constraint_component_id_unique"),
    ("Route",           "route_id",      "constraint_route_id_unique"),
    ("Region",          "region_id",     "constraint_region_id_unique"),
    ("DisruptionEvent", "event_id",      "constraint_event_id_unique"),
]

# ──────────────────────────────────────────────────────────────────
# PROPERTY EXISTENCE CONSTRAINTS (Neo4j Enterprise only — skip on Community)
# Included for documentation; guarded by try/except below.
# ──────────────────────────────────────────────────────────────────
EXISTENCE_CONSTRAINTS = [
    ("Supplier",  "name",    "constraint_supplier_name_exists"),
    ("Supplier",  "country", "constraint_supplier_country_exists"),
    ("Facility",  "name",    "constraint_facility_name_exists"),
    ("Port",      "name",    "constraint_port_name_exists"),
    ("Product",   "name",    "constraint_product_name_exists"),
    ("Component", "name",    "constraint_component_name_exists"),
]

# ──────────────────────────────────────────────────────────────────
# RANGE INDEXES (for WHERE / ORDER BY on non-id fields)
# ──────────────────────────────────────────────────────────────────
RANGE_INDEXES = [
    # Supplier
    ("Supplier", ["country"],    "idx_supplier_country"),
    ("Supplier", ["tier"],       "idx_supplier_tier"),
    ("Supplier", ["risk_level"], "idx_supplier_risk_level"),

    # Facility
    ("Facility", ["country"],         "idx_facility_country"),
    ("Facility", ["facility_type"],   "idx_facility_type"),
    ("Facility", ["is_active"],       "idx_facility_active"),

    # Port
    ("Port", ["country"],           "idx_port_country"),
    ("Port", ["congestion_index"],  "idx_port_congestion"),
    ("Port", ["port_type"],         "idx_port_type"),

    # Product
    ("Product", ["criticality"],  "idx_product_criticality"),
    ("Product", ["category"],     "idx_product_category"),

    # DisruptionEvent
    ("DisruptionEvent", ["event_type"],   "idx_event_type"),
    ("DisruptionEvent", ["severity"],     "idx_event_severity"),
    ("DisruptionEvent", ["is_resolved"],  "idx_event_resolved"),
    ("DisruptionEvent", ["started_at"],   "idx_event_started_at"),
]

# ──────────────────────────────────────────────────────────────────
# POINT INDEXES (for geospatial queries on lat/lon encoded as Neo4j point)
# ──────────────────────────────────────────────────────────────────
POINT_INDEXES = [
    ("Facility", "location", "idx_facility_location"),
    ("Port",     "location", "idx_port_location"),
]


def run_migration(conn: Neo4jConnection):
    logger.info("🚀 Starting schema migration 001...")

    # 1. Uniqueness constraints
    for label, prop, name in UNIQUENESS_CONSTRAINTS:
        cypher = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
        )
        try:
            conn.run(cypher)
            logger.info("  ✅ Constraint: %s", name)
        except Exception as e:
            logger.warning("  ⚠️  Constraint %s skipped: %s", name, e)

    # 2. Existence constraints (Enterprise only — graceful skip)
    for label, prop, name in EXISTENCE_CONSTRAINTS:
        cypher = (
            f"CREATE CONSTRAINT {name} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{prop} IS NOT NULL"
        )
        try:
            conn.run(cypher)
            logger.info("  ✅ Existence constraint: %s", name)
        except Exception as e:
            logger.info("  ℹ️  Existence constraint %s skipped (Community edition): %s", name, e)

    # 3. Range indexes
    for label, props, name in RANGE_INDEXES:
        props_str = ", ".join(f"n.{p}" for p in props)
        cypher = (
            f"CREATE INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON ({props_str})"
        )
        try:
            conn.run(cypher)
            logger.info("  ✅ Index: %s", name)
        except Exception as e:
            logger.warning("  ⚠️  Index %s skipped: %s", name, e)

    # 4. Point indexes (for geospatial proximity queries)
    for label, prop, name in POINT_INDEXES:
        cypher = (
            f"CREATE POINT INDEX {name} IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.{prop})"
        )
        try:
            conn.run(cypher)
            logger.info("  ✅ Point index: %s", name)
        except Exception as e:
            logger.warning("  ⚠️  Point index %s skipped: %s", name, e)

    logger.info("✅ Migration 001 complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with Neo4jConnection() as conn:
        run_migration(conn)