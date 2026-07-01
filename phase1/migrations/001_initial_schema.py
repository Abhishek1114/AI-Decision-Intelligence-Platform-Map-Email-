"""
Phase 1 — Neo4j schema migration.
Run once against a fresh Neo4j instance.
Creates all constraints, indexes, and baseline structure.

Usage:
    python phase1/migrations/001_initial_schema.py
"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

SCHEMA_STATEMENTS = [

    # ── Uniqueness constraints (also create indexes automatically) ──────────

    # Customer — root of every supply chain
    "CREATE CONSTRAINT customer_id_unique IF NOT EXISTS "
    "FOR (n:Customer) REQUIRE n.customer_id IS UNIQUE",

    # Product
    "CREATE CONSTRAINT product_id_unique IF NOT EXISTS "
    "FOR (n:Product) REQUIRE n.product_id IS UNIQUE",

    # Component
    "CREATE CONSTRAINT component_id_unique IF NOT EXISTS "
    "FOR (n:Component) REQUIRE n.component_id IS UNIQUE",

    # Supplier
    "CREATE CONSTRAINT supplier_id_unique IF NOT EXISTS "
    "FOR (n:Supplier) REQUIRE n.supplier_id IS UNIQUE",

    # Factory
    "CREATE CONSTRAINT factory_id_unique IF NOT EXISTS "
    "FOR (n:Factory) REQUIRE n.factory_id IS UNIQUE",

    # Warehouse
    "CREATE CONSTRAINT warehouse_id_unique IF NOT EXISTS "
    "FOR (n:Warehouse) REQUIRE n.warehouse_id IS UNIQUE",

    # Port
    "CREATE CONSTRAINT port_id_unique IF NOT EXISTS "
    "FOR (n:Port) REQUIRE n.port_id IS UNIQUE",

    # Route
    "CREATE CONSTRAINT route_id_unique IF NOT EXISTS "
    "FOR (n:Route) REQUIRE n.route_id IS UNIQUE",

    # ── Additional indexes for common query patterns ─────────────────────────

    # customer_id on every node type — the multi-tenancy filter
    "CREATE INDEX product_customer_idx IF NOT EXISTS "
    "FOR (n:Product) ON (n.customer_id)",

    "CREATE INDEX component_customer_idx IF NOT EXISTS "
    "FOR (n:Component) ON (n.customer_id)",

    "CREATE INDEX supplier_customer_idx IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.customer_id)",

    "CREATE INDEX factory_customer_idx IF NOT EXISTS "
    "FOR (n:Factory) ON (n.customer_id)",

    "CREATE INDEX warehouse_customer_idx IF NOT EXISTS "
    "FOR (n:Warehouse) ON (n.customer_id)",

    "CREATE INDEX port_customer_idx IF NOT EXISTS "
    "FOR (n:Port) ON (n.customer_id)",

    "CREATE INDEX route_customer_idx IF NOT EXISTS "
    "FOR (n:Route) ON (n.customer_id)",

    # Country-based lookups (disruption matching by region)
    "CREATE INDEX supplier_country_idx IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.country)",

    "CREATE INDEX factory_country_idx IF NOT EXISTS "
    "FOR (n:Factory) ON (n.country)",

    "CREATE INDEX port_country_idx IF NOT EXISTS "
    "FOR (n:Port) ON (n.country)",

    # Risk level — for dashboard queries
    "CREATE INDEX supplier_risk_idx IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.risk_level)",

    "CREATE INDEX factory_risk_idx IF NOT EXISTS "
    "FOR (n:Factory) ON (n.risk_level)",

    "CREATE POINT INDEX supplier_location_idx IF NOT EXISTS "
    "FOR (n:Supplier) ON (n.location)",
    
    # Geo-spatial point index for factory and port locations
    # Neo4j 5.x: point index uses CREATE POINT INDEX syntax
    "CREATE POINT INDEX factory_location_idx IF NOT EXISTS "
    "FOR (n:Factory) ON (n.location)",

    "CREATE POINT INDEX port_location_idx IF NOT EXISTS "
    "FOR (n:Port) ON (n.location)",

    "CREATE POINT INDEX warehouse_location_idx IF NOT EXISTS "
    "FOR (n:Warehouse) ON (n.location)",
]


def run_migration(uri: str, user: str, password: str) -> None:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for stmt in SCHEMA_STATEMENTS:
                try:
                    session.run(stmt)
                    label = stmt.split("FOR")[1].split("ON")[0].strip()[:60]
                    print(f"  OK  {label}")
                except Exception as e:
                    print(f"  WARN  {stmt[:60]}... → {e}")
        print("\nMigration 001 complete.")
    finally:
        driver.close()


if __name__ == "__main__":
    run_migration(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "supply_chain_secret"),
    )