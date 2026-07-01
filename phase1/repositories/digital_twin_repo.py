"""
Phase 1 — CustomerDigitalTwinRepository

Fixed: replaced **model_dump() + explicit kwargs pattern (causes duplicate
keyword argument errors) with explicit params dicts per upsert method.

Root cause: model_dump() already includes created_at, updated_at, and enum
fields. Passing those same keys again as explicit kwargs caused:
  TypeError: Session.run() got multiple values for keyword argument 'created_at'

Fix: build a clean params dict manually for every s.run() call. No model_dump()
unpacking anywhere — each field is set explicitly, enums serialised via .value,
datetimes serialised via .isoformat().
"""

from __future__ import annotations
from typing import Optional
from neo4j import GraphDatabase, Driver
from datetime import datetime

from phase1.models.domain import (
    Customer, Product, Component, Supplier, Factory,
    Warehouse, Port, Route
)


def _now() -> str:
    return datetime.utcnow().isoformat()


class CustomerDigitalTwinRepository:

    def __init__(self, driver: Driver):
        self._driver = driver

    # ── Customer ──────────────────────────────────────────────────────────────

    def upsert_customer(self, c: Customer) -> None:
        cypher = """
        MERGE (n:Customer {customer_id: $customer_id})
        ON CREATE SET
            n.company_name         = $company_name,
            n.industry             = $industry,
            n.headquarters_country = $headquarters_country,
            n.headquarters_city    = $headquarters_city,
            n.contact_email        = $contact_email,
            n.annual_revenue_usd   = $annual_revenue_usd,
            n.is_active            = $is_active,
            n.created_at           = $created_at
        ON MATCH SET
            n.company_name         = $company_name,
            n.is_active            = $is_active,
            n.updated_at           = $updated_at
        """
        params = {
            "customer_id":           c.customer_id,
            "company_name":          c.company_name,
            "industry":              c.industry.value,
            "headquarters_country":  c.headquarters_country,
            "headquarters_city":     c.headquarters_city,
            "contact_email":         c.contact_email,
            "annual_revenue_usd":    c.annual_revenue_usd,
            "is_active":             c.is_active,
            "created_at":            c.created_at.isoformat(),
            "updated_at":            _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    def get_customer(self, customer_id: str) -> Optional[dict]:
        with self._driver.session() as s:
            result = s.run(
                "MATCH (n:Customer {customer_id: $customer_id}) RETURN n",
                parameters={"customer_id": customer_id}
            )
            rec = result.single()
            return dict(rec["n"]) if rec else None

    # ── Product ───────────────────────────────────────────────────────────────

    def upsert_product(self, p: Product) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Product {product_id: $product_id})
        ON CREATE SET
            n.customer_id        = $customer_id,
            n.name               = $name,
            n.sku                = $sku,
            n.category           = $category,
            n.annual_revenue_usd = $annual_revenue_usd,
            n.risk_level         = $risk_level,
            n.status             = $status,
            n.created_at         = $created_at
        ON MATCH SET
            n.name               = $name,
            n.risk_level         = $risk_level,
            n.status             = $status,
            n.updated_at         = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":       p.customer_id,
            "product_id":        p.product_id,
            "name":              p.name,
            "sku":               p.sku,
            "category":          p.category,
            "annual_revenue_usd": p.annual_revenue_usd,
            "risk_level":        p.risk_level.value,
            "status":            p.status.value,
            "created_at":        p.created_at.isoformat(),
            "updated_at":        _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    def link_product_to_component(
        self, customer_id: str, product_id: str,
        component_id: str, quantity: int = 1
    ) -> None:
        cypher = """
        MATCH (p:Product   {product_id:   $product_id,   customer_id: $customer_id})
        MATCH (c:Component {component_id: $component_id, customer_id: $customer_id})
        MERGE (p)-[r:CONTAINS]->(c)
        ON CREATE SET r.quantity = $quantity
        ON MATCH SET  r.quantity = $quantity
        """
        with self._driver.session() as s:
            s.run(cypher, parameters={
                "customer_id":  customer_id,
                "product_id":   product_id,
                "component_id": component_id,
                "quantity":     quantity,
            })

    # ── Component ─────────────────────────────────────────────────────────────

    def upsert_component(self, c: Component) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Component {component_id: $component_id})
        ON CREATE SET
            n.customer_id            = $customer_id,
            n.name                   = $name,
            n.part_number            = $part_number,
            n.category               = $category,
            n.is_sole_sourced        = $is_sole_sourced,
            n.lead_time_days         = $lead_time_days,
            n.inventory_buffer_days  = $inventory_buffer_days,
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.created_at             = $created_at
        ON MATCH SET
            n.name                   = $name,
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.updated_at             = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":           c.customer_id,
            "component_id":          c.component_id,
            "name":                  c.name,
            "part_number":           c.part_number,
            "category":              c.category,
            "is_sole_sourced":       c.is_sole_sourced,
            "lead_time_days":        c.lead_time_days,
            "inventory_buffer_days": c.inventory_buffer_days,
            "risk_level":            c.risk_level.value,
            "status":                c.status.value,
            "created_at":            c.created_at.isoformat(),
            "updated_at":            _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    # ── Supplier ──────────────────────────────────────────────────────────────

    def upsert_supplier(self, sup: Supplier) -> None:
        
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Supplier {supplier_id: $supplier_id})
        ON CREATE SET
            n.customer_id             = $customer_id,
            n.company_name            = $company_name,
            n.tier                    = $tier,
            n.country                 = $country,
            n.city                    = $city,
            n.contract_value_usd      = $contract_value_usd,
            n.lead_time_days          = $lead_time_days,
            n.on_time_delivery_rate   = $on_time_delivery_rate,
            n.quality_score           = $quality_score,
            n.risk_level              = $risk_level,
            n.is_sole_source          = $is_sole_source,
            n.status                  = $status,
            n.created_at              = $created_at
        ON MATCH SET
            n.company_name            = $company_name,
            n.tier                    = $tier,
            n.risk_level              = $risk_level,
            n.status                  = $status,
            n.updated_at              = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":           sup.customer_id,
            "supplier_id":           sup.supplier_id,
            "company_name":          sup.company_name,
            "tier":                  sup.tier.value,
            "country":               sup.country,
            "city":                  sup.city,
            "contract_value_usd":    sup.contract_value_usd,
            "lead_time_days":        sup.lead_time_days,
            "on_time_delivery_rate": sup.on_time_delivery_rate,
            "quality_score":         sup.quality_score,
            "risk_level":            sup.risk_level.value,
            "is_sole_source":        sup.is_sole_source,
            "status":                sup.status.value,
            "created_at":            sup.created_at.isoformat(),
            "updated_at":            _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

        # Set location separately — only if coordinates were provided.
        # Mirrors the same pattern used by the GlobalEvent writer in Phase 2,
        # so a supplier without lat/lon doesn't break the upsert.
        if sup.latitude is not None and sup.longitude is not None:
            with self._driver.session() as s:
                s.run(
                    """
                    MATCH (n:Supplier {supplier_id: $supplier_id})
                    SET n.location = point({latitude: $latitude, longitude: $longitude})
                    """,
                    parameters={
                        "supplier_id": sup.supplier_id,
                        "latitude":    sup.latitude,
                        "longitude":   sup.longitude,
                    }
                )

    def link_supplier_to_component(
        self, customer_id: str, supplier_id: str,
        component_id: str, annual_volume: Optional[int] = None
    ) -> None:
        cypher = """
        MATCH (s:Supplier  {supplier_id:  $supplier_id,  customer_id: $customer_id})
        MATCH (c:Component {component_id: $component_id, customer_id: $customer_id})
        MERGE (s)-[r:SUPPLIES]->(c)
        ON CREATE SET r.annual_volume = $annual_volume
        ON MATCH SET  r.annual_volume = $annual_volume
        """
        with self._driver.session() as s:
            s.run(cypher, parameters={
                "customer_id":  customer_id,
                "supplier_id":  supplier_id,
                "component_id": component_id,
                "annual_volume": annual_volume,
            })

    # ── Factory ───────────────────────────────────────────────────────────────

    def upsert_factory(self, f: Factory) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MATCH (sup:Supplier  {supplier_id: $supplier_id, customer_id: $customer_id})
        MERGE (n:Factory {factory_id: $factory_id})
        ON CREATE SET
            n.customer_id            = $customer_id,
            n.supplier_id            = $supplier_id,
            n.name                   = $name,
            n.country                = $country,
            n.city                   = $city,
            n.location               = point({latitude: $latitude, longitude: $longitude}),
            n.capacity_utilisation   = $capacity_utilisation,
            n.workforce_size         = $workforce_size,
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.created_at             = $created_at
        ON MATCH SET
            n.name                   = $name,
            n.location               = point({latitude: $latitude, longitude: $longitude}),
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.updated_at             = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        MERGE (sup)-[:OPERATES]->(n)
        """
        params = {
            "customer_id":          f.customer_id,
            "supplier_id":          f.supplier_id,
            "factory_id":           f.factory_id,
            "name":                 f.name,
            "country":              f.country,
            "city":                 f.city,
            "latitude":             f.latitude,
            "longitude":            f.longitude,
            "capacity_utilisation": f.capacity_utilisation,
            "workforce_size":       f.workforce_size,
            "risk_level":           f.risk_level.value,
            "status":               f.status.value,
            "created_at":           f.created_at.isoformat(),
            "updated_at":           _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    def link_factory_produces_component(
        self, customer_id: str, factory_id: str, component_id: str
    ) -> None:
        cypher = """
        MATCH (f:Factory   {factory_id:   $factory_id,   customer_id: $customer_id})
        MATCH (c:Component {component_id: $component_id, customer_id: $customer_id})
        MERGE (f)-[:PRODUCES]->(c)
        """
        with self._driver.session() as s:
            s.run(cypher, parameters={
                "customer_id":  customer_id,
                "factory_id":   factory_id,
                "component_id": component_id,
            })

    # ── Warehouse ─────────────────────────────────────────────────────────────

    def upsert_warehouse(self, w: Warehouse) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Warehouse {warehouse_id: $warehouse_id})
        ON CREATE SET
            n.customer_id           = $customer_id,
            n.name                  = $name,
            n.country               = $country,
            n.city                  = $city,
            n.location              = point({latitude: $latitude, longitude: $longitude}),
            n.type                  = $type,
            n.capacity_sqm          = $capacity_sqm,
            n.inventory_buffer_days = $inventory_buffer_days,
            n.status                = $status,
            n.created_at            = $created_at
        ON MATCH SET
            n.name                  = $name,
            n.location              = point({latitude: $latitude, longitude: $longitude}),
            n.status                = $status,
            n.updated_at            = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":           w.customer_id,
            "warehouse_id":          w.warehouse_id,
            "name":                  w.name,
            "country":               w.country,
            "city":                  w.city,
            "latitude":              w.latitude,
            "longitude":             w.longitude,
            "type":                  w.type,
            "capacity_sqm":          w.capacity_sqm,
            "inventory_buffer_days": w.inventory_buffer_days,
            "status":                w.status.value,
            "created_at":            w.created_at.isoformat(),
            "updated_at":            _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    # ── Port ──────────────────────────────────────────────────────────────────

    def upsert_port(self, p: Port) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Port {port_id: $port_id})
        ON CREATE SET
            n.customer_id           = $customer_id,
            n.name                  = $name,
            n.un_locode             = $un_locode,
            n.country               = $country,
            n.city                  = $city,
            n.location              = point({latitude: $latitude, longitude: $longitude}),
            n.port_type             = $port_type,
            n.annual_throughput_teu = $annual_throughput_teu,
            n.congestion_level      = $congestion_level,
            n.status                = $status,
            n.created_at            = $created_at
        ON MATCH SET
            n.name                  = $name,
            n.congestion_level      = $congestion_level,
            n.status                = $status,
            n.updated_at            = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":          p.customer_id,
            "port_id":              p.port_id,
            "name":                 p.name,
            "un_locode":            p.un_locode,
            "country":              p.country,
            "city":                 p.city,
            "latitude":             p.latitude,
            "longitude":            p.longitude,
            "port_type":            p.port_type,
            "annual_throughput_teu": p.annual_throughput_teu,
            "congestion_level":     p.congestion_level.value,
            "status":               p.status.value,
            "created_at":           p.created_at.isoformat(),
            "updated_at":           _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    def link_factory_ships_via_port(
        self, customer_id: str, factory_id: str, port_id: str
    ) -> None:
        cypher = """
        MATCH (f:Factory {factory_id: $factory_id, customer_id: $customer_id})
        MATCH (p:Port    {port_id:    $port_id,    customer_id: $customer_id})
        MERGE (f)-[:SHIPS_VIA]->(p)
        """
        with self._driver.session() as s:
            s.run(cypher, parameters={
                "customer_id": customer_id,
                "factory_id":  factory_id,
                "port_id":     port_id,
            })

    # ── Route ─────────────────────────────────────────────────────────────────

    def upsert_route(self, r: Route) -> None:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})
        MERGE (n:Route {route_id: $route_id})
        ON CREATE SET
            n.customer_id            = $customer_id,
            n.name                   = $name,
            n.origin_node_id         = $origin_node_id,
            n.origin_node_type       = $origin_node_type,
            n.destination_node_id    = $destination_node_id,
            n.destination_node_type  = $destination_node_type,
            n.transport_mode         = $transport_mode,
            n.transit_time_days      = $transit_time_days,
            n.carrier                = $carrier,
            n.annual_shipment_volume = $annual_shipment_volume,
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.created_at             = $created_at
        ON MATCH SET
            n.transit_time_days      = $transit_time_days,
            n.risk_level             = $risk_level,
            n.status                 = $status,
            n.updated_at             = $updated_at
        MERGE (cust)-[:OWNS]->(n)
        """
        params = {
            "customer_id":            r.customer_id,
            "route_id":               r.route_id,
            "name":                   r.name,
            "origin_node_id":         r.origin_node_id,
            "origin_node_type":       r.origin_node_type,
            "destination_node_id":    r.destination_node_id,
            "destination_node_type":  r.destination_node_type,
            "transport_mode":         r.transport_mode.value,
            "transit_time_days":      r.transit_time_days,
            "carrier":                r.carrier,
            "annual_shipment_volume": r.annual_shipment_volume,
            "risk_level":             r.risk_level.value,
            "status":                 r.status.value,
            "created_at":             r.created_at.isoformat(),
            "updated_at":             _now(),
        }
        with self._driver.session() as s:
            s.run(cypher, parameters=params)

    # ── Cross-tenant safety check ─────────────────────────────────────────────

    def assert_node_belongs_to_customer(
        self, node_label: str, node_id_prop: str,
        node_id_val: str, customer_id: str
    ) -> bool:
        cypher = f"""
        MATCH (n:{node_label} {{{node_id_prop}: $nid, customer_id: $cid}})
        RETURN count(n) AS c
        """
        with self._driver.session() as s:
            result = s.run(cypher, parameters={"nid": node_id_val, "cid": customer_id})
            return result.single()["c"] > 0

    # ── Read helpers ──────────────────────────────────────────────────────────

    def get_full_digital_twin(self, customer_id: str) -> dict:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})-[:OWNS]->(n)
        OPTIONAL MATCH (n)-[r]->(m)
        WHERE m.customer_id = $customer_id
        RETURN labels(n)[0] AS node_type, n,
               type(r) AS rel_type, labels(m)[0] AS target_type, m
        """
        with self._driver.session() as s:
            results = s.run(cypher, parameters={"customer_id": customer_id})
            nodes, rels = {}, []
            for rec in results:
                n = dict(rec["n"])
                pk = (n.get("product_id") or n.get("supplier_id") or
                      n.get("factory_id") or n.get("component_id") or
                      n.get("warehouse_id") or n.get("port_id") or
                      n.get("route_id"))
                nodes[pk] = {**n, "_label": rec["node_type"]}
                if rec["rel_type"] and rec["m"]:
                    rels.append({
                        "type":        rec["rel_type"],
                        "target_type": rec["target_type"],
                        "target":      dict(rec["m"]),
                    })
            return {"nodes": nodes, "relationships": rels}

    def get_suppliers_by_country(self, customer_id: str, country: str) -> list[dict]:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})-[:OWNS]->
              (s:Supplier {country: $country})
        RETURN s
        ORDER BY s.tier, s.risk_level DESC
        """
        with self._driver.session() as s:
            return [dict(r["s"]) for r in s.run(cypher, parameters={
                "customer_id": customer_id,
                "country":     country,
            })]

    def get_products_at_risk_via_supplier(
        self, customer_id: str, supplier_id: str
    ) -> list[dict]:
        cypher = """
        MATCH (cust:Customer {customer_id: $customer_id})-[:OWNS]->
              (s:Supplier {supplier_id: $supplier_id})
        MATCH (s)-[:SUPPLIES]->(c:Component {customer_id: $customer_id})
        MATCH (p:Product {customer_id: $customer_id})-[:CONTAINS]->(c)
        RETURN DISTINCT p, c.name AS via_component, s.company_name AS via_supplier
        ORDER BY p.annual_revenue_usd DESC
        """
        with self._driver.session() as s:
            return [
                {
                    **dict(r["p"]),
                    "via_component": r["via_component"],
                    "via_supplier":  r["via_supplier"],
                }
                for r in s.run(cypher, parameters={
                    "customer_id": customer_id,
                    "supplier_id": supplier_id,
                })
            ]