"""
Edges for the supply chain map. Only uses relationships confirmed live in
NEO4J_SCHEMA_REFERENCE_2.md (FEEDS) plus a safe property-join (Factory.supplier_id)
that needs no relationship assumption. Port/warehouse legs are deliberately
left out until digital_twin_repo.py confirms whether Route/SHIPS_VIA actually
creates graph edges or just stores property references.
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


def fetch_edges(session, customer_id: str) -> list[dict]:
    edges = []
    for query in (FETCH_FEEDS_EDGES_QUERY, FETCH_OPERATES_EDGES_QUERY, FETCH_SHIPS_VIA_EDGES_QUERY):
        for rec in session.run(query, parameters={"customer_id": customer_id}):
            d = dict(rec)
            if None not in (d["src_lat"], d["src_lon"], d["dst_lat"], d["dst_lon"]):
                edges.append(d)
    return edges