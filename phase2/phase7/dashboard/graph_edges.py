"""
Edges for the supply chain map. Covers every confirmed relationship type:
  Supplier -[:FEEDS]-> Supplier        (tier-2 → tier-1)
  Supplier -[:OPERATES]-> Factory
  Factory  -[:SHIPS_VIA]-> Port
  Port     -[:DELIVERS_TO]-> Warehouse
  Warehouse -[:SUPPLIES]-> Customer    (last-mile into HQ)
"""

FETCH_FEEDS_EDGES_QUERY = """
MATCH (t2:Supplier {customer_id: $customer_id})-[:FEEDS]->(t1:Supplier {customer_id: $customer_id})
WHERE t2.location IS NOT NULL AND t1.location IS NOT NULL
RETURN t2.supplier_id AS src_id, t2.company_name AS src_name,
       t2.location.latitude AS src_lat, t2.location.longitude AS src_lon,
       t1.supplier_id AS dst_id, t1.company_name AS dst_name,
       t1.location.latitude AS dst_lat, t1.location.longitude AS dst_lon,
       'feeds' AS edge_type
"""

FETCH_OPERATES_EDGES_QUERY = """
MATCH (s:Supplier {customer_id: $customer_id})-[:OPERATES]->(f:Factory {customer_id: $customer_id})
WHERE s.location IS NOT NULL AND f.location IS NOT NULL
RETURN s.supplier_id AS src_id, s.company_name AS src_name,
       s.location.latitude AS src_lat, s.location.longitude AS src_lon,
       f.factory_id AS dst_id, f.name AS dst_name,
       f.location.latitude AS dst_lat, f.location.longitude AS dst_lon,
       'operates' AS edge_type
"""

FETCH_SHIPS_VIA_EDGES_QUERY = """
MATCH (f:Factory {customer_id: $customer_id})-[:SHIPS_VIA]->(p:Port {customer_id: $customer_id})
WHERE f.location IS NOT NULL AND p.location IS NOT NULL
RETURN f.factory_id AS src_id, f.name AS src_name,
       f.location.latitude AS src_lat, f.location.longitude AS src_lon,
       p.port_id AS dst_id, p.name AS dst_name,
       p.location.latitude AS dst_lat, p.location.longitude AS dst_lon,
       'ships_via' AS edge_type
"""


FETCH_SUPPLIER_FACTORY_EDGES_QUERY = """
MATCH (s:Supplier {customer_id: $customer_id}), (f:Factory {customer_id: $customer_id})
WHERE f.supplier_id = s.supplier_id AND s.location IS NOT NULL
RETURN s.supplier_id AS src_id, s.company_name AS src_name,
       s.location.latitude AS src_lat, s.location.longitude AS src_lon,
       f.factory_id AS dst_id, f.name AS dst_name,
       f.latitude AS dst_lat, f.longitude AS dst_lon
"""

FETCH_DELIVERS_TO_EDGES_QUERY = """
MATCH (p:Port {customer_id: $customer_id})-[:DELIVERS_TO]->(w:Warehouse {customer_id: $customer_id})
WHERE p.location IS NOT NULL AND w.location IS NOT NULL
RETURN p.port_id AS src_id, p.name AS src_name,
       p.location.latitude AS src_lat, p.location.longitude AS src_lon,
       w.warehouse_id AS dst_id, w.name AS dst_name,
       w.location.latitude AS dst_lat, w.location.longitude AS dst_lon,
       'delivers_to' AS edge_type
"""

FETCH_WAREHOUSE_TO_CUSTOMER_EDGES_QUERY = """
MATCH (w:Warehouse {customer_id: $customer_id})-[:SUPPLIES]->(c:Customer {customer_id: $customer_id})
WHERE w.location IS NOT NULL AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL
RETURN w.warehouse_id AS src_id, w.name AS src_name,
       w.location.latitude AS src_lat, w.location.longitude AS src_lon,
       c.customer_id AS dst_id, c.company_name AS dst_name,
       c.latitude AS dst_lat, c.longitude AS dst_lon,
       'supplies_customer' AS edge_type
"""

FETCH_ROUTE_EDGES_QUERY = """
MATCH (r:Route {customer_id: $customer_id})
OPTIONAL MATCH (op:Port {customer_id: $customer_id, port_id: r.origin_node_id})
OPTIONAL MATCH (of:Factory {customer_id: $customer_id, factory_id: r.origin_node_id})
OPTIONAL MATCH (ow:Warehouse {customer_id: $customer_id, warehouse_id: r.origin_node_id})
WITH r, coalesce(op, of, ow) AS origin
OPTIONAL MATCH (dp:Port {customer_id: $customer_id, port_id: r.destination_node_id})
OPTIONAL MATCH (df:Factory {customer_id: $customer_id, factory_id: r.destination_node_id})
OPTIONAL MATCH (dw:Warehouse {customer_id: $customer_id, warehouse_id: r.destination_node_id})
WITH r, origin, coalesce(dp, df, dw) AS destination
WHERE origin IS NOT NULL AND destination IS NOT NULL
  AND origin.location IS NOT NULL AND destination.location IS NOT NULL
RETURN coalesce(origin.port_id, origin.factory_id, origin.warehouse_id) AS src_id,
       coalesce(origin.name) AS src_name,
       origin.location.latitude AS src_lat, origin.location.longitude AS src_lon,
       coalesce(destination.port_id, destination.factory_id, destination.warehouse_id) AS dst_id,
       coalesce(destination.name) AS dst_name,
       destination.location.latitude AS dst_lat, destination.location.longitude AS dst_lon,
       'route' AS edge_type
"""

def fetch_edges(session, customer_id: str) -> list[dict]:
    edges = []
    for query in (
        FETCH_FEEDS_EDGES_QUERY,
        FETCH_OPERATES_EDGES_QUERY,
        FETCH_SHIPS_VIA_EDGES_QUERY,
        FETCH_ROUTE_EDGES_QUERY,          # NEW — closes Port→Port / Port→Factory legs
        FETCH_DELIVERS_TO_EDGES_QUERY,
        FETCH_WAREHOUSE_TO_CUSTOMER_EDGES_QUERY,
    ):
        for rec in session.run(query, parameters={"customer_id": customer_id}):
            d = dict(rec)
            if None not in (d["src_lat"], d["src_lon"], d["dst_lat"], d["dst_lon"]):
                edges.append(d)
    return edges