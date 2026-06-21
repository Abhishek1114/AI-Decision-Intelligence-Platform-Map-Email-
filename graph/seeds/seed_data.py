"""
graph/seeds/seed_data.py
Realistic seed fixture for a consumer electronics supply chain.
Covers: semiconductors, lithium batteries, display panels.
Tier structure: 3 Tier-1 suppliers → Tier-2 component makers → Tier-3 raw materials.

Run: python -m graph.seeds.seed_data
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from graph.connection import Neo4jConnection
from graph.queries.repository import SupplyChainRepository
from graph.models.nodes import (
    RegionNode, SupplierNode, FacilityNode, PortNode,
    ProductNode, ComponentNode, RouteNode, DisruptionEventNode,
    FacilityType, TransportMode, RiskLevel, EventType,
)
from graph.models.relationships import (
    SuppliesRel, RequiresRel, ConnectsToRel, AffectsRel, SubSupplierOfRel,
)

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def seed(repo: SupplyChainRepository):
    logger.info("🌱 Seeding supply chain graph...")

    # ──────────────────────────────────────────────
    # 1. REGIONS
    # ──────────────────────────────────────────────
    regions = [
        RegionNode(region_id="APAC",  name="Asia Pacific",   countries=["TW","KR","JP","CN","SG","MY","VN"], geopolitical_risk=0.55, climate_risk=0.60),
        RegionNode(region_id="EU",    name="Europe",          countries=["DE","NL","PL","FR","SE","FI"],      geopolitical_risk=0.30, climate_risk=0.25),
        RegionNode(region_id="NA",    name="North America",   countries=["US","MX","CA"],                     geopolitical_risk=0.20, climate_risk=0.30),
        RegionNode(region_id="LATAM", name="Latin America",   countries=["BR","CL","AR","CO"],                geopolitical_risk=0.55, climate_risk=0.45),
    ]
    for r in regions:
        repo.upsert_region(r)

    # ──────────────────────────────────────────────
    # 2. SUPPLIERS
    # ──────────────────────────────────────────────
    suppliers = [
        # Tier 1 — direct suppliers
        SupplierNode(supplier_id="SUP-001", name="TSMC",           country="TW", region_id="APAC", tier=1, risk_score=0.45, risk_level=RiskLevel.MEDIUM,  is_single_source=True,  certifications=["ISO9001","IATF16949"]),
        SupplierNode(supplier_id="SUP-002", name="Samsung SDI",    country="KR", region_id="APAC", tier=1, risk_score=0.30, risk_level=RiskLevel.LOW,     is_single_source=False, certifications=["ISO9001"]),
        SupplierNode(supplier_id="SUP-003", name="LG Display",     country="KR", region_id="APAC", tier=1, risk_score=0.35, risk_level=RiskLevel.LOW,     is_single_source=False),
        # Tier 2 — sub-suppliers
        SupplierNode(supplier_id="SUP-011", name="Shin-Etsu Chem", country="JP", region_id="APAC", tier=2, risk_score=0.40, risk_level=RiskLevel.MEDIUM),
        SupplierNode(supplier_id="SUP-012", name="Albemarle Corp", country="US", region_id="NA",   tier=2, risk_score=0.25, risk_level=RiskLevel.LOW),
        SupplierNode(supplier_id="SUP-013", name="Corning Inc",    country="US", region_id="NA",   tier=2, risk_score=0.20, risk_level=RiskLevel.LOW),
        # Tier 3 — raw materials
        SupplierNode(supplier_id="SUP-021", name="Sociedad Química y Minera", country="CL", region_id="LATAM", tier=3, risk_score=0.50, risk_level=RiskLevel.MEDIUM),
        SupplierNode(supplier_id="SUP-022", name="Ganfeng Lithium",           country="CN", region_id="APAC",  tier=3, risk_score=0.70, risk_level=RiskLevel.HIGH, is_single_source=True),
    ]
    for s in suppliers:
        repo.upsert_supplier(s)
        repo.link_supplier_to_region(s.supplier_id, s.region_id)

    # ──────────────────────────────────────────────
    # 3. FACILITIES
    # ──────────────────────────────────────────────
    facilities = [
        FacilityNode(facility_id="FAC-001", supplier_id="SUP-001", name="TSMC Fab 18 (Phoenix)",     facility_type=FacilityType.FACTORY,    country="US", city="Phoenix",       latitude=33.4484,  longitude=-112.0740, capacity_units_per_day=50000,  utilization_pct=95.0),
        FacilityNode(facility_id="FAC-002", supplier_id="SUP-001", name="TSMC Fab 12 (Hsinchu)",    facility_type=FacilityType.FACTORY,    country="TW", city="Hsinchu",       latitude=24.8138,  longitude=120.9675,  capacity_units_per_day=200000, utilization_pct=98.5),
        FacilityNode(facility_id="FAC-003", supplier_id="SUP-002", name="Samsung SDI Ulsan",        facility_type=FacilityType.FACTORY,    country="KR", city="Ulsan",         latitude=35.5384,  longitude=129.3114,  capacity_units_per_day=80000,  utilization_pct=82.0),
        FacilityNode(facility_id="FAC-004", supplier_id="SUP-003", name="LG Display Gumi",          facility_type=FacilityType.FACTORY,    country="KR", city="Gumi",          latitude=36.1097,  longitude=128.3442,  capacity_units_per_day=60000,  utilization_pct=78.0),
        FacilityNode(facility_id="FAC-005", supplier_id="SUP-012", name="Albemarle Silver Peak",    facility_type=FacilityType.FACTORY,    country="US", city="Silver Peak",   latitude=38.1144,  longitude=-117.6364, capacity_units_per_day=5000,   utilization_pct=65.0),
        FacilityNode(facility_id="FAC-006", supplier_id="SUP-021", name="SQM Atacama Plant",        facility_type=FacilityType.FACTORY,    country="CL", city="Antofagasta",   latitude=-23.6524, longitude=-70.3954,  capacity_units_per_day=3000,   utilization_pct=90.0),
    ]
    for f in facilities:
        repo.upsert_facility(f)
        repo.link_facility_to_supplier(f.supplier_id, f.facility_id)
        # Find region_id from supplier
        sup = next(s for s in suppliers if s.supplier_id == f.supplier_id)
        repo.link_facility_to_region(f.facility_id, sup.region_id)

    # ──────────────────────────────────────────────
    # 4. PORTS
    # ──────────────────────────────────────────────
    ports = [
        PortNode(port_id="TWKHH", name="Port of Kaohsiung",   country="TW", city="Kaohsiung", port_type="sea", latitude=22.6139,  longitude=120.2780, throughput_teu_annual=10_000_000, congestion_index=0.55, avg_dwell_days=3.2, region_id="APAC"),
        PortNode(port_id="KRPUS", name="Port of Busan",        country="KR", city="Busan",     port_type="sea", latitude=35.1028,  longitude=129.0403, throughput_teu_annual=22_000_000, congestion_index=0.40, avg_dwell_days=2.8, region_id="APAC"),
        PortNode(port_id="SGSIN", name="Port of Singapore",    country="SG", city="Singapore", port_type="sea", latitude=1.2897,   longitude=103.8501, throughput_teu_annual=37_000_000, congestion_index=0.35, avg_dwell_days=2.1, region_id="APAC"),
        PortNode(port_id="USLAX", name="Port of Los Angeles",  country="US", city="Los Angeles", port_type="sea", latitude=33.7395, longitude=-118.2615, throughput_teu_annual=9_900_000, congestion_index=0.30, avg_dwell_days=4.5, region_id="NA"),
        PortNode(port_id="NLRTM", name="Port of Rotterdam",    country="NL", city="Rotterdam", port_type="sea", latitude=51.9225,  longitude=4.4792,   throughput_teu_annual=14_800_000, congestion_index=0.25, avg_dwell_days=2.4, region_id="EU"),
        PortNode(port_id="USLGB", name="Port of Long Beach",   country="US", city="Long Beach", port_type="sea", latitude=33.7542, longitude=-118.2165, throughput_teu_annual=8_100_000, congestion_index=0.28, avg_dwell_days=3.8, region_id="NA"),
    ]
    for p in ports:
        repo.upsert_port(p)

    # ──────────────────────────────────────────────
    # 5. PRODUCTS
    # ──────────────────────────────────────────────
    products = [
        ProductNode(product_id="PROD-001", name="Consumer Laptop",     sku="LAPTOP-PRO-X1", category="computing",  criticality=RiskLevel.HIGH,   lead_time_days=45, safety_stock_days=14, unit_cost_usd=850.0),
        ProductNode(product_id="PROD-002", name="Smartphone Module",   sku="PHONE-MOD-A15", category="mobile",     criticality=RiskLevel.CRITICAL,lead_time_days=60, safety_stock_days=21, unit_cost_usd=320.0),
        ProductNode(product_id="PROD-003", name="EV Battery Pack",     sku="BATT-EV-72KWH", category="automotive", criticality=RiskLevel.CRITICAL,lead_time_days=90, safety_stock_days=30, unit_cost_usd=12000.0),
    ]
    for p in products:
        repo.upsert_product(p)

    # ──────────────────────────────────────────────
    # 6. COMPONENTS
    # ──────────────────────────────────────────────
    components = [
        ComponentNode(component_id="COMP-001", name="3nm Logic Chip",         material_type="semiconductor", hs_code="8542.31", substitutability=RiskLevel.CRITICAL),
        ComponentNode(component_id="COMP-002", name="LPDDR5 Memory",          material_type="semiconductor", hs_code="8542.32", substitutability=RiskLevel.HIGH),
        ComponentNode(component_id="COMP-003", name="Lithium-Ion Cell (NMC)", material_type="battery_cell",  hs_code="8507.60", substitutability=RiskLevel.HIGH,     is_hazmat=True),
        ComponentNode(component_id="COMP-004", name="OLED Display Panel",     material_type="display",       hs_code="8524.11", substitutability=RiskLevel.MEDIUM),
        ComponentNode(component_id="COMP-005", name="Lithium Carbonate",      material_type="rare_earth",    hs_code="2836.91", substitutability=RiskLevel.HIGH),
        ComponentNode(component_id="COMP-006", name="Silicon Wafer (300mm)",  material_type="semiconductor", hs_code="3818.00", substitutability=RiskLevel.MEDIUM),
    ]
    for c in components:
        repo.upsert_component(c)

    # ──────────────────────────────────────────────
    # 7. ROUTES
    # ──────────────────────────────────────────────
    routes = [
        RouteNode(route_id="RT-001", origin_id="TWKHH", destination_id="USLAX", transport_mode=TransportMode.SEA, distance_km=11_000, transit_days_avg=14.0, transit_days_std=2.0, carrier="Evergreen"),
        RouteNode(route_id="RT-002", origin_id="KRPUS", destination_id="USLAX", transport_mode=TransportMode.SEA, distance_km=9_500,  transit_days_avg=12.0, transit_days_std=1.5, carrier="HMM"),
        RouteNode(route_id="RT-003", origin_id="SGSIN", destination_id="NLRTM", transport_mode=TransportMode.SEA, distance_km=15_600, transit_days_avg=22.0, transit_days_std=3.0, carrier="Maersk"),
        RouteNode(route_id="RT-004", origin_id="KRPUS", destination_id="NLRTM", transport_mode=TransportMode.SEA, distance_km=20_000, transit_days_avg=28.0, transit_days_std=4.0, carrier="MSC"),
    ]
    for r in routes:
        repo.upsert_route(r)

    # ──────────────────────────────────────────────
    # 8. RELATIONSHIPS
    # ──────────────────────────────────────────────

    # Supplier → Product
    repo.link_supplier_supplies_product("SUP-001", "PROD-001", SuppliesRel(annual_volume_units=2_000_000, share_of_supply_pct=100.0, lead_time_days=30, is_preferred=True))
    repo.link_supplier_supplies_product("SUP-001", "PROD-002", SuppliesRel(annual_volume_units=5_000_000, share_of_supply_pct=100.0, lead_time_days=45, is_preferred=True))
    repo.link_supplier_supplies_product("SUP-002", "PROD-003", SuppliesRel(annual_volume_units=500_000,   share_of_supply_pct=65.0,  lead_time_days=60, is_preferred=True))
    repo.link_supplier_supplies_product("SUP-003", "PROD-001", SuppliesRel(annual_volume_units=2_000_000, share_of_supply_pct=80.0,  lead_time_days=30, is_preferred=True))

    # Product → Component
    repo.link_product_requires_component("PROD-001", "COMP-001", RequiresRel(quantity_per_unit=1.0, is_critical=True))
    repo.link_product_requires_component("PROD-001", "COMP-004", RequiresRel(quantity_per_unit=1.0, is_critical=True))
    repo.link_product_requires_component("PROD-002", "COMP-001", RequiresRel(quantity_per_unit=1.0, is_critical=True))
    repo.link_product_requires_component("PROD-002", "COMP-002", RequiresRel(quantity_per_unit=2.0, is_critical=True))
    repo.link_product_requires_component("PROD-003", "COMP-003", RequiresRel(quantity_per_unit=288.0, unit_of_measure="cell", is_critical=True))
    repo.link_product_requires_component("PROD-003", "COMP-005", RequiresRel(quantity_per_unit=50.0, unit_of_measure="kg", is_critical=True))

    # Component → Supplier (sourced from)
    repo.link_component_sourced_from("COMP-001", "SUP-001")
    repo.link_component_sourced_from("COMP-002", "SUP-001")
    repo.link_component_sourced_from("COMP-003", "SUP-002")
    repo.link_component_sourced_from("COMP-004", "SUP-003")
    repo.link_component_sourced_from("COMP-005", "SUP-021")
    repo.link_component_sourced_from("COMP-005", "SUP-022")
    repo.link_component_sourced_from("COMP-006", "SUP-011")

    # Sub-supplier chain
    repo.link_subsupplier("SUP-011", "SUP-001", SubSupplierOfRel(tier_from=2, tier_to=1, component_ids=["COMP-006"]))  # Shin-Etsu → TSMC
    repo.link_subsupplier("SUP-012", "SUP-002", SubSupplierOfRel(tier_from=2, tier_to=1, component_ids=["COMP-005"]))  # Albemarle → Samsung SDI
    repo.link_subsupplier("SUP-021", "SUP-012", SubSupplierOfRel(tier_from=3, tier_to=2, component_ids=["COMP-005"]))  # SQM → Albemarle
    repo.link_subsupplier("SUP-022", "SUP-002", SubSupplierOfRel(tier_from=3, tier_to=1, component_ids=["COMP-005"]))  # Ganfeng → Samsung SDI

    # Facility → Port
    repo.link_facility_ships_via_port("FAC-002", "TWKHH")
    repo.link_facility_ships_via_port("FAC-003", "KRPUS")
    repo.link_facility_ships_via_port("FAC-004", "KRPUS")
    repo.link_facility_ships_via_port("FAC-006", "USLAX")   # SQM ships through LA

    # Port → Port lanes
    repo.link_port_to_port("TWKHH", "USLAX", ConnectsToRel(transport_mode="sea", distance_km=11000, transit_days_avg=14.0, weekly_sailings=7))
    repo.link_port_to_port("KRPUS", "USLAX", ConnectsToRel(transport_mode="sea", distance_km=9500,  transit_days_avg=12.0, weekly_sailings=14))
    repo.link_port_to_port("SGSIN", "NLRTM", ConnectsToRel(transport_mode="sea", distance_km=15600, transit_days_avg=22.0, weekly_sailings=5))
    repo.link_port_to_port("KRPUS", "NLRTM", ConnectsToRel(transport_mode="sea", distance_km=20000, transit_days_avg=28.0, weekly_sailings=3))

    # ──────────────────────────────────────────────
    # 9. SEED DISRUPTION EVENTS
    # ──────────────────────────────────────────────
    events = [
        DisruptionEventNode(
            event_id="EVT-2024-001",
            event_type=EventType.GEOPOLITICAL,
            title="Taiwan Strait Tension Escalation",
            description="Increased military activity in the Taiwan Strait causing shipping rerouting and insurance rate spikes.",
            severity=RiskLevel.HIGH,
            source="gdelt",
            affected_region="APAC",
            started_at=datetime(2024, 8, 1, tzinfo=timezone.utc),
            is_resolved=False,
            impact_score=0.82,
        ),
        DisruptionEventNode(
            event_id="EVT-2024-002",
            event_type=EventType.WEATHER,
            title="Typhoon Ampil — South China Sea",
            description="Category 3 typhoon disrupting port operations at Kaohsiung and affecting semiconductor shipments.",
            severity=RiskLevel.CRITICAL,
            source="noaa",
            affected_region="APAC",
            started_at=datetime(2024, 7, 18, tzinfo=timezone.utc),
            ended_at=datetime(2024, 7, 25, tzinfo=timezone.utc),
            is_resolved=True,
            impact_score=0.91,
        ),
        DisruptionEventNode(
            event_id="EVT-2024-003",
            event_type=EventType.LOGISTICS,
            title="LA/LB Port Congestion — Peak Season",
            description="Container dwell times exceeding 8 days at LA/LB complex during peak import season.",
            severity=RiskLevel.MEDIUM,
            source="portwatch",
            affected_region="NA",
            started_at=datetime(2024, 10, 1, tzinfo=timezone.utc),
            is_resolved=False,
            impact_score=0.55,
        ),
    ]
    for e in events:
        repo.upsert_disruption_event(e)

    # Link events to affected nodes
    repo.link_event_affects("EVT-2024-001", "SUP-001", "Supplier", AffectsRel(impact_type="supply_delay",  estimated_delay_days=21.0, confidence=0.85, detected_at=now()))
    repo.link_event_affects("EVT-2024-001", "FAC-002", "Facility", AffectsRel(impact_type="shutdown",      estimated_delay_days=7.0,  confidence=0.70, detected_at=now()))
    repo.link_event_affects("EVT-2024-001", "TWKHH",   "Port",     AffectsRel(impact_type="reroute",       estimated_delay_days=5.0,  confidence=0.90, detected_at=now()))
    repo.link_event_affects("EVT-2024-002", "TWKHH",   "Port",     AffectsRel(impact_type="shutdown",      estimated_delay_days=7.0,  confidence=0.95, detected_at=now()))
    repo.link_event_affects("EVT-2024-002", "FAC-002", "Facility", AffectsRel(impact_type="supply_delay",  estimated_delay_days=10.0, confidence=0.80, detected_at=now()))
    repo.link_event_affects("EVT-2024-003", "USLAX",   "Port",     AffectsRel(impact_type="cost_increase", estimated_delay_days=4.5,  confidence=0.95, detected_at=now()))
    repo.link_event_affects("EVT-2024-003", "USLGB",   "Port",     AffectsRel(impact_type="cost_increase", estimated_delay_days=4.0,  confidence=0.95, detected_at=now()))

    logger.info("✅ Seed complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    with Neo4jConnection() as conn:
        repo = SupplyChainRepository(conn)
        seed(repo)