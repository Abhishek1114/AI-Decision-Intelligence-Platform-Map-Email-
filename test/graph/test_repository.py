"""
tests/graph/test_repository.py
Integration tests for Phase 1.
Requires a live Neo4j instance (use docker-compose up neo4j).
Run: pytest tests/graph/test_repository.py -v
"""
import pytest
from datetime import datetime, timezone

from graph.connection import Neo4jConnection
from graph.queries.repository import SupplyChainRepository
from graph.models.nodes import (
    RegionNode, SupplierNode, FacilityNode, PortNode,
    ProductNode, ComponentNode, DisruptionEventNode,
    FacilityType, RiskLevel, EventType,
)
from graph.models.relationships import SuppliesRel, RequiresRel, AffectsRel


@pytest.fixture(scope="module")
def conn():
    c = Neo4jConnection()
    c.connect()
    yield c
    # Cleanup test data
    c.run("MATCH (n) WHERE n.supplier_id STARTS WITH 'TEST-' DETACH DELETE n")
    c.run("MATCH (n) WHERE n.product_id  STARTS WITH 'TEST-' DETACH DELETE n")
    c.run("MATCH (n) WHERE n.event_id    STARTS WITH 'TEST-' DETACH DELETE n")
    c.run("MATCH (n) WHERE n.region_id   = 'TEST-REGION' DETACH DELETE n")
    c.close()


@pytest.fixture(scope="module")
def repo(conn):
    return SupplyChainRepository(conn)


# ──────────────────────────────────────────────
# Node Upserts
# ──────────────────────────────────────────────

def test_upsert_region(repo):
    r = RegionNode(region_id="TEST-REGION", name="Test Region", countries=["XX"], geopolitical_risk=0.5, climate_risk=0.5)
    result = repo.upsert_region(r)
    assert result["r"]["region_id"] == "TEST-REGION"


def test_upsert_supplier(repo):
    s = SupplierNode(
        supplier_id="TEST-SUP-001", name="Acme Test Supplier",
        country="US", region_id="TEST-REGION", tier=1,
        risk_score=0.3, risk_level=RiskLevel.LOW,
    )
    result = repo.upsert_supplier(s)
    assert result["s"]["supplier_id"] == "TEST-SUP-001"


def test_upsert_supplier_idempotent(repo):
    """Running upsert twice should not create duplicate nodes."""
    s = SupplierNode(
        supplier_id="TEST-SUP-001", name="Acme Test Supplier Updated",
        country="US", region_id="TEST-REGION", tier=1,
        risk_score=0.9,  # changed
        risk_level=RiskLevel.CRITICAL,
    )
    repo.upsert_supplier(s)
    result = repo.get_supplier_by_id("TEST-SUP-001")
    assert result["risk_score"] == 0.9
    # Verify only one node exists
    count = repo.conn.run("MATCH (s:Supplier {supplier_id: 'TEST-SUP-001'}) RETURN count(s) as c")
    assert count[0]["c"] == 1


def test_upsert_product(repo):
    p = ProductNode(
        product_id="TEST-PROD-001", name="Test Widget", sku="TW-001",
        category="test", criticality=RiskLevel.HIGH,
        lead_time_days=30, safety_stock_days=7,
    )
    result = repo.upsert_product(p)
    assert result["p"]["product_id"] == "TEST-PROD-001"


def test_upsert_disruption_event(repo):
    e = DisruptionEventNode(
        event_id="TEST-EVT-001",
        event_type=EventType.WEATHER,
        title="Test Storm",
        description="Unit test event",
        severity=RiskLevel.HIGH,
        source="test",
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        is_resolved=False,
        impact_score=0.75,
    )
    result = repo.upsert_disruption_event(e)
    assert result["e"]["event_id"] == "TEST-EVT-001"


# ──────────────────────────────────────────────
# Relationships
# ──────────────────────────────────────────────

def test_link_supplier_to_region(repo):
    repo.link_supplier_to_region("TEST-SUP-001", "TEST-REGION")
    result = repo.conn.run(
        "MATCH (s:Supplier {supplier_id: 'TEST-SUP-001'})-[:LOCATED_IN]->(r:Region) RETURN r.region_id as rid"
    )
    assert result[0]["rid"] == "TEST-REGION"


def test_link_supplier_supplies_product(repo):
    rel = SuppliesRel(annual_volume_units=1000, share_of_supply_pct=100.0, lead_time_days=14)
    repo.link_supplier_supplies_product("TEST-SUP-001", "TEST-PROD-001", rel)
    result = repo.conn.run(
        "MATCH (:Supplier {supplier_id:'TEST-SUP-001'})-[r:SUPPLIES]->(:Product {product_id:'TEST-PROD-001'}) RETURN r"
    )
    assert len(result) == 1
    assert result[0]["r"]["share_of_supply_pct"] == 100.0


def test_link_event_affects_supplier(repo):
    rel = AffectsRel(impact_type="supply_delay", estimated_delay_days=5.0, confidence=0.9, detected_at=datetime.now(timezone.utc))
    repo.link_event_affects("TEST-EVT-001", "TEST-SUP-001", "Supplier", rel)
    result = repo.conn.run(
        "MATCH (:DisruptionEvent {event_id:'TEST-EVT-001'})-[r:AFFECTS]->(:Supplier {supplier_id:'TEST-SUP-001'}) RETURN r"
    )
    assert len(result) == 1
    assert result[0]["r"]["impact_type"] == "supply_delay"


# ──────────────────────────────────────────────
# Read Queries
# ──────────────────────────────────────────────

def test_get_all_active_disruptions(repo):
    results = repo.get_all_active_disruptions()
    # TEST-EVT-001 is not resolved
    event_ids = [r["e"]["event_id"] for r in results]
    assert "TEST-EVT-001" in event_ids


def test_get_affected_suppliers_for_event(repo):
    results = repo.get_affected_suppliers_for_event("TEST-EVT-001")
    supplier_ids = [r["supplier_id"] for r in results]
    assert "TEST-SUP-001" in supplier_ids


def test_graph_summary_returns_counts(repo):
    summary = repo.graph_summary()
    assert "counts" in summary
    assert len(summary["counts"]) > 0


def test_high_risk_suppliers_threshold(repo):
    """Force risk_score to 0.95 and verify it appears in high-risk query."""
    repo.conn.run_write(
        "MATCH (s:Supplier {supplier_id: 'TEST-SUP-001'}) SET s.risk_score = 0.95"
    )
    results = repo.get_high_risk_suppliers(min_risk_score=0.9)
    ids = [r["supplier_id"] for r in results]
    assert "TEST-SUP-001" in ids