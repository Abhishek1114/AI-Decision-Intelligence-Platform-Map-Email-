"""
Phase 1 — Seed data for four realistic customers.

Customer 1: Apex Electronics  (electronics — iPhone-like supply chain)
Customer 2: Novara Pharma     (pharmaceutical — API ingredient supply chain)
Customer 3: Volta Motors      (EV automotive — battery/power electronics)
Customer 4: SkyBridge Aerospace (aerospace components — titanium/CFRP/avionics)

Tier 2 suppliers added for all critical/sole-sourced components.
Tier 2 alert logic: only HIGH/CRITICAL severity events trigger customer alerts.
                    LOW/MEDIUM Tier 2 events are logged and monitored silently.

Run: python phase1/seeds/seed_customers.py
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from neo4j import GraphDatabase
from dotenv import load_dotenv
from phase1.models.domain import (
    Customer, Product, Component, Supplier, Factory,
    Warehouse, Port, Route,
    SupplierTier, RiskLevel, NodeStatus, TransportMode, IndustryVertical
)
from phase1.repositories.digital_twin_repo import CustomerDigitalTwinRepository

load_dotenv()


def _link_tier2_feeds_tier1(repo, customer_id: str, tier2_supplier_id: str, tier1_supplier_id: str) -> None:
    """
    Creates (Tier2Supplier)-[:FEEDS]->(Tier1Supplier) relationship.
    This is how Phase 4 will traverse: GlobalEvent → Tier2 → FEEDS → Tier1 → SUPPLIES → Component → Product
    Alert threshold enforced in Phase 4: only fire customer alert if severity = high or critical.
    """
    cypher = """
    MATCH (t2:Supplier {supplier_id: $t2id, customer_id: $cid})
    MATCH (t1:Supplier {supplier_id: $t1id, customer_id: $cid})
    MERGE (t2)-[r:FEEDS]->(t1)
    ON CREATE SET r.created_at = $now
    """
    with repo._driver.session() as s:
        s.run(cypher, parameters={
            "t2id": tier2_supplier_id,
            "t1id": tier1_supplier_id,
            "cid":  customer_id,
            "now":  __import__('datetime').datetime.utcnow().isoformat(),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Customer 1 — Apex Electronics
# ─────────────────────────────────────────────────────────────────────────────

def seed_apex_electronics(repo: CustomerDigitalTwinRepository) -> str:
    """Electronics manufacturer with Taiwan/China/Vietnam supply chain."""
    print("\n── Seeding Apex Electronics ──")
    cid = "cust_apex_001"

    repo.upsert_customer(Customer(
        customer_id=cid, company_name="Apex Electronics Inc.",
        industry=IndustryVertical.ELECTRONICS,
        headquarters_country="United States", headquarters_city="Cupertino",
        contact_email="supplychain@apexelectronics.com",
        annual_revenue_usd=380_000_000_000,
    ))
    print("  Customer: Apex Electronics")

    # ── Products ──────────────────────────────────────────────────────────────
    prod_phone = Product(customer_id=cid, product_id="prod_apex_phone",
        name="Apex X1 Smartphone", sku="AX1-256GB",
        category="smartphone", annual_revenue_usd=200_000_000_000)
    prod_laptop = Product(customer_id=cid, product_id="prod_apex_laptop",
        name="Apex Notebook Pro", sku="ANP-M4-16",
        category="laptop", annual_revenue_usd=80_000_000_000)
    for p in [prod_phone, prod_laptop]:
        repo.upsert_product(p)
        print(f"  Product: {p.name}")

    # ── Components ────────────────────────────────────────────────────────────
    comp_chip = Component(customer_id=cid, component_id="comp_apex_chip",
        name="AX1 Application Processor (5nm)", category="semiconductor",
        is_sole_sourced=True, lead_time_days=90, inventory_buffer_days=14,
        risk_level=RiskLevel.HIGH)
    comp_display = Component(customer_id=cid, component_id="comp_apex_display",
        name="6.7-inch OLED Display", category="display",
        is_sole_sourced=False, lead_time_days=45, inventory_buffer_days=21)
    comp_battery = Component(customer_id=cid, component_id="comp_apex_battery",
        name="Li-ion Battery Pack 4500mAh", category="battery",
        is_sole_sourced=False, lead_time_days=30, inventory_buffer_days=30)
    comp_camera = Component(customer_id=cid, component_id="comp_apex_camera",
        name="48MP Camera Module", category="optics",
        is_sole_sourced=False, lead_time_days=45, inventory_buffer_days=21)
    for c in [comp_chip, comp_display, comp_battery, comp_camera]:
        repo.upsert_component(c)
        print(f"  Component: {c.name}")

    # Product → Component
    repo.link_product_to_component(cid, "prod_apex_phone",  "comp_apex_chip",    1)
    repo.link_product_to_component(cid, "prod_apex_phone",  "comp_apex_display",  1)
    repo.link_product_to_component(cid, "prod_apex_phone",  "comp_apex_battery",  1)
    repo.link_product_to_component(cid, "prod_apex_phone",  "comp_apex_camera",   1)
    repo.link_product_to_component(cid, "prod_apex_laptop", "comp_apex_chip",    1)
    repo.link_product_to_component(cid, "prod_apex_laptop", "comp_apex_display",  1)

    # ── Tier 1 Suppliers ──────────────────────────────────────────────────────
    supp_tsmc = Supplier(customer_id=cid, supplier_id="supp_apex_tsmc",
            company_name="TSMC", tier=SupplierTier.TIER_1,
            country="Taiwan", city="Hsinchu",
            latitude=24.8138, longitude=120.9675,
            contract_value_usd=18_000_000_000,
            lead_time_days=90, on_time_delivery_rate=0.97, quality_score=0.99,
            risk_level=RiskLevel.HIGH, is_sole_source=True)
    supp_samdis = Supplier(customer_id=cid, supplier_id="supp_apex_samdis",
        company_name="Samsung Display", tier=SupplierTier.TIER_1,
        country="South Korea", city="Asan",
        latitude=36.7898, longitude=127.0019,
        contract_value_usd=7_000_000_000,
        lead_time_days=45, on_time_delivery_rate=0.95, quality_score=0.97)
    supp_catl = Supplier(customer_id=cid, supplier_id="supp_apex_catl",
        company_name="CATL", tier=SupplierTier.TIER_1,
        country="China", city="Ningde",
        latitude=26.6617, longitude=119.5269,
        contract_value_usd=3_000_000_000,
        lead_time_days=30, on_time_delivery_rate=0.93, quality_score=0.95)
    supp_sony = Supplier(customer_id=cid, supplier_id="supp_apex_sony",
        company_name="Sony Semiconductor", tier=SupplierTier.TIER_1,
        country="Japan", city="Kumamoto",
        latitude=32.8032, longitude=130.7079,
        contract_value_usd=2_500_000_000,
        lead_time_days=45, on_time_delivery_rate=0.96, quality_score=0.98)
    supp_foxconn = Supplier(customer_id=cid, supplier_id="supp_apex_foxconn",
        company_name="Foxconn", tier=SupplierTier.TIER_1,
        country="China", city="Zhengzhou",
        latitude=34.7472, longitude=113.6249,
        contract_value_usd=25_000_000_000,
        lead_time_days=14, on_time_delivery_rate=0.92, quality_score=0.94)

    for sup in [supp_tsmc, supp_samdis, supp_catl, supp_sony, supp_foxconn]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T1: {sup.company_name}")

    repo.link_supplier_to_component(cid, "supp_apex_tsmc",   "comp_apex_chip",    annual_volume=250_000_000)
    repo.link_supplier_to_component(cid, "supp_apex_samdis", "comp_apex_display", annual_volume=180_000_000)
    repo.link_supplier_to_component(cid, "supp_apex_catl",   "comp_apex_battery", annual_volume=200_000_000)
    repo.link_supplier_to_component(cid, "supp_apex_sony",   "comp_apex_camera",  annual_volume=200_000_000)

    # ── Tier 2 Suppliers ──────────────────────────────────────────────────────
    # ASML → TSMC: only EUV lithography machine maker on earth.
    # If ASML halts, TSMC cannot manufacture at 5nm/3nm. No alternative exists.
    supp_asml = Supplier(customer_id=cid, supplier_id="supp_apex_asml",
        company_name="ASML Holding NV", tier=SupplierTier.TIER_2,
        country="Netherlands", city="Veldhoven",
        latitude=51.4216, longitude=5.4040,
        contract_value_usd=3_200_000_000,
        lead_time_days=365, on_time_delivery_rate=0.96, quality_score=0.99,
        risk_level=RiskLevel.CRITICAL, is_sole_source=True)
    supp_shinetsu = Supplier(customer_id=cid, supplier_id="supp_apex_shinetsu",
        company_name="Shin-Etsu Chemical", tier=SupplierTier.TIER_2,
        country="Japan", city="Niigata",
        latitude=37.9161, longitude=139.0364,
        contract_value_usd=1_800_000_000,
        lead_time_days=60, on_time_delivery_rate=0.97, quality_score=0.99,
        risk_level=RiskLevel.HIGH)

    for sup in [supp_asml, supp_shinetsu]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T2: {sup.company_name} → feeds TSMC")

    # FEEDS relationships: Tier 2 → Tier 1
    _link_tier2_feeds_tier1(repo, cid, "supp_apex_asml",     "supp_apex_tsmc")
    _link_tier2_feeds_tier1(repo, cid, "supp_apex_shinetsu", "supp_apex_tsmc")

    # ── Factories ─────────────────────────────────────────────────────────────
    fact_tsmc = Factory(customer_id=cid, factory_id="fact_apex_tsmc_hsin",
        name="TSMC Fab 18 (N3/N5)", supplier_id="supp_apex_tsmc",
        country="Taiwan", city="Hsinchu",
        latitude=24.8138, longitude=120.9675,
        capacity_utilisation=0.95, workforce_size=12000,
        risk_level=RiskLevel.HIGH)
    fact_fox_zz = Factory(customer_id=cid, factory_id="fact_apex_fox_zz",
        name="Foxconn Zhengzhou Campus", supplier_id="supp_apex_foxconn",
        country="China", city="Zhengzhou",
        latitude=34.7472, longitude=113.6249,
        capacity_utilisation=0.88, workforce_size=200000)
    fact_fox_vn = Factory(customer_id=cid, factory_id="fact_apex_fox_vn",
        name="Foxconn Bắc Giang Vietnam", supplier_id="supp_apex_foxconn",
        country="Vietnam", city="Bac Giang",
        latitude=21.2731, longitude=106.1946,
        capacity_utilisation=0.75, workforce_size=30000)

    for f in [fact_tsmc, fact_fox_zz, fact_fox_vn]:
        repo.upsert_factory(f)
        print(f"  Factory: {f.name}")

    repo.link_factory_produces_component(cid, "fact_apex_tsmc_hsin", "comp_apex_chip")

    # ── Ports ─────────────────────────────────────────────────────────────────
    port_khh = Port(customer_id=cid, port_id="port_apex_khh",
        name="Port of Kaohsiung", un_locode="TWKHH",
        country="Taiwan", city="Kaohsiung",
        latitude=22.6163, longitude=120.2648,
        port_type="sea", annual_throughput_teu=10_000_000)
    port_sha = Port(customer_id=cid, port_id="port_apex_sha",
        name="Port of Shanghai", un_locode="CNSHA",
        country="China", city="Shanghai",
        latitude=31.3697, longitude=121.5966,
        port_type="sea", annual_throughput_teu=47_000_000)
    port_lax = Port(customer_id=cid, port_id="port_apex_lax",
        name="Port of Los Angeles", un_locode="USLAX",
        country="United States", city="Los Angeles",
        latitude=33.7361, longitude=-118.2639,
        port_type="sea", annual_throughput_teu=10_700_000)

    for p in [port_khh, port_sha, port_lax]:
        repo.upsert_port(p)
        print(f"  Port: {p.name}")

    repo.link_factory_ships_via_port(cid, "fact_apex_tsmc_hsin", "port_apex_khh")
    repo.link_factory_ships_via_port(cid, "fact_apex_fox_zz",    "port_apex_sha")
    repo.link_factory_ships_via_port(cid, "fact_apex_fox_vn",    "port_apex_khh")

    # ── Warehouse + Route ─────────────────────────────────────────────────────
    wh = Warehouse(customer_id=cid, warehouse_id="wh_apex_us",
        name="Apex US Distribution Center", country="United States", city="Memphis",
        latitude=35.1495, longitude=-90.0490, type="distribution_center",
        capacity_sqm=85000, inventory_buffer_days=21)
    repo.upsert_warehouse(wh)
    print(f"  Warehouse: {wh.name}")

    route = Route(customer_id=cid, route_id="route_apex_tw_us",
        name="Taiwan → US West Coast (Sea)",
        origin_node_id="port_apex_khh", origin_node_type="Port",
        destination_node_id="port_apex_lax", destination_node_type="Port",
        transport_mode=TransportMode.SEA, transit_time_days=14,
        carrier="Evergreen Marine", annual_shipment_volume=2400)
    repo.upsert_route(route)
    print(f"  Route: {route.name}")

    print("  ✓ Apex Electronics complete (2 Tier 2: ASML, Shin-Etsu → TSMC)")
    return cid


# ─────────────────────────────────────────────────────────────────────────────
# Customer 2 — Novara Pharma
# ─────────────────────────────────────────────────────────────────────────────

def seed_novara_pharma(repo: CustomerDigitalTwinRepository) -> str:
    """Pharmaceutical company with India/Ireland/Germany supply chain."""
    print("\n── Seeding Novara Pharma ──")
    cid = "cust_novara_001"

    repo.upsert_customer(Customer(
        customer_id=cid, company_name="Novara Pharmaceuticals Ltd.",
        industry=IndustryVertical.PHARMA,
        headquarters_country="Ireland", headquarters_city="Dublin",
        contact_email="supplychain@novarapharma.com",
        annual_revenue_usd=24_000_000_000,
    ))
    print("  Customer: Novara Pharma")

    # ── Products ──────────────────────────────────────────────────────────────
    prod_vaccine = Product(customer_id=cid, product_id="prod_nov_vaccine",
        name="NovaShield mRNA Vaccine", sku="NSV-200",
        category="vaccine", annual_revenue_usd=8_000_000_000,
        risk_level=RiskLevel.HIGH)
    prod_antibiotic = Product(customer_id=cid, product_id="prod_nov_antibiotic",
        name="Claravex Antibiotic 500mg", sku="CLV-500",
        category="antibiotic", annual_revenue_usd=3_500_000_000)
    for p in [prod_vaccine, prod_antibiotic]:
        repo.upsert_product(p)
        print(f"  Product: {p.name}")

    # ── Components ────────────────────────────────────────────────────────────
    comp_mrna = Component(customer_id=cid, component_id="comp_nov_mrna",
        name="mRNA Drug Substance", category="api",
        is_sole_sourced=True, lead_time_days=120, inventory_buffer_days=30,
        risk_level=RiskLevel.CRITICAL)
    comp_lipid = Component(customer_id=cid, component_id="comp_nov_lipid",
        name="Lipid Nanoparticle Excipient", category="excipient",
        is_sole_sourced=False, lead_time_days=60, inventory_buffer_days=45)
    comp_amox = Component(customer_id=cid, component_id="comp_nov_amox",
        name="Amoxicillin API Bulk", category="api",
        is_sole_sourced=False, lead_time_days=90, inventory_buffer_days=60)
    for c in [comp_mrna, comp_lipid, comp_amox]:
        repo.upsert_component(c)
        print(f"  Component: {c.name}")

    repo.link_product_to_component(cid, "prod_nov_vaccine",    "comp_nov_mrna",  1)
    repo.link_product_to_component(cid, "prod_nov_vaccine",    "comp_nov_lipid", 1)
    repo.link_product_to_component(cid, "prod_nov_antibiotic", "comp_nov_amox",  1)

    # ── Tier 1 Suppliers ──────────────────────────────────────────────────────
    supp_indapi = Supplier(customer_id=cid, supplier_id="supp_nov_indapi",
        company_name="BioSynth India Ltd.", tier=SupplierTier.TIER_1,
        country="India", city="Hyderabad",
        latitude=17.3850, longitude=78.4867,
        contract_value_usd=1_200_000_000,
        lead_time_days=90, on_time_delivery_rate=0.91, quality_score=0.96,
        risk_level=RiskLevel.MEDIUM)
    supp_delipid = Supplier(customer_id=cid, supplier_id="supp_nov_delipid",
        company_name="LipidChem GmbH", tier=SupplierTier.TIER_1,
        country="Germany", city="Munich",
        latitude=48.1351, longitude=11.5820,
        contract_value_usd=400_000_000,
        lead_time_days=60, on_time_delivery_rate=0.98, quality_score=0.99)

    for sup in [supp_indapi, supp_delipid]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T1: {sup.company_name}")

    repo.link_supplier_to_component(cid, "supp_nov_indapi",  "comp_nov_amox")
    repo.link_supplier_to_component(cid, "supp_nov_delipid", "comp_nov_lipid")

    # ── Tier 2 Suppliers ──────────────────────────────────────────────────────
    # CSPC Pharma → BioSynth India: supplies 6-APA (6-aminopenicillanic acid),
    # the key precursor for Amoxicillin synthesis. ~80% of global 6-APA supply
    # comes from China. An export restriction (as seen in COVID) halts BioSynth.
    supp_cspc = Supplier(customer_id=cid, supplier_id="supp_nov_cspc",
        company_name="CSPC Pharmaceutical Group", tier=SupplierTier.TIER_2,
        country="China", city="Shijiazhuang",
        latitude=38.0428, longitude=114.5149,
        contract_value_usd=180_000_000,
        lead_time_days=60, on_time_delivery_rate=0.90, quality_score=0.94,
        risk_level=RiskLevel.HIGH)
    supp_evonik = Supplier(customer_id=cid, supplier_id="supp_nov_evonik",
        company_name="Evonik Industries AG", tier=SupplierTier.TIER_2,
        country="Germany", city="Essen",
        latitude=51.4556, longitude=7.0116,
        contract_value_usd=220_000_000,
        lead_time_days=45, on_time_delivery_rate=0.96, quality_score=0.98,
        risk_level=RiskLevel.HIGH, is_sole_source=True)

    for sup in [supp_cspc, supp_evonik]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T2: {sup.company_name}")

    # FEEDS relationships
    _link_tier2_feeds_tier1(repo, cid, "supp_nov_cspc",   "supp_nov_indapi")
    _link_tier2_feeds_tier1(repo, cid, "supp_nov_evonik", "supp_nov_delipid")

    # ── Factory ───────────────────────────────────────────────────────────────
    fact_hyd = Factory(customer_id=cid, factory_id="fact_nov_hyd",
        name="BioSynth Hyderabad API Plant", supplier_id="supp_nov_indapi",
        country="India", city="Hyderabad",
        latitude=17.3850, longitude=78.4867,
        capacity_utilisation=0.82, workforce_size=3500,
        risk_level=RiskLevel.MEDIUM)
    repo.upsert_factory(fact_hyd)
    print(f"  Factory: {fact_hyd.name}")
    repo.link_factory_produces_component(cid, "fact_nov_hyd", "comp_nov_amox")

    # ── Ports ─────────────────────────────────────────────────────────────────
    port_maa = Port(customer_id=cid, port_id="port_nov_maa",
        name="Chennai Port", un_locode="INMAA",
        country="India", city="Chennai",
        latitude=13.0827, longitude=80.2707,
        port_type="sea", annual_throughput_teu=2_000_000)
    port_rtm = Port(customer_id=cid, port_id="port_nov_rtm",
        name="Port of Rotterdam", un_locode="NLRTM",
        country="Netherlands", city="Rotterdam",
        latitude=51.9225, longitude=4.4792,
        port_type="sea", annual_throughput_teu=15_000_000)
    for p in [port_maa, port_rtm]:
        repo.upsert_port(p)
        print(f"  Port: {p.name}")

    repo.link_factory_ships_via_port(cid, "fact_nov_hyd", "port_nov_maa")

    wh = Warehouse(customer_id=cid, warehouse_id="wh_nov_dublin",
        name="Novara Dublin Pharma Warehouse", country="Ireland", city="Dublin",
        latitude=53.3498, longitude=-6.2603, type="warehouse",
        capacity_sqm=12000, inventory_buffer_days=45)
    repo.upsert_warehouse(wh)
    print(f"  Warehouse: {wh.name}")

    route = Route(customer_id=cid, route_id="route_nov_in_eu",
        name="India → Rotterdam (Sea)",
        origin_node_id="port_nov_maa", origin_node_type="Port",
        destination_node_id="port_nov_rtm", destination_node_type="Port",
        transport_mode=TransportMode.SEA, transit_time_days=21,
        carrier="Maersk", annual_shipment_volume=480)
    repo.upsert_route(route)
    print(f"  Route: {route.name}")

    print("  ✓ Novara Pharma complete (2 Tier 2: CSPC→BioSynth, Evonik→LipidChem)")
    return cid


# ─────────────────────────────────────────────────────────────────────────────
# Customer 3 — Volta Motors
# ─────────────────────────────────────────────────────────────────────────────

def seed_volta_motors(repo: CustomerDigitalTwinRepository) -> str:
    """EV automotive — battery cells, power electronics, Germany + Mexico assembly."""
    print("\n── Seeding Volta Motors ──")
    cid = "cust_volta_001"

    repo.upsert_customer(Customer(
        customer_id=cid, company_name="Volta Motors GmbH",
        industry=IndustryVertical.AUTOMOTIVE,
        headquarters_country="Germany", headquarters_city="Munich",
        contact_email="supplychain@voltamotors.de",
        annual_revenue_usd=85_000_000_000,
    ))
    print("  Customer: Volta Motors GmbH")

    # ── Products ──────────────────────────────────────────────────────────────
    prod_sedan = Product(customer_id=cid, product_id="prod_volta_sedan",
        name="Volta E5 Electric Sedan", sku="VE5-AWD-800",
        category="electric_vehicle", annual_revenue_usd=42_000_000_000,
        risk_level=RiskLevel.MEDIUM)
    prod_suv = Product(customer_id=cid, product_id="prod_volta_suv",
        name="Volta E7 Electric SUV", sku="VE7-4WD-1000",
        category="electric_vehicle", annual_revenue_usd=38_000_000_000,
        risk_level=RiskLevel.MEDIUM)
    prod_van = Product(customer_id=cid, product_id="prod_volta_van",
        name="Volta Cargo Van EV", sku="VCV-FWD-500",
        category="commercial_ev", annual_revenue_usd=5_000_000_000)
    for p in [prod_sedan, prod_suv, prod_van]:
        repo.upsert_product(p)
        print(f"  Product: {p.name}")

    # ── Components ────────────────────────────────────────────────────────────
    comp_cell = Component(customer_id=cid, component_id="comp_volta_cell",
        name="NCM 811 Lithium Battery Cell", category="battery",
        is_sole_sourced=True, lead_time_days=120, inventory_buffer_days=21,
        risk_level=RiskLevel.CRITICAL)
    comp_bms = Component(customer_id=cid, component_id="comp_volta_bms",
        name="Battery Management System (BMS)", category="power_electronics",
        is_sole_sourced=False, lead_time_days=60, inventory_buffer_days=30,
        risk_level=RiskLevel.HIGH)
    comp_inverter = Component(customer_id=cid, component_id="comp_volta_inverter",
        name="800V SiC Power Inverter", category="power_electronics",
        is_sole_sourced=False, lead_time_days=75, inventory_buffer_days=28,
        risk_level=RiskLevel.HIGH)
    comp_motor = Component(customer_id=cid, component_id="comp_volta_motor",
        name="Permanent Magnet Electric Motor", category="drivetrain",
        is_sole_sourced=False, lead_time_days=45, inventory_buffer_days=35,
        risk_level=RiskLevel.MEDIUM)
    comp_chassis = Component(customer_id=cid, component_id="comp_volta_chassis",
        name="Aluminium EV Platform Chassis", category="structure",
        is_sole_sourced=False, lead_time_days=30, inventory_buffer_days=14,
        risk_level=RiskLevel.LOW)
    for c in [comp_cell, comp_bms, comp_inverter, comp_motor, comp_chassis]:
        repo.upsert_component(c)
        print(f"  Component: {c.name}")

    for prod_id in ["prod_volta_sedan", "prod_volta_suv"]:
        repo.link_product_to_component(cid, prod_id, "comp_volta_cell",    96)
        repo.link_product_to_component(cid, prod_id, "comp_volta_bms",      1)
        repo.link_product_to_component(cid, prod_id, "comp_volta_inverter", 2)
        repo.link_product_to_component(cid, prod_id, "comp_volta_motor",    2)
        repo.link_product_to_component(cid, prod_id, "comp_volta_chassis",  1)
    repo.link_product_to_component(cid, "prod_volta_van", "comp_volta_cell",    64)
    repo.link_product_to_component(cid, "prod_volta_van", "comp_volta_bms",      1)
    repo.link_product_to_component(cid, "prod_volta_van", "comp_volta_inverter", 1)
    repo.link_product_to_component(cid, "prod_volta_van", "comp_volta_motor",    1)

    # ── Tier 1 Suppliers ──────────────────────────────────────────────────────
    supp_sdi = Supplier(customer_id=cid, supplier_id="supp_volta_sdi",
        company_name="Samsung SDI", tier=SupplierTier.TIER_1,
        country="South Korea", city="Cheonan",
        latitude=36.8082, longitude=127.1441,
        contract_value_usd=9_000_000_000,
        lead_time_days=120, on_time_delivery_rate=0.94, quality_score=0.97,
        risk_level=RiskLevel.HIGH, is_sole_source=True)
    supp_infineon = Supplier(customer_id=cid, supplier_id="supp_volta_infineon",
        company_name="Infineon Technologies", tier=SupplierTier.TIER_1,
        country="Germany", city="Neubiberg",
        latitude=48.0667, longitude=11.6667,
        contract_value_usd=2_200_000_000,
        lead_time_days=60, on_time_delivery_rate=0.96, quality_score=0.98,
        risk_level=RiskLevel.MEDIUM)
    supp_bosch = Supplier(customer_id=cid, supplier_id="supp_volta_bosch",
        company_name="Robert Bosch GmbH", tier=SupplierTier.TIER_1,
        country="Germany", city="Stuttgart",
        latitude=48.7758, longitude=9.1829,
        contract_value_usd=3_800_000_000,
        lead_time_days=45, on_time_delivery_rate=0.97, quality_score=0.97,
        risk_level=RiskLevel.LOW)

    for sup in [supp_sdi, supp_infineon, supp_bosch]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T1: {sup.company_name}")

    repo.link_supplier_to_component(cid, "supp_volta_sdi",      "comp_volta_cell",    annual_volume=15_000_000)
    repo.link_supplier_to_component(cid, "supp_volta_infineon", "comp_volta_inverter", annual_volume=500_000)
    repo.link_supplier_to_component(cid, "supp_volta_bosch",    "comp_volta_bms",     annual_volume=800_000)
    repo.link_supplier_to_component(cid, "supp_volta_bosch",    "comp_volta_motor",   annual_volume=800_000)

    # ── Tier 2 Suppliers ──────────────────────────────────────────────────────
    # Ganfeng Lithium → Samsung SDI: raw lithium hydroxide for NCM 811 cells.
    # Controls ~25% of global lithium supply. Chinese export restrictions
    # or mine strikes directly choke Samsung SDI's cell output.
    supp_ganfeng = Supplier(customer_id=cid, supplier_id="supp_volta_ganfeng",
        company_name="Ganfeng Lithium", tier=SupplierTier.TIER_2,
        country="China", city="Xinyu",
        latitude=27.8170, longitude=114.9332,
        contract_value_usd=1_500_000_000,
        lead_time_days=90, on_time_delivery_rate=0.89, quality_score=0.93,
        risk_level=RiskLevel.HIGH)

    repo.upsert_supplier(supp_ganfeng)
    print(f"  Supplier T2: {supp_ganfeng.company_name} → feeds Samsung SDI")
    _link_tier2_feeds_tier1(repo, cid, "supp_volta_ganfeng", "supp_volta_sdi")

    # ── Factories ─────────────────────────────────────────────────────────────
    fact_sdi = Factory(customer_id=cid, factory_id="fact_volta_sdi_kr",
        name="Samsung SDI Cheonan Cell Plant", supplier_id="supp_volta_sdi",
        country="South Korea", city="Cheonan",
        latitude=36.8082, longitude=127.1441,
        capacity_utilisation=0.91, workforce_size=8500, risk_level=RiskLevel.HIGH)
    fact_inf = Factory(customer_id=cid, factory_id="fact_volta_inf_de",
        name="Infineon Dresden SiC Fab", supplier_id="supp_volta_infineon",
        country="Germany", city="Dresden",
        latitude=51.0504, longitude=13.7373,
        capacity_utilisation=0.87, workforce_size=3200, risk_level=RiskLevel.MEDIUM)
    fact_de = Factory(customer_id=cid, factory_id="fact_volta_asm_de",
        name="Volta Munich Assembly Plant", supplier_id="supp_volta_bosch",
        country="Germany", city="Munich",
        latitude=48.1351, longitude=11.5820,
        capacity_utilisation=0.82, workforce_size=12000, risk_level=RiskLevel.LOW)
    fact_mx = Factory(customer_id=cid, factory_id="fact_volta_asm_mx",
        name="Volta Monterrey Assembly Plant", supplier_id="supp_volta_bosch",
        country="Mexico", city="Monterrey",
        latitude=25.6866, longitude=-100.3161,
        capacity_utilisation=0.74, workforce_size=6500, risk_level=RiskLevel.MEDIUM)

    for f in [fact_sdi, fact_inf, fact_de, fact_mx]:
        repo.upsert_factory(f)
        print(f"  Factory: {f.name}")

    repo.link_factory_produces_component(cid, "fact_volta_sdi_kr", "comp_volta_cell")
    repo.link_factory_produces_component(cid, "fact_volta_inf_de", "comp_volta_inverter")

    # ── Ports ─────────────────────────────────────────────────────────────────
    port_pus = Port(customer_id=cid, port_id="port_volta_pus",
        name="Port of Busan", un_locode="KRPUS",
        country="South Korea", city="Busan",
        latitude=35.1796, longitude=129.0756,
        port_type="sea", annual_throughput_teu=22_000_000)
    port_ham = Port(customer_id=cid, port_id="port_volta_ham",
        name="Port of Hamburg", un_locode="DEHAM",
        country="Germany", city="Hamburg",
        latitude=53.5753, longitude=9.9882,
        port_type="sea", annual_throughput_teu=8_700_000)
    port_ver = Port(customer_id=cid, port_id="port_volta_ver",
        name="Port of Veracruz", un_locode="MXVER",
        country="Mexico", city="Veracruz",
        latitude=19.2000, longitude=-96.1333,
        port_type="sea", annual_throughput_teu=1_200_000)
    for p in [port_pus, port_ham, port_ver]:
        repo.upsert_port(p)
        print(f"  Port: {p.name}")

    repo.link_factory_ships_via_port(cid, "fact_volta_sdi_kr", "port_volta_pus")
    repo.link_factory_ships_via_port(cid, "fact_volta_asm_de", "port_volta_ham")
    repo.link_factory_ships_via_port(cid, "fact_volta_asm_mx", "port_volta_ver")

    wh_de = Warehouse(customer_id=cid, warehouse_id="wh_volta_de",
        name="Volta Munich Parts Warehouse", country="Germany", city="Munich",
        latitude=48.1500, longitude=11.6000, type="warehouse",
        capacity_sqm=45000, inventory_buffer_days=28)
    wh_mx = Warehouse(customer_id=cid, warehouse_id="wh_volta_mx",
        name="Volta Monterrey Parts Warehouse", country="Mexico", city="Monterrey",
        latitude=25.7000, longitude=-100.3000, type="warehouse",
        capacity_sqm=22000, inventory_buffer_days=21)
    for w in [wh_de, wh_mx]:
        repo.upsert_warehouse(w)
        print(f"  Warehouse: {w.name}")

    route_kr_de = Route(customer_id=cid, route_id="route_volta_kr_de",
        name="South Korea → Hamburg (Sea)",
        origin_node_id="port_volta_pus", origin_node_type="Port",
        destination_node_id="port_volta_ham", destination_node_type="Port",
        transport_mode=TransportMode.SEA, transit_time_days=26,
        carrier="HMM", annual_shipment_volume=1800, risk_level=RiskLevel.MEDIUM)
    route_air = Route(customer_id=cid, route_id="route_volta_de_mx_air",
        name="Munich → Monterrey (Air — emergency)",
        origin_node_id="port_volta_ham", origin_node_type="Port",
        destination_node_id="port_volta_ver", destination_node_type="Port",
        transport_mode=TransportMode.AIR, transit_time_days=2,
        carrier="Lufthansa Cargo", annual_shipment_volume=60)
    for r in [route_kr_de, route_air]:
        repo.upsert_route(r)
        print(f"  Route: {r.name}")

    print("  ✓ Volta Motors complete (1 Tier 2: Ganfeng Lithium → Samsung SDI)")
    return cid


# ─────────────────────────────────────────────────────────────────────────────
# Customer 4 — SkyBridge Aerospace
# ─────────────────────────────────────────────────────────────────────────────

def seed_skybridge_aerospace(repo: CustomerDigitalTwinRepository) -> str:
    """Aerospace — titanium forgings, CFRP, avionics, Seattle assembly."""
    print("\n── Seeding SkyBridge Aerospace ──")
    cid = "cust_skybridge_001"

    repo.upsert_customer(Customer(
        customer_id=cid, company_name="SkyBridge Aerospace Inc.",
        industry=IndustryVertical.AEROSPACE,
        headquarters_country="United States", headquarters_city="Seattle",
        contact_email="supplychain@skybridgeaero.com",
        annual_revenue_usd=18_000_000_000,
    ))
    print("  Customer: SkyBridge Aerospace Inc.")

    # ── Products ──────────────────────────────────────────────────────────────
    prod_wing = Product(customer_id=cid, product_id="prod_sky_wing",
        name="737-class Wing Assembly", sku="SKY-WING-737",
        category="airframe_assembly", annual_revenue_usd=9_000_000_000,
        risk_level=RiskLevel.HIGH)
    prod_nacelle = Product(customer_id=cid, product_id="prod_sky_nacelle",
        name="CFM56 Engine Nacelle", sku="SKY-NAC-CFM56",
        category="propulsion_assembly", annual_revenue_usd=5_500_000_000,
        risk_level=RiskLevel.HIGH)
    prod_fuselage = Product(customer_id=cid, product_id="prod_sky_fuselage",
        name="Composite Fuselage Section", sku="SKY-FUS-SEC3",
        category="airframe_assembly", annual_revenue_usd=3_500_000_000,
        risk_level=RiskLevel.MEDIUM)
    for p in [prod_wing, prod_nacelle, prod_fuselage]:
        repo.upsert_product(p)
        print(f"  Product: {p.name}")

    # ── Components ────────────────────────────────────────────────────────────
    comp_titanium = Component(customer_id=cid, component_id="comp_sky_titanium",
        name="Grade 5 Titanium Forgings", category="raw_material",
        is_sole_sourced=False, lead_time_days=180, inventory_buffer_days=90,
        risk_level=RiskLevel.HIGH)
    comp_cfrp = Component(customer_id=cid, component_id="comp_sky_cfrp",
        name="T800 Carbon Fibre Reinforced Polymer", category="composite",
        is_sole_sourced=True, lead_time_days=150, inventory_buffer_days=60,
        risk_level=RiskLevel.CRITICAL)
    comp_avionics = Component(customer_id=cid, component_id="comp_sky_avionics",
        name="Flight Control Avionics Unit (DO-178C)", category="avionics",
        is_sole_sourced=True, lead_time_days=210, inventory_buffer_days=45,
        risk_level=RiskLevel.CRITICAL)
    comp_hydraulics = Component(customer_id=cid, component_id="comp_sky_hydraulics",
        name="Primary Flight Hydraulic Actuator", category="hydraulics",
        is_sole_sourced=False, lead_time_days=120, inventory_buffer_days=30,
        risk_level=RiskLevel.HIGH)
    comp_fasteners = Component(customer_id=cid, component_id="comp_sky_fasteners",
        name="Aerospace Grade Titanium Fasteners", category="hardware",
        is_sole_sourced=False, lead_time_days=30, inventory_buffer_days=60,
        risk_level=RiskLevel.LOW)
    for c in [comp_titanium, comp_cfrp, comp_avionics, comp_hydraulics, comp_fasteners]:
        repo.upsert_component(c)
        print(f"  Component: {c.name}")

    repo.link_product_to_component(cid, "prod_sky_wing",     "comp_sky_titanium",   1)
    repo.link_product_to_component(cid, "prod_sky_wing",     "comp_sky_cfrp",       1)
    repo.link_product_to_component(cid, "prod_sky_wing",     "comp_sky_fasteners", 4800)
    repo.link_product_to_component(cid, "prod_sky_nacelle",  "comp_sky_titanium",   1)
    repo.link_product_to_component(cid, "prod_sky_nacelle",  "comp_sky_avionics",   1)
    repo.link_product_to_component(cid, "prod_sky_nacelle",  "comp_sky_hydraulics", 3)
    repo.link_product_to_component(cid, "prod_sky_fuselage", "comp_sky_cfrp",       1)
    repo.link_product_to_component(cid, "prod_sky_fuselage", "comp_sky_fasteners", 8200)

    # ── Tier 1 Suppliers ──────────────────────────────────────────────────────
    supp_kobe = Supplier(customer_id=cid, supplier_id="supp_sky_kobe",
        company_name="Kobe Steel (KOBELCO)", tier=SupplierTier.TIER_1,
        country="Japan", city="Kobe",
        latitude=34.6913, longitude=135.1830,
        contract_value_usd=1_800_000_000,
        lead_time_days=180, on_time_delivery_rate=0.92, quality_score=0.99,
        risk_level=RiskLevel.HIGH)
    supp_toray = Supplier(customer_id=cid, supplier_id="supp_sky_toray",
        company_name="Toray Industries", tier=SupplierTier.TIER_1,
        country="Japan", city="Tokyo",
        latitude=35.6762, longitude=139.6503,
        contract_value_usd=2_400_000_000,
        lead_time_days=150, on_time_delivery_rate=0.95, quality_score=0.99,
        risk_level=RiskLevel.CRITICAL, is_sole_source=True)
    supp_thales = Supplier(customer_id=cid, supplier_id="supp_sky_thales",
        company_name="Thales Avionics", tier=SupplierTier.TIER_1,
        country="France", city="Bordeaux",
        latitude=44.8378, longitude=-0.5792,
        contract_value_usd=1_600_000_000,
        lead_time_days=210, on_time_delivery_rate=0.91, quality_score=0.99,
        risk_level=RiskLevel.CRITICAL, is_sole_source=True)
    supp_parker = Supplier(customer_id=cid, supplier_id="supp_sky_parker",
        company_name="Parker Hannifin", tier=SupplierTier.TIER_1,
        country="United States", city="Cleveland",
        latitude=41.4993, longitude=-81.6944,
        contract_value_usd=900_000_000,
        lead_time_days=120, on_time_delivery_rate=0.94, quality_score=0.97,
        risk_level=RiskLevel.MEDIUM)

    for sup in [supp_kobe, supp_toray, supp_thales, supp_parker]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T1: {sup.company_name}")

    repo.link_supplier_to_component(cid, "supp_sky_kobe",   "comp_sky_titanium",   annual_volume=1200)
    repo.link_supplier_to_component(cid, "supp_sky_toray",  "comp_sky_cfrp",       annual_volume=850)
    repo.link_supplier_to_component(cid, "supp_sky_thales", "comp_sky_avionics",   annual_volume=400)
    repo.link_supplier_to_component(cid, "supp_sky_parker", "comp_sky_hydraulics", annual_volume=3200)
    repo.link_supplier_to_component(cid, "supp_sky_kobe",   "comp_sky_fasteners",  annual_volume=12_000_000)

    # ── Tier 2 Suppliers ──────────────────────────────────────────────────────
    # UKTMP → Kobe Steel: raw titanium sponge from Kazakhstan.
    # Kobe Steel cannot forge without it. Geopolitically sensitive region.
    supp_uktmp = Supplier(customer_id=cid, supplier_id="supp_sky_uktmp",
        company_name="UKTMP (Ust-Kamenogorsk Titanium)", tier=SupplierTier.TIER_2,
        country="Kazakhstan", city="Ust-Kamenogorsk",
        latitude=49.9483, longitude=82.6275,
        contract_value_usd=400_000_000,
        lead_time_days=120, on_time_delivery_rate=0.88, quality_score=0.95,
        risk_level=RiskLevel.HIGH)
    supp_solvay = Supplier(customer_id=cid, supplier_id="supp_sky_solvay",
        company_name="Solvay SA", tier=SupplierTier.TIER_2,
        country="Belgium", city="Brussels",
        latitude=50.8503, longitude=4.3517,
        contract_value_usd=620_000_000,
        lead_time_days=90, on_time_delivery_rate=0.94, quality_score=0.97,
        risk_level=RiskLevel.CRITICAL, is_sole_source=True)
    supp_teledyne = Supplier(customer_id=cid, supplier_id="supp_sky_teledyne",
        company_name="Teledyne Technologies", tier=SupplierTier.TIER_2,
        country="United States", city="Thousand Oaks",
        latitude=34.1808, longitude=-118.8740,
        contract_value_usd=310_000_000,
        lead_time_days=180, on_time_delivery_rate=0.93, quality_score=0.99,
        risk_level=RiskLevel.CRITICAL, is_sole_source=True)

    for sup in [supp_uktmp, supp_solvay, supp_teledyne]:
        repo.upsert_supplier(sup)
        print(f"  Supplier T2: {sup.company_name}")

    # FEEDS relationships
    _link_tier2_feeds_tier1(repo, cid, "supp_sky_uktmp",    "supp_sky_kobe")
    _link_tier2_feeds_tier1(repo, cid, "supp_sky_solvay",   "supp_sky_toray")
    _link_tier2_feeds_tier1(repo, cid, "supp_sky_teledyne", "supp_sky_thales")

    # ── Factories ─────────────────────────────────────────────────────────────
    fact_kobe = Factory(customer_id=cid, factory_id="fact_sky_kobe_jp",
        name="KOBELCO Kobe Titanium Forge", supplier_id="supp_sky_kobe",
        country="Japan", city="Kobe",
        latitude=34.6913, longitude=135.1830,
        capacity_utilisation=0.88, workforce_size=4200, risk_level=RiskLevel.HIGH)
    fact_toray = Factory(customer_id=cid, factory_id="fact_sky_toray_jp",
        name="Toray Ehime CFRP Plant", supplier_id="supp_sky_toray",
        country="Japan", city="Ehime",
        latitude=33.8416, longitude=132.7657,
        capacity_utilisation=0.93, workforce_size=2800, risk_level=RiskLevel.CRITICAL)
    fact_thales = Factory(customer_id=cid, factory_id="fact_sky_thales_fr",
        name="Thales Avionics Bordeaux Plant", supplier_id="supp_sky_thales",
        country="France", city="Bordeaux",
        latitude=44.8378, longitude=-0.5792,
        capacity_utilisation=0.79, workforce_size=1800, risk_level=RiskLevel.HIGH)
    fact_seattle = Factory(customer_id=cid, factory_id="fact_sky_asm_us",
        name="SkyBridge Everett Assembly Center", supplier_id="supp_sky_parker",
        country="United States", city="Everett",
        latitude=47.9790, longitude=-122.2021,
        capacity_utilisation=0.76, workforce_size=9500, risk_level=RiskLevel.LOW)

    for f in [fact_kobe, fact_toray, fact_thales, fact_seattle]:
        repo.upsert_factory(f)
        print(f"  Factory: {f.name}")

    repo.link_factory_produces_component(cid, "fact_sky_kobe_jp",   "comp_sky_titanium")
    repo.link_factory_produces_component(cid, "fact_sky_toray_jp",  "comp_sky_cfrp")
    repo.link_factory_produces_component(cid, "fact_sky_thales_fr", "comp_sky_avionics")

    # ── Ports ─────────────────────────────────────────────────────────────────
    port_kobe = Port(customer_id=cid, port_id="port_sky_kobe",
        name="Port of Kobe", un_locode="JPUKB",
        country="Japan", city="Kobe",
        latitude=34.6778, longitude=135.1978,
        port_type="sea", annual_throughput_teu=2_800_000)
    port_sea = Port(customer_id=cid, port_id="port_sky_sea",
        name="Port of Seattle", un_locode="USSEA",
        country="United States", city="Seattle",
        latitude=47.6062, longitude=-122.3321,
        port_type="sea", annual_throughput_teu=3_900_000)
    port_bdx = Port(customer_id=cid, port_id="port_sky_bdx",
        name="Port of Bordeaux", un_locode="FRBOD",
        country="France", city="Bordeaux",
        latitude=44.8637, longitude=-0.5573,
        port_type="sea", annual_throughput_teu=280_000)
    for p in [port_kobe, port_sea, port_bdx]:
        repo.upsert_port(p)
        print(f"  Port: {p.name}")

    repo.link_factory_ships_via_port(cid, "fact_sky_kobe_jp",   "port_sky_kobe")
    repo.link_factory_ships_via_port(cid, "fact_sky_toray_jp",  "port_sky_kobe")
    repo.link_factory_ships_via_port(cid, "fact_sky_thales_fr", "port_sky_bdx")
    repo.link_factory_ships_via_port(cid, "fact_sky_asm_us",    "port_sky_sea")

    wh_everett = Warehouse(customer_id=cid, warehouse_id="wh_sky_everett",
        name="SkyBridge Everett Parts Bonded Store",
        country="United States", city="Everett",
        latitude=47.9700, longitude=-122.1950, type="warehouse",
        capacity_sqm=28000, inventory_buffer_days=90)
    wh_toulouse = Warehouse(customer_id=cid, warehouse_id="wh_sky_toulouse",
        name="SkyBridge Toulouse European Buffer",
        country="France", city="Toulouse",
        latitude=43.6047, longitude=1.4442, type="warehouse",
        capacity_sqm=8000, inventory_buffer_days=60)
    for w in [wh_everett, wh_toulouse]:
        repo.upsert_warehouse(w)
        print(f"  Warehouse: {w.name}")

    route_jp_us = Route(customer_id=cid, route_id="route_sky_jp_us",
        name="Japan → Seattle (Sea — primary)",
        origin_node_id="port_sky_kobe", origin_node_type="Port",
        destination_node_id="port_sky_sea", destination_node_type="Port",
        transport_mode=TransportMode.SEA, transit_time_days=12,
        carrier="Nippon Yusen (NYK)", annual_shipment_volume=320,
        risk_level=RiskLevel.MEDIUM)
    route_fr_air = Route(customer_id=cid, route_id="route_sky_fr_us_air",
        name="Bordeaux → Seattle (Air — avionics)",
        origin_node_id="port_sky_bdx", origin_node_type="Port",
        destination_node_id="port_sky_sea", destination_node_type="Port",
        transport_mode=TransportMode.AIR, transit_time_days=1,
        carrier="Air France Cargo", annual_shipment_volume=180)
    route_jp_air = Route(customer_id=cid, route_id="route_sky_jp_us_air",
        name="Japan → Seattle (Air — emergency CFRP)",
        origin_node_id="port_sky_kobe", origin_node_type="Port",
        destination_node_id="port_sky_sea", destination_node_type="Port",
        transport_mode=TransportMode.AIR, transit_time_days=1,
        carrier="Japan Airlines Cargo", annual_shipment_volume=24)
    for r in [route_jp_us, route_fr_air, route_jp_air]:
        repo.upsert_route(r)
        print(f"  Route: {r.name}")

    print("  ✓ SkyBridge Aerospace complete (3 Tier 2: UKTMP→Kobe, Solvay→Toray, Teledyne→Thales)")
    return cid


# ─────────────────────────────────────────────────────────────────────────────
# main()
# ─────────────────────────────────────────────────────────────────────────────

def main():
    uri      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user     = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "supply_chain_secret")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    repo   = CustomerDigitalTwinRepository(driver)

    seed_apex_electronics(repo)
    seed_novara_pharma(repo)
    seed_volta_motors(repo)
    seed_skybridge_aerospace(repo)

    print("\n" + "="*60)
    print("All 4 customer digital twins loaded.")
    print("Tier 2 coverage summary:")
    print("  Apex Electronics  → ASML + Shin-Etsu (both feed TSMC)")
    print("  Novara Pharma     → CSPC + Evonik (feed BioSynth + LipidChem)")
    print("  Volta Motors      → Ganfeng Lithium (feeds Samsung SDI)")
    print("  SkyBridge         → UKTMP + Solvay + Teledyne (feed Kobe/Toray/Thales)")
    print("="*60)
    print("\nVerify Tier 2 FEEDS chain in Neo4j Browser:")
    print("  MATCH (t2:Supplier {tier:'tier_2'})-[:FEEDS]->(t1:Supplier)")
    print("  RETURN t2.company_name AS tier2, t1.company_name AS tier1,")
    print("         t2.customer_id AS customer ORDER BY t2.customer_id")
    driver.close()


if __name__ == "__main__":
    main()