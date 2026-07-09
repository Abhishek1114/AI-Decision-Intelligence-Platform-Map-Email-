# phase2/phase7/dashboard/graph_path.py
"""
Phase 7 — Graph path drill-down. Renders the actual traversal the system
used to connect a GlobalEvent to a customer's Product, so a manager can
verify the AI's reasoning against the real graph rather than trusting
the narrative alone.
"""

FETCH_PATH_QUERY = """
MATCH (a:AgentAssessment {assessment_id: $assessment_id})
MATCH (s:Supplier {supplier_id: a.supplier_id, customer_id: a.customer_id})
OPTIONAL MATCH (t2:Supplier)-[:FEEDS]->(s)
  WHERE t2.customer_id = a.customer_id
OPTIONAL MATCH (s)-[sup:SUPPLIES]->(comp:Component)
  WHERE comp.component_id IN a.affected_product_ids
     OR comp.customer_id = a.customer_id
OPTIONAL MATCH (comp)<-[:CONTAINS]-(prod:Product)
  WHERE prod.product_id IN a.affected_product_ids
RETURN s.company_name AS supplier_name, s.tier AS supplier_tier,
       s.country AS supplier_country, s.is_sole_source AS supplier_sole_source,
       collect(DISTINCT {name: t2.company_name, country: t2.country}) AS tier2_suppliers,
       collect(DISTINCT {name: comp.name, sole_sourced: comp.is_sole_sourced,
                          lead_time: comp.lead_time_days, buffer: comp.inventory_buffer_days}) AS components,
       collect(DISTINCT {name: prod.name, category: prod.category}) AS products
"""


def fetch_graph_path(session, assessment_id: str) -> dict | None:
    record = session.run(FETCH_PATH_QUERY, parameters={"assessment_id": assessment_id}).single()
    if record is None:
        return None
    return {
        "supplier_name": record["supplier_name"],
        "supplier_tier": record["supplier_tier"],
        "supplier_country": record["supplier_country"],
        "supplier_sole_source": record["supplier_sole_source"],
        "tier2_suppliers": [t for t in record["tier2_suppliers"] if t["name"]],
        "components": [c for c in record["components"] if c["name"]],
        "products": [p for p in record["products"] if p["name"]],
    }