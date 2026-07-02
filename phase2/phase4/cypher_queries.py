"""
Phase 4 — Cypher query library.

Every query here is parameterized (never string-interpolated) and follows
the Phase 1-3 convention: explicit params dicts, never **model_dump().
Kept as raw strings in one place so Phase 4 doesn't repeat the property-name
drift that cost Phase 3 several debugging rounds (company_name vs name,
tier_1 vs tier1) -- one file to check against the schema reference, not
scattered across DAG task functions.

Confirmed against live data this session (not assumed):
  - Supplier.is_sole_source lives on the Supplier node, not on OWNS.
  - FEEDS points (tier_2)-[:FEEDS]->(tier_1) -- e.g. ASML -[:FEEDS]-> TSMC.
    Read as "the tier_2 supplier feeds the tier_1 supplier."
"""

# ---------------------------------------------------------------------------
# Step 1 -- Event eligibility filter
# ---------------------------------------------------------------------------
FETCH_ELIGIBLE_EVENTS = """
MATCH (e:GlobalEvent)
WHERE e.processed = true
  AND e.location IS NOT NULL
  AND (
        e.source_tier = 'tier_1'
        OR (e.source_tier = 'tier_2' AND e.severity IN ['high', 'critical'])
      )
  AND NOT EXISTS {
        MATCH (e)-[r:IMPACTS]->(:Customer)
        WHERE r.calculated_at IS NOT NULL
      }
RETURN e.event_id AS event_id,
       e.severity AS severity,
       e.source_tier AS source_tier,
       e.location AS location
"""
# NOTE: the NOT EXISTS guard skips events already scored -- reruns only pick
# up new events, matching Phase 3's mark_processed pattern. If you change
# scoring weights and want a full re-score, drop that clause; WRITE_IMPACTS'
# MERGE will overwrite existing IMPACTS in place rather than duplicate them.
#
# Events with no MENTIONS but also no location are silently excluded here
# (Path B can't run without coordinates, and this filter requires location
# IS NOT NULL). Worth checking whether that case exists before going live:
#   MATCH (e:GlobalEvent)-[:MENTIONS]->() WHERE e.location IS NULL RETURN count(e)
# If it's non-zero, split this into two filters so Path A can run standalone
# for events lacking coordinates.

# ---------------------------------------------------------------------------
# Step 2a -- Path A: direct mention (Phase 3's MENTIONS relationship)
# ---------------------------------------------------------------------------
PATH_A_DIRECT_MENTION = """
MATCH (e:GlobalEvent {event_id: $event_id})-[m:MENTIONS]->(s:Supplier)
RETURN s.supplier_id AS supplier_id,
       s.tier AS tier,
       s.company_name AS company_name,
       s.component_criticality AS component_criticality,
       s.is_sole_source AS is_sole_source,
       m.confidence AS match_confidence,
       'mention' AS match_method
"""

# ---------------------------------------------------------------------------
# Step 2b -- Path B: geo-proximity
# ---------------------------------------------------------------------------
PATH_B_GEO_PROXIMITY = """
MATCH (e:GlobalEvent {event_id: $event_id})
MATCH (s:Supplier)
WHERE s.location IS NOT NULL
  AND point.distance(e.location, s.location) <= $distance_threshold_m
RETURN s.supplier_id AS supplier_id,
       s.tier AS tier,
       s.company_name AS company_name,
       s.component_criticality AS component_criticality,
       s.is_sole_source AS is_sole_source,
       point.distance(e.location, s.location) AS distance_m,
       'geo' AS match_method
"""

# ---------------------------------------------------------------------------
# Step 3 -- Walk up to customer
# ---------------------------------------------------------------------------
WALK_UP_TIER_1 = """
MATCH (s:Supplier {supplier_id: $supplier_id, tier: 'tier_1'})<-[:OWNS]-(c:Customer)
RETURN c.customer_id AS customer_id,
       c.company_name AS customer_name
"""

# FEEDS direction confirmed: (tier_2)-[:FEEDS]->(tier_1). The tier_2
# supplier matched by Path A/B is the *start* node of FEEDS, walking
# forward to its tier_1 parent, then up via OWNS to the customer.
WALK_UP_TIER_2 = """
MATCH (s2:Supplier {supplier_id: $supplier_id, tier: 'tier_2'})-[:FEEDS]->(s1:Supplier {tier: 'tier_1'})<-[:OWNS]-(c:Customer)
RETURN c.customer_id AS customer_id,
       c.company_name AS customer_name,
       s1.supplier_id AS tier1_supplier_id,
       s1.company_name AS tier1_supplier_name
"""

# ---------------------------------------------------------------------------
# Step 6 -- Write IMPACTS
# ---------------------------------------------------------------------------
# supplier_id is deliberately part of the MERGE key: if the same event
# reaches the same customer via two different suppliers (e.g. direct
# mention of one supplier plus a geo-match on an unrelated nearby tier_2
# supplier that feeds the same customer), that's two distinct impact
# paths worth keeping separate for audit/tuning -- not collapsed into
# one relationship where one path's score silently overwrites the other's.
WRITE_IMPACTS = """
MATCH (e:GlobalEvent {event_id: $event_id})
MATCH (c:Customer {customer_id: $customer_id})
MERGE (e)-[r:IMPACTS {supplier_id: $supplier_id}]->(c)
ON CREATE SET
    r.score = $score,
    r.alert_triggered = $alert_triggered,
    r.calculated_at = $calculated_at,
    r.match_method = $match_method,
    r.match_confidence = $match_confidence,
    r.severity = $severity,
    r.tier = $tier
ON MATCH SET
    r.score = $score,
    r.alert_triggered = $alert_triggered,
    r.calculated_at = $calculated_at,
    r.match_method = $match_method,
    r.match_confidence = $match_confidence,
    r.severity = $severity,
    r.tier = $tier
"""