"""
graph/queries/repository.py
All Cypher read/write operations for the supply chain graph.
Single point of access — Airflow tasks, the LangGraph agent, and
the Streamlit dashboard all call methods on SupplyChainRepository.

Design decisions:
  - MERGE (not CREATE) for all upserts → idempotent Airflow runs
  - Parameters always passed as dicts, never f-strings → injection-safe
  - lat/lon stored as Neo4j Point for geo queries (not separate floats)
  - Relationships carry properties via MERGE ON MATCH SET / ON CREATE SET
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from graph.connection import Neo4jConnection
from graph.models.nodes import (
    SupplierNode, FacilityNode, PortNode,
    ProductNode, ComponentNode, RouteNode,
    RegionNode, DisruptionEventNode,
)
from graph.models.relationships import (
    RelType, SuppliesRel, RequiresRel,
    ConnectsToRel, AffectsRel, SubSupplierOfRel,
)

logger = logging.getLogger(__name__)


class SupplyChainRepository:

    def __init__(self, conn: Neo4jConnection):
        self.conn = conn

    # ══════════════════════════════════════════════════════════════
    # NODE UPSERTS (MERGE on primary key)
    # ══════════════════════════════════════════════════════════════

    def upsert_region(self, node: RegionNode) -> dict:
        q = """
        MERGE (r:Region {region_id: $region_id})
        ON CREATE SET
            r.name               = $name,
            r.countries          = $countries,
            r.geopolitical_risk  = $geopolitical_risk,
            r.climate_risk       = $climate_risk,
            r.created_at         = datetime()
        ON MATCH SET
            r.geopolitical_risk  = $geopolitical_risk,
            r.climate_risk       = $climate_risk,
            r.updated_at         = datetime()
        RETURN r
        """
        return self.conn.run_write(q, node.model_dump())[0]

    def upsert_supplier(self, node: SupplierNode) -> dict:
        q = """
        MERGE (s:Supplier {supplier_id: $supplier_id})
        ON CREATE SET
            s.name               = $name,
            s.country            = $country,
            s.region_id          = $region_id,
            s.tier               = $tier,
            s.risk_score         = $risk_score,
            s.risk_level         = $risk_level,
            s.annual_revenue_usd = $annual_revenue_usd,
            s.employee_count     = $employee_count,
            s.certifications     = $certifications,
            s.is_single_source   = $is_single_source,
            s.created_at         = datetime()
        ON MATCH SET
            s.risk_score         = $risk_score,
            s.risk_level         = $risk_level,
            s.is_single_source   = $is_single_source,
            s.updated_at         = datetime()
        RETURN s
        """
        data = node.model_dump()
        data["risk_level"] = node.risk_level.value
        return self.conn.run_write(q, data)[0]

    def upsert_facility(self, node: FacilityNode) -> dict:
        q = """
        MERGE (f:Facility {facility_id: $facility_id})
        ON CREATE SET
            f.supplier_id             = $supplier_id,
            f.name                    = $name,
            f.facility_type           = $facility_type,
            f.country                 = $country,
            f.city                    = $city,
            f.location                = point({latitude: $latitude, longitude: $longitude}),
            f.capacity_units_per_day  = $capacity_units_per_day,
            f.utilization_pct         = $utilization_pct,
            f.is_active               = $is_active,
            f.created_at              = datetime()
        ON MATCH SET
            f.utilization_pct  = $utilization_pct,
            f.is_active        = $is_active,
            f.updated_at       = datetime()
        RETURN f
        """
        data = node.model_dump()
        data["facility_type"] = node.facility_type.value
        return self.conn.run_write(q, data)[0]

    def upsert_port(self, node: PortNode) -> dict:
        q = """
        MERGE (p:Port {port_id: $port_id})
        ON CREATE SET
            p.name                   = $name,
            p.country                = $country,
            p.city                   = $city,
            p.port_type              = $port_type,
            p.location               = point({latitude: $latitude, longitude: $longitude}),
            p.throughput_teu_annual  = $throughput_teu_annual,
            p.congestion_index       = $congestion_index,
            p.avg_dwell_days         = $avg_dwell_days,
            p.region_id              = $region_id,
            p.created_at             = datetime()
        ON MATCH SET
            p.congestion_index  = $congestion_index,
            p.avg_dwell_days    = $avg_dwell_days,
            p.updated_at        = datetime()
        RETURN p
        """
        return self.conn.run_write(q, node.model_dump())[0]

    def upsert_product(self, node: ProductNode) -> dict:
        q = """
        MERGE (p:Product {product_id: $product_id})
        ON CREATE SET
            p.name               = $name,
            p.sku                = $sku,
            p.category           = $category,
            p.criticality        = $criticality,
            p.lead_time_days     = $lead_time_days,
            p.safety_stock_days  = $safety_stock_days,
            p.unit_cost_usd      = $unit_cost_usd,
            p.created_at         = datetime()
        ON MATCH SET
            p.lead_time_days    = $lead_time_days,
            p.criticality       = $criticality,
            p.updated_at        = datetime()
        RETURN p
        """
        data = node.model_dump()
        data["criticality"] = node.criticality.value
        return self.conn.run_write(q, data)[0]

    def upsert_component(self, node: ComponentNode) -> dict:
        q = """
        MERGE (c:Component {component_id: $component_id})
        ON CREATE SET
            c.name                = $name,
            c.material_type       = $material_type,
            c.hs_code             = $hs_code,
            c.unit_of_measure     = $unit_of_measure,
            c.is_hazmat           = $is_hazmat,
            c.substitutability    = $substitutability,
            c.created_at          = datetime()
        ON MATCH SET
            c.substitutability  = $substitutability,
            c.updated_at        = datetime()
        RETURN c
        """
        data = node.model_dump()
        data["substitutability"] = node.substitutability.value
        return self.conn.run_write(q, data)[0]

    def upsert_route(self, node: RouteNode) -> dict:
        q = """
        MERGE (r:Route {route_id: $route_id})
        ON CREATE SET
            r.origin_id           = $origin_id,
            r.destination_id      = $destination_id,
            r.transport_mode      = $transport_mode,
            r.distance_km         = $distance_km,
            r.transit_days_avg    = $transit_days_avg,
            r.transit_days_std    = $transit_days_std,
            r.cost_per_unit_usd   = $cost_per_unit_usd,
            r.carrier             = $carrier,
            r.is_active           = $is_active,
            r.created_at          = datetime()
        ON MATCH SET
            r.transit_days_avg  = $transit_days_avg,
            r.is_active         = $is_active,
            r.updated_at        = datetime()
        RETURN r
        """
        data = node.model_dump()
        data["transport_mode"] = node.transport_mode.value
        return self.conn.run_write(q, data)[0]

    def upsert_disruption_event(self, node: DisruptionEventNode) -> dict:
        q = """
        MERGE (e:DisruptionEvent {event_id: $event_id})
        ON CREATE SET
            e.event_type      = $event_type,
            e.title           = $title,
            e.description     = $description,
            e.severity        = $severity,
            e.source          = $source,
            e.source_url      = $source_url,
            e.affected_region = $affected_region,
            e.started_at      = datetime($started_at),
            e.is_resolved     = $is_resolved,
            e.impact_score    = $impact_score,
            e.created_at      = datetime()
        ON MATCH SET
            e.is_resolved    = $is_resolved,
            e.ended_at       = CASE WHEN $ended_at IS NOT NULL THEN datetime($ended_at) ELSE null END,
            e.impact_score   = $impact_score,
            e.updated_at     = datetime()
        RETURN e
        """
        data = node.model_dump()
        data["event_type"] = node.event_type.value
        data["severity"]   = node.severity.value
        data["started_at"] = node.started_at.isoformat()
        data["ended_at"]   = node.ended_at.isoformat() if node.ended_at else None
        return self.conn.run_write(q, data)[0]

    # ══════════════════════════════════════════════════════════════
    # RELATIONSHIP UPSERTS
    # ══════════════════════════════════════════════════════════════

    def link_supplier_to_region(self, supplier_id: str, region_id: str):
        q = """
        MATCH (s:Supplier {supplier_id: $supplier_id})
        MATCH (r:Region   {region_id:   $region_id})
        MERGE (s)-[:LOCATED_IN]->(r)
        """
        self.conn.run_write(q, {"supplier_id": supplier_id, "region_id": region_id})

    def link_facility_to_region(self, facility_id: str, region_id: str):
        q = """
        MATCH (f:Facility {facility_id: $facility_id})
        MATCH (r:Region   {region_id:   $region_id})
        MERGE (f)-[:LOCATED_IN]->(r)
        """
        self.conn.run_write(q, {"facility_id": facility_id, "region_id": region_id})

    def link_facility_to_supplier(self, supplier_id: str, facility_id: str):
        q = """
        MATCH (s:Supplier {supplier_id: $supplier_id})
        MATCH (f:Facility {facility_id: $facility_id})
        MERGE (s)-[:MANUFACTURES_AT]->(f)
        """
        self.conn.run_write(q, {"supplier_id": supplier_id, "facility_id": facility_id})

    def link_supplier_supplies_product(self, supplier_id: str, product_id: str, rel: SuppliesRel):
        q = """
        MATCH (s:Supplier {supplier_id: $supplier_id})
        MATCH (p:Product  {product_id:  $product_id})
        MERGE (s)-[r:SUPPLIES]->(p)
        ON CREATE SET
            r.annual_volume_units   = $annual_volume_units,
            r.is_preferred          = $is_preferred,
            r.share_of_supply_pct   = $share_of_supply_pct,
            r.lead_time_days        = $lead_time_days
        ON MATCH SET
            r.share_of_supply_pct   = $share_of_supply_pct
        """
        params = {"supplier_id": supplier_id, "product_id": product_id, **rel.model_dump()}
        self.conn.run_write(q, params)

    def link_product_requires_component(self, product_id: str, component_id: str, rel: RequiresRel):
        q = """
        MATCH (p:Product   {product_id:   $product_id})
        MATCH (c:Component {component_id: $component_id})
        MERGE (p)-[r:REQUIRES]->(c)
        ON CREATE SET
            r.quantity_per_unit = $quantity_per_unit,
            r.unit_of_measure   = $unit_of_measure,
            r.is_critical       = $is_critical
        ON MATCH SET
            r.is_critical       = $is_critical
        """
        params = {"product_id": product_id, "component_id": component_id, **rel.model_dump()}
        self.conn.run_write(q, params)

    def link_component_sourced_from(self, component_id: str, supplier_id: str):
        q = """
        MATCH (c:Component {component_id: $component_id})
        MATCH (s:Supplier  {supplier_id:  $supplier_id})
        MERGE (c)-[:SOURCED_FROM]->(s)
        """
        self.conn.run_write(q, {"component_id": component_id, "supplier_id": supplier_id})

    def link_facility_ships_via_port(self, facility_id: str, port_id: str):
        q = """
        MATCH (f:Facility {facility_id: $facility_id})
        MATCH (p:Port     {port_id:     $port_id})
        MERGE (f)-[:SHIPS_VIA]->(p)
        """
        self.conn.run_write(q, {"facility_id": facility_id, "port_id": port_id})

    def link_port_to_port(self, origin_port_id: str, dest_port_id: str, rel: ConnectsToRel):
        q = """
        MATCH (o:Port {port_id: $origin_port_id})
        MATCH (d:Port {port_id: $dest_port_id})
        MERGE (o)-[r:CONNECTS_TO]->(d)
        ON CREATE SET
            r.transport_mode    = $transport_mode,
            r.distance_km       = $distance_km,
            r.transit_days_avg  = $transit_days_avg,
            r.weekly_sailings   = $weekly_sailings
        ON MATCH SET
            r.transit_days_avg  = $transit_days_avg
        """
        params = {
            "origin_port_id": origin_port_id,
            "dest_port_id": dest_port_id,
            **rel.model_dump()
        }
        self.conn.run_write(q, params)

    def link_subsupplier(self, sub_id: str, parent_id: str, rel: SubSupplierOfRel):
        q = """
        MATCH (sub:Supplier    {supplier_id: $sub_id})
        MATCH (parent:Supplier {supplier_id: $parent_id})
        MERGE (sub)-[r:SUB_SUPPLIER_OF]->(parent)
        ON CREATE SET
            r.tier_from      = $tier_from,
            r.tier_to        = $tier_to,
            r.component_ids  = $component_ids
        """
        params = {"sub_id": sub_id, "parent_id": parent_id, **rel.model_dump()}
        self.conn.run_write(q, params)

    def link_event_affects(self, event_id: str, target_id: str, target_label: str, rel: AffectsRel):
        """
        target_label must be one of: Supplier, Facility, Port, Route
        target_id is the primary key value (supplier_id, facility_id, port_id, route_id)
        """
        pk_map = {
            "Supplier": "supplier_id",
            "Facility": "facility_id",
            "Port":     "port_id",
            "Route":    "route_id",
        }
        pk = pk_map[target_label]
        q = f"""
        MATCH (e:DisruptionEvent {{event_id: $event_id}})
        MATCH (t:{target_label}  {{{pk}: $target_id}})
        MERGE (e)-[r:AFFECTS]->(t)
        ON CREATE SET
            r.impact_type           = $impact_type,
            r.estimated_delay_days  = $estimated_delay_days,
            r.confidence            = $confidence,
            r.detected_at           = datetime($detected_at)
        ON MATCH SET
            r.confidence            = $confidence
        """
        data = rel.model_dump()
        data["detected_at"] = rel.detected_at.isoformat()
        data["resolved_at"] = rel.resolved_at.isoformat() if rel.resolved_at else None
        params = {"event_id": event_id, "target_id": target_id, **data}
        self.conn.run_write(q, params)

    # ══════════════════════════════════════════════════════════════
    # READ QUERIES (used by Phase 4 LangGraph agent + Phase 5 dashboard)
    # ══════════════════════════════════════════════════════════════

    def get_supplier_by_id(self, supplier_id: str) -> Optional[dict]:
        results = self.conn.run(
            "MATCH (s:Supplier {supplier_id: $supplier_id}) RETURN s",
            {"supplier_id": supplier_id}
        )
        return results[0]["s"] if results else None

    def get_all_active_disruptions(self) -> list[dict]:
        return self.conn.run(
            "MATCH (e:DisruptionEvent {is_resolved: false}) RETURN e ORDER BY e.impact_score DESC"
        )

    def get_affected_suppliers_for_event(self, event_id: str) -> list[dict]:
        q = """
        MATCH (e:DisruptionEvent {event_id: $event_id})-[:AFFECTS]->(s:Supplier)
        RETURN s.supplier_id AS supplier_id, s.name AS name, s.tier AS tier,
               s.risk_level AS risk_level, s.country AS country
        ORDER BY s.tier
        """
        return self.conn.run(q, {"event_id": event_id})

    def get_upstream_suppliers(self, supplier_id: str, max_hops: int = 3) -> list[dict]:
        """
        Traverse SUB_SUPPLIER_OF chain upstream from a given supplier.
        Returns all reachable suppliers up to max_hops tiers deep.
        """
        q = """
        MATCH path = (s:Supplier {supplier_id: $supplier_id})
                     -[:SUB_SUPPLIER_OF*1..$max_hops]->(upstream:Supplier)
        RETURN upstream.supplier_id AS supplier_id,
               upstream.name        AS name,
               upstream.tier        AS tier,
               upstream.country     AS country,
               length(path)         AS hops
        ORDER BY hops, upstream.tier
        """
        return self.conn.run(q, {"supplier_id": supplier_id, "max_hops": max_hops})

    def get_critical_path_for_product(self, product_id: str) -> list[dict]:
        """
        Find all Suppliers (any tier) that feed a given product,
        plus which components they supply and their risk levels.
        """
        q = """
        MATCH (prod:Product {product_id: $product_id})-[:REQUIRES]->(comp:Component)
              <-[:SOURCED_FROM]-(s:Supplier)
        RETURN s.supplier_id  AS supplier_id,
               s.name         AS name,
               s.tier         AS tier,
               s.risk_level   AS risk_level,
               s.is_single_source AS is_single_source,
               collect(comp.name) AS components
        ORDER BY s.tier, s.risk_level DESC
        """
        return self.conn.run(q, {"product_id": product_id})

    def get_high_risk_suppliers(self, min_risk_score: float = 0.7) -> list[dict]:
        q = """
        MATCH (s:Supplier)
        WHERE s.risk_score >= $min_risk_score
        OPTIONAL MATCH (s)-[:SUPPLIES]->(p:Product)
        RETURN s.supplier_id   AS supplier_id,
               s.name          AS name,
               s.country       AS country,
               s.tier          AS tier,
               s.risk_score    AS risk_score,
               s.risk_level    AS risk_level,
               count(p)        AS product_count
        ORDER BY s.risk_score DESC
        """
        return self.conn.run(q, {"min_risk_score": min_risk_score})

    def get_ports_by_congestion(self, min_congestion: float = 0.5) -> list[dict]:
        q = """
        MATCH (p:Port)
        WHERE p.congestion_index >= $min_congestion
        RETURN p.port_id           AS port_id,
               p.name              AS name,
               p.country           AS country,
               p.congestion_index  AS congestion_index,
               p.avg_dwell_days    AS avg_dwell_days
        ORDER BY p.congestion_index DESC
        """
        return self.conn.run(q, {"min_congestion": min_congestion})

    def get_single_source_risk_products(self) -> list[dict]:
        """Products that depend on at least one single-source supplier."""
        q = """
        MATCH (s:Supplier {is_single_source: true})-[:SUPPLIES]->(p:Product)
        RETURN p.product_id   AS product_id,
               p.name         AS name,
               p.criticality  AS criticality,
               collect(s.name) AS single_source_suppliers
        ORDER BY p.criticality DESC
        """
        return self.conn.run(q)

    def find_alternative_components(self, component_id: str) -> list[dict]:
        q = """
        MATCH (c:Component {component_id: $component_id})-[:ALTERNATIVE_FOR]->(alt:Component)
        OPTIONAL MATCH (alt)<-[:SOURCED_FROM]-(s:Supplier)
        RETURN alt.component_id AS component_id,
               alt.name         AS name,
               collect(s.name)  AS suppliers
        """
        return self.conn.run(q, {"component_id": component_id})

    def graph_summary(self) -> dict:
        """Quick health-check: node and relationship counts."""
        q = """
        MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count
        UNION ALL
        MATCH ()-[r]->() RETURN type(r) AS label, count(r) AS count
        """
        return {"counts": self.conn.run(q)}