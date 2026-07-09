"""
Phase 7 — Map data query. Pulls every geo-located node for a customer
(Supplier, Factory, Port — all carry lat/lon per domain.py) plus active
high/critical assessments, so the map can distinguish "normal supply chain
node" from "node currently under an active alert."
"""

FETCH_NODES_QUERY = """
MATCH (c:Customer {customer_id: $customer_id})-[:OWNS]->(s:Supplier)
WHERE s.location IS NOT NULL
RETURN 'Supplier' AS node_type, s.supplier_id AS node_id, s.company_name AS name,
       s.tier AS tier, s.country AS country,
       s.location.latitude AS latitude, s.location.longitude AS longitude
UNION
MATCH (c:Customer {customer_id: $customer_id})-[:OWNS]->(f:Factory)
WHERE f.location IS NOT NULL
RETURN 'Factory' AS node_type, f.factory_id AS node_id, f.name AS name,
       NULL AS tier, f.country AS country,
       f.location.latitude AS latitude, f.location.longitude AS longitude
UNION
MATCH (c:Customer {customer_id: $customer_id})-[:OWNS]->(p:Port)
WHERE p.location IS NOT NULL
RETURN 'Port' AS node_type, p.port_id AS node_id, p.name AS name,
       NULL AS tier, p.country AS country,
       p.location.latitude AS latitude, p.location.longitude AS longitude
"""

FETCH_ACTIVE_ALERT_LOCATIONS_QUERY = """
MATCH (a:AgentAssessment {customer_id: $customer_id})-[:FOR_CUSTOMER]->(:Customer)
WHERE a.severity IN ['high', 'critical']
MATCH (s:Supplier {supplier_id: a.supplier_id, customer_id: $customer_id})
WHERE s.location IS NOT NULL
RETURN s.supplier_id AS supplier_id, s.company_name AS name,
       s.location.latitude AS latitude, s.location.longitude AS longitude,
       a.severity AS severity, a.assessment_id AS assessment_id,
       a.created_at AS created_at
"""



def fetch_map_nodes(session, customer_id: str) -> list[dict]:
    records = session.run(FETCH_NODES_QUERY, parameters={"customer_id": customer_id})
    return [dict(r) for r in records if r["latitude"] is not None and r["longitude"] is not None]


def fetch_active_alert_locations(session, customer_id: str) -> list[dict]:
    records = session.run(FETCH_ACTIVE_ALERT_LOCATIONS_QUERY, parameters={"customer_id": customer_id})
    return [dict(r) for r in records if r["latitude"] is not None and r["longitude"] is not None]