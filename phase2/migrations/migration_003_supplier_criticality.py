# phase2/migrations/003_supplier_criticality.py

from neo4j import GraphDatabase
import os

URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER     = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "supply_chain_secret")

VALID_VALUES = {"critical", "standard"}

# ─────────────────────────────────────────────
# STEP 1: Default all suppliers to 'standard'
# (fail toward not-alerting on unclassified data)
# ─────────────────────────────────────────────
DEFAULT_BACKFILL = """
MATCH (s:Supplier)
WHERE s.component_criticality IS NULL
SET s.component_criticality = 'standard'
"""

# ─────────────────────────────────────────────
# STEP 2: Explicit overrides — fill this in based on
# Step 1's query output and your own domain knowledge
# of what each Tier 2 supplier actually produces.
# ─────────────────────────────────────────────
CRITICAL_OVERRIDES = [
    "supp_apex_asml",
    "supp_nov_evonik",
    "supp_sky_solvay",
    "supp_sky_teledyne"
]

SET_CRITICAL = """
MATCH (s:Supplier)
WHERE s.supplier_id IN $supplier_ids
SET s.component_criticality = 'critical'
"""

# ─────────────────────────────────────────────
# STEP 3: Index — Phase 4 will filter on this
# ─────────────────────────────────────────────
INDEX = (
    "component_criticality — Phase 4 Tier 2 alert threshold: only alert "
    "when severity IN ['high','critical'] AND component_criticality = 'critical'",
    "CREATE INDEX supplier_component_criticality IF NOT EXISTS "
    "FOR (s:Supplier) ON (s.component_criticality)"
)


def run_migration():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))

    print("\n── Migration 003: Supplier component_criticality ──\n")

    with driver.session() as session:
        print("Step 1: Defaulting all suppliers to 'standard'...")
        result = session.run(DEFAULT_BACKFILL)
        print(f"  ✓ Defaulted {result.consume().counters.properties_set} properties")

        if CRITICAL_OVERRIDES:
            print(f"\nStep 2: Applying {len(CRITICAL_OVERRIDES)} critical overrides...")
            result = session.run(SET_CRITICAL, supplier_ids=CRITICAL_OVERRIDES)
            print(f"  ✓ Set {result.consume().counters.properties_set} suppliers to 'critical'")
        else:
            print("\nStep 2: SKIPPED — CRITICAL_OVERRIDES is empty.")
            print("  ⚠ Fill in CRITICAL_OVERRIDES with real supplier_ids before "
                  "Phase 4 alert logic will distinguish any suppliers as critical.")

        print("\nStep 3: Creating index...")
        try:
            session.run(INDEX[1])
            print(f"  ✓ {INDEX[0][:70]}")
        except Exception as e:
            print(f"  ✗ Index creation failed: {e}")

        # Verification
        print("\n── Verification ──")
        verify = session.run("""
            MATCH (s:Supplier)
            RETURN s.component_criticality AS criticality, count(s) AS count
            ORDER BY criticality
        """)
        for record in verify:
            print(f"  {record['criticality']}: {record['count']} suppliers")

    driver.close()
    print("\n── Migration complete ──\n")


if __name__ == "__main__":
    run_migration()