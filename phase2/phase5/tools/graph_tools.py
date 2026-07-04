"""
Phase 5 — Graph traversal tools.

Built against the CONFIRMED live schema only:
  (Customer)-[:OWNS]->(Product)                      -- confirmed forward, count=10
  (Product)-[:CONTAINS {quantity}]->(Component)       -- confirmed
  (Supplier)-[:SUPPLIES {annual_volume?}]->(Component) -- confirmed, annual_volume nullable
  Component keys: component_id, name, category, status, risk_level, lead_time_days,
                  inventory_buffer_days, is_sole_sourced, customer_id, created_at

IMPORTANT: OWNS is overloaded across (Customer)->(Product) and (Customer)->(Supplier).
Every query below constrains by target label explicitly — never relies on relationship
type alone to disambiguate.

Multi-tenant isolation: every query filters by customer_id, including on Component
(which carries its own customer_id — do not assume it inherits from Product alone).
"""
from __future__ import annotations
import hashlib
import json
import re
from typing import Optional
from neo4j import Driver

from phase2.phase5.models import (
    ObservedProduct, ObservedComponent, ObservedSupplierAlternative,
    ObservedFacts, NarrowingMethod, SimilarEventSummary,
)

DEDUP_WINDOW_HOURS = 72  # events with matching normalized title within this window
                          # are treated as the same real-world event


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — same-event titles
    that differ only in casing/punctuation should still hash identically."""
    lowered = title.lower().strip()
    no_punct = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", no_punct)


def compute_dedup_key(title: str) -> str:
    return hashlib.md5(normalize_title(title).encode()).hexdigest()[:16]


def find_existing_assessment(
    driver: Driver, dedup_key: str, customer_id: str, supplier_id: str,
    window_hours: int = DEDUP_WINDOW_HOURS,
) -> Optional[str]:
    """
    Returns the existing AgentAssessment's assessment_id if one was created for
    this (customer, title-hash, supplier) combination within the window.

    supplier_id is included deliberately, matching Phase 4's WRITE_IMPACTS
    merge key ((event_id, customer_id, supplier_id)) — the same real-world
    event hitting one customer via two different suppliers is two distinct
    impact paths Phase 4 keeps separate for audit/tuning, and Phase 5 must
    not silently collapse that granularity via title-based dedup. Title-hash
    dedup is only meant to catch upstream duplicate GlobalEvent *nodes*
    (same real event, same supplier, distinct node id) — not distinct
    supplier matches on the same real event.
    """
    query = """
    MATCH (a:AgentAssessment {assessment_id: $assessment_id})
    WHERE a.customer_id = $customer_id
      AND a.created_at > datetime() - duration({hours: $window_hours})
    RETURN a.assessment_id AS assessment_id
    LIMIT 1
    """
    assessment_id = f"assess_{dedup_key}_{customer_id}_{supplier_id}"
    with driver.session() as session:
        result = session.run(
            query, assessment_id=assessment_id, customer_id=customer_id,
            window_hours=window_hours,
        )
        record = result.single()
        return record["assessment_id"] if record else None


def link_duplicate_event(driver: Driver, event_id: str, assessment_id: str):
    """Points a duplicate event at the existing assessment for traceability,
    and appends event_id to the assessment's source_event_ids list (dedup'd)."""
    query = """
    MATCH (e:GlobalEvent {event_id: $event_id})
    MATCH (a:AgentAssessment {assessment_id: $assessment_id})
    MERGE (a)-[:REGARDING]->(e)
    SET a.source_event_ids = CASE
        WHEN $event_id IN coalesce(a.source_event_ids, []) THEN a.source_event_ids
        ELSE coalesce(a.source_event_ids, []) + $event_id
    END
    """
    with driver.session() as session:
        session.run(query, event_id=event_id, assessment_id=assessment_id)


def resolve_canonical_event_id(driver: Driver, event_id: str) -> str:
    """
    Heuristic dedup for the still-open upstream GlobalEvent duplication bug
    (same-title distinct nodes from separate ingestion runs, per Phase 4
    diagnosis). This is a stand-in at the Phase 5 boundary, NOT a substitute
    for the real fix (deterministic content-hash event IDs at ingestion,
    per the Phase 2 lesson) — revisit removing this once that lands.

    Groups GlobalEvent nodes by (normalized title, source_tier) and picks the
    earliest-created node in the group as canonical. All duplicates converge
    on the same assessment_id downstream, so the agent only ever pays for one
    LLM call per real-world event regardless of how many duplicate nodes exist.
    """
    query = """
    MATCH (e:GlobalEvent {event_id: $event_id})
    WITH toLower(trim(e.title)) AS norm_title, e.source_tier AS tier
    MATCH (dup:GlobalEvent)
    WHERE toLower(trim(dup.title)) = norm_title AND dup.source_tier = tier
    RETURN dup.event_id AS event_id
    ORDER BY dup.created_at ASC, dup.event_id ASC
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(query, event_id=event_id)
        record = result.single()
        return record["event_id"] if record else event_id


def get_event_impact_metadata(driver: Driver, event_id: str, customer_id: str) -> dict:
    """
    Pulls the IMPACTS relationship connecting this event to this customer.
    Confirmed live keys: score, match_confidence, alert_triggered, calculated_at,
    severity, match_method, supplier_id, tier.
    """
    query = """
    MATCH (e:GlobalEvent {event_id: $event_id})-[r:IMPACTS]->(c:Customer {customer_id: $customer_id})
    RETURN properties(r) AS props
    LIMIT 1
    """
    with driver.session() as session:
        result = session.run(query, event_id=event_id, customer_id=customer_id)
        record = result.single()
        return dict(record["props"]) if record else {}


def get_customer_product_graph(
    driver: Driver,
    customer_id: str,
    matched_supplier_id: Optional[str] = None,
) -> tuple[list[ObservedProduct], NarrowingMethod]:
    """
    Returns the customer's affected product/component/alternative-supplier graph.

    If matched_supplier_id is provided, narrows to only products whose components
    are supplied by that supplier (NarrowingMethod.SUPPLIER_MATCH).
    Otherwise falls back to the customer's full product catalog
    (NarrowingMethod.NONE) — this is the honest fallback, not a silent guess.
    """
    if matched_supplier_id:
        query = """
        MATCH (c:Customer {customer_id: $customer_id})-[:OWNS]->(p:Product)
        MATCH (p)-[cont:CONTAINS]->(comp:Component {customer_id: $customer_id})
        MATCH (comp)<-[:SUPPLIES]-(matched:Supplier {supplier_id: $matched_supplier_id})
        WITH c, p, collect(DISTINCT comp) AS affected_components
        MATCH (p)-[cont2:CONTAINS]->(all_comp:Component {customer_id: $customer_id})
        WHERE all_comp IN affected_components
        OPTIONAL MATCH (all_comp)<-[sup_r:SUPPLIES]-(alt:Supplier)
        RETURN p, all_comp, sup_r, alt
        """
        params = {"customer_id": customer_id, "matched_supplier_id": matched_supplier_id}
        narrowing = NarrowingMethod.SUPPLIER_MATCH
    else:
        query = """
        MATCH (c:Customer {customer_id: $customer_id})-[:OWNS]->(p:Product)
        OPTIONAL MATCH (p)-[cont:CONTAINS]->(comp:Component {customer_id: $customer_id})
        OPTIONAL MATCH (comp)<-[sup_r:SUPPLIES]-(alt:Supplier)
        RETURN p, comp AS all_comp, sup_r, alt
        """
        params = {"customer_id": customer_id}
        narrowing = NarrowingMethod.NONE

    products: dict[str, ObservedProduct] = {}

    with driver.session() as session:
        result = session.run(query, **params)
        for record in result:
            p = record["p"]
            comp = record["all_comp"]
            sup_r = record["sup_r"]
            alt = record["alt"]

            pid = p["product_id"]
            if pid not in products:
                products[pid] = ObservedProduct(
                    product_id=pid,
                    name=p["name"],
                    category=p["category"],
                    annual_revenue_usd=p.get("annual_revenue_usd"),
                )

            if comp is None:
                continue

            component_model = ObservedComponent(
                component_id=comp["component_id"],
                name=comp["name"],
                category=comp["category"],
                is_sole_sourced=comp["is_sole_sourced"],
                lead_time_days=comp["lead_time_days"],
                inventory_buffer_days=comp["inventory_buffer_days"],
                seeded_risk_level=comp.get("risk_level"),
            )
            if not any(c.component_id == component_model.component_id
                       for c in products[pid].components):
                products[pid].components.append(component_model)

            if alt is not None:
                alt_model = ObservedSupplierAlternative(
                    supplier_id=alt["supplier_id"],
                    name=alt.get("name"),
                    annual_volume=sup_r.get("annual_volume") if sup_r else None,
                    has_volume_data=bool(sup_r and sup_r.get("annual_volume") is not None),
                )
                bucket = products[pid].alternatives_by_component.setdefault(
                    component_model.component_id, []
                )
                if not any(a.supplier_id == alt_model.supplier_id for a in bucket):
                    bucket.append(alt_model)

    # Rank alternatives: known volume first (desc), unknown volume last.
    for prod in products.values():
        for comp_id, alts in prod.alternatives_by_component.items():
            alts.sort(key=lambda a: (a.annual_volume is None, -(a.annual_volume or 0)))

    return list(products.values()), narrowing


def get_similar_event_context(
    driver: Driver, event_ids: list[str], customer_id: str
) -> list[SimilarEventSummary]:
    """
    Enriches bare RAG event_ids with actual content — this is what makes
    'similar past disruptions' usable reasoning material for the LLM instead
    of an opaque ID. Also pulls a prior AgentAssessment for the same customer
    if one exists for that past event, since 'what did we recommend last time'
    is the single most useful piece of history the agent can be given.
    """
    if not event_ids:
        return []

    query = """
    UNWIND $event_ids AS eid
    MATCH (e:GlobalEvent {event_id: eid})
    OPTIONAL MATCH (e)<-[:REGARDING]-(a:AgentAssessment {customer_id: $customer_id})
    RETURN e.event_id AS event_id, e.title AS title, e.severity AS severity,
           e.category AS category, a.severity AS prior_severity,
           a.recommended_actions_json AS prior_actions_json
    """
    summaries = []
    with driver.session() as session:
        result = session.run(query, event_ids=event_ids, customer_id=customer_id)
        for record in result:
            top_action = None
            if record["prior_actions_json"]:
                try:
                    actions = json.loads(record["prior_actions_json"])
                    if actions:
                        top_action = actions[0].get("action")
                except (json.JSONDecodeError, IndexError):
                    pass
            summaries.append(SimilarEventSummary(
                event_id=record["event_id"],
                title=record["title"],
                severity=record["severity"],
                category=record["category"],
                prior_assessment_severity=record["prior_severity"],
                prior_recommended_action=top_action,
            ))
    return summaries


def build_observed_facts(
    driver: Driver,
    customer_id: str,
    event_id: str,
    supplier_id: str,
    similar_event_ids: list[str],
) -> ObservedFacts:
    """
    supplier_id is now passed directly from the alert message (Phase 4 knows
    it exactly at write time — it's part of the IMPACTS MERGE key). This
    removes the earlier LIMIT-1 guess against IMPACTS, which broke down as
    soon as one event had multiple supplier-differentiated IMPACTS to the
    same customer (confirmed this is a real, intentional Phase 4 pattern,
    not an edge case).
    """
    products, narrowing = get_customer_product_graph(driver, customer_id, supplier_id)
    similar_events = get_similar_event_context(driver, similar_event_ids, customer_id)

    return ObservedFacts(
        customer_id=customer_id,
        event_id=event_id,
        narrowing_method=narrowing,
        affected_products=products,
        similar_past_events=similar_events,
    )