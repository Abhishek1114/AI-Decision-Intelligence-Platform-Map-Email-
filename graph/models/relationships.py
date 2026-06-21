"""
graph/models/relationships.py
All relationship types in the Supply Chain graph.
Direction: (source)-[:REL_TYPE]->(target)
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


# ──────────────────────────────────────────────
# Relationship Type Constants
# (Used as string keys in Cypher queries)
# ──────────────────────────────────────────────

class RelType:
    # Supplier relationships
    SUPPLIES        = "SUPPLIES"         # (Supplier)-[:SUPPLIES]->(Product)
    MANUFACTURES_AT = "MANUFACTURES_AT"  # (Supplier)-[:MANUFACTURES_AT]->(Facility)
    SUB_SUPPLIER_OF = "SUB_SUPPLIER_OF"  # (Supplier)-[:SUB_SUPPLIER_OF]->(Supplier) tier chain
    LOCATED_IN      = "LOCATED_IN"       # (Facility|Port)-[:LOCATED_IN]->(Region)

    # Logistics relationships
    SHIPS_VIA       = "SHIPS_VIA"        # (Facility)-[:SHIPS_VIA]->(Port)
    CONNECTS_TO     = "CONNECTS_TO"      # (Port)-[:CONNECTS_TO]->(Port) — shipping lane
    DELIVERS_TO     = "DELIVERS_TO"      # (Port)-[:DELIVERS_TO]->(Facility)
    USES_ROUTE      = "USES_ROUTE"       # (Supplier)-[:USES_ROUTE]->(Route)

    # Product/component relationships
    REQUIRES        = "REQUIRES"         # (Product)-[:REQUIRES]->(Component)
    SOURCED_FROM    = "SOURCED_FROM"     # (Component)-[:SOURCED_FROM]->(Supplier)
    ALTERNATIVE_FOR = "ALTERNATIVE_FOR"  # (Component)-[:ALTERNATIVE_FOR]->(Component)

    # Disruption relationships
    AFFECTS         = "AFFECTS"          # (DisruptionEvent)-[:AFFECTS]->(Supplier|Facility|Port|Route)
    TRIGGERS        = "TRIGGERS"         # (DisruptionEvent)-[:TRIGGERS]->(DisruptionEvent) cascades


# ──────────────────────────────────────────────
# Relationship Property Models
# ──────────────────────────────────────────────

class SuppliesRel(BaseModel):
    """(Supplier)-[:SUPPLIES {props}]->(Product)"""
    annual_volume_units: Optional[int] = None
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None
    lead_time_days: Optional[int] = None
    is_preferred: bool = False
    share_of_supply_pct: float = Field(100.0, ge=0.0, le=100.0)


class RequiresRel(BaseModel):
    """(Product)-[:REQUIRES {props}]->(Component)"""
    quantity_per_unit: float = Field(1.0, gt=0.0)
    unit_of_measure: str = "unit"
    is_critical: bool = False               # if missing, production halts


class ConnectsToRel(BaseModel):
    """(Port)-[:CONNECTS_TO {props}]->(Port) — shipping lane metadata"""
    transport_mode: str                     # TransportMode value
    distance_km: Optional[float] = None
    transit_days_avg: float
    weekly_sailings: Optional[int] = None
    carrier_alliances: List[str] = Field(default_factory=list)


class AffectsRel(BaseModel):
    """(DisruptionEvent)-[:AFFECTS {props}]->(any node)"""
    impact_type: str                        # "supply_delay" | "shutdown" | "cost_increase" | "reroute"
    estimated_delay_days: Optional[float] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class SubSupplierOfRel(BaseModel):
    """(Supplier)-[:SUB_SUPPLIER_OF {props}]->(Supplier) — tier chain"""
    tier_from: int                          # tier of the source supplier
    tier_to: int                            # tier of the target (always tier_from - 1)
    component_ids: List[str] = Field(default_factory=list)  # what flows up