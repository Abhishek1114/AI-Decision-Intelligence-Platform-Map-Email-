"""
graph/models/nodes.py
Domain models for all Neo4j node types in the Supply Chain graph.
Each model maps 1:1 to a node label and its required/optional properties.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


# ──────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────

class NodeLabel(str, Enum):
    SUPPLIER    = "Supplier"
    FACILITY    = "Facility"
    PORT        = "Port"
    PRODUCT     = "Product"
    COMPONENT   = "Component"
    ROUTE       = "Route"
    REGION      = "Region"
    EVENT       = "DisruptionEvent"


class FacilityType(str, Enum):
    FACTORY         = "factory"
    WAREHOUSE       = "warehouse"
    DISTRIBUTION    = "distribution_center"
    ASSEMBLY        = "assembly"


class TransportMode(str, Enum):
    SEA     = "sea"
    AIR     = "air"
    RAIL    = "rail"
    ROAD    = "road"
    MULTI   = "multimodal"


class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class EventType(str, Enum):
    WEATHER         = "weather"
    GEOPOLITICAL    = "geopolitical"
    LABOR           = "labor"
    CYBER           = "cyber"
    LOGISTICS       = "logistics"
    NATURAL         = "natural_disaster"


# ──────────────────────────────────────────────
# Node Models
# ──────────────────────────────────────────────

class SupplierNode(BaseModel):
    """Represents a company or entity that supplies goods/components."""
    supplier_id: str = Field(..., description="Globally unique identifier, e.g. 'SUP-001'")
    name: str
    country: str                            # ISO-3166 alpha-2
    region_id: str                          # FK → RegionNode.region_id
    tier: int = Field(..., ge=1, le=4)      # 1 = direct, 2-4 = sub-supplier tiers
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.LOW
    annual_revenue_usd: Optional[float] = None
    employee_count: Optional[int] = None
    certifications: List[str] = Field(default_factory=list)  # e.g. ["ISO9001", "IATF16949"]
    is_single_source: bool = False          # no alternative supplier for any product
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FacilityNode(BaseModel):
    """Physical location owned/operated by a Supplier."""
    facility_id: str                        # e.g. 'FAC-001'
    supplier_id: str                        # FK → SupplierNode
    name: str
    facility_type: FacilityType
    country: str
    city: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    capacity_units_per_day: Optional[int] = None
    utilization_pct: float = Field(0.0, ge=0.0, le=100.0)
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PortNode(BaseModel):
    """Sea/air port or logistics hub. Key chokepoints in the graph."""
    port_id: str                            # UN/LOCODE preferred, e.g. 'USNYC'
    name: str
    country: str
    city: str
    port_type: str                          # "sea" | "air" | "inland"
    latitude: float
    longitude: float
    throughput_teu_annual: Optional[int] = None   # TEU for sea ports
    congestion_index: float = Field(0.0, ge=0.0, le=1.0)  # 0=free, 1=gridlock
    avg_dwell_days: Optional[float] = None
    region_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProductNode(BaseModel):
    """Finished product or SKU tracked in the supply chain."""
    product_id: str                         # e.g. 'PROD-001'
    name: str
    sku: str
    category: str
    criticality: RiskLevel = RiskLevel.LOW  # how bad if supply fails
    lead_time_days: int = Field(..., ge=0)
    safety_stock_days: int = Field(0, ge=0)
    unit_cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ComponentNode(BaseModel):
    """Raw material or sub-component used in manufacturing."""
    component_id: str                       # e.g. 'COMP-001'
    name: str
    material_type: str                      # e.g. "semiconductor", "rare_earth", "polymer"
    hs_code: Optional[str] = None           # Harmonized System tariff code
    unit_of_measure: str = "unit"           # unit | kg | liter | m2
    is_hazmat: bool = False
    substitutability: RiskLevel = RiskLevel.LOW   # how easy to substitute
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RouteNode(BaseModel):
    """
    Logical shipping lane between two locations.
    Can be Facility→Port, Port→Port, or Port→Facility.
    """
    route_id: str                           # e.g. 'RT-001'
    origin_id: str                          # facility_id or port_id
    destination_id: str                     # facility_id or port_id
    transport_mode: TransportMode
    distance_km: Optional[float] = None
    transit_days_avg: float
    transit_days_std: float = 0.0
    cost_per_unit_usd: Optional[float] = None
    carrier: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RegionNode(BaseModel):
    """Geographic region grouping countries for macro-level risk analysis."""
    region_id: str                          # e.g. 'APAC', 'EU', 'NA'
    name: str
    countries: List[str]                    # ISO-3166 alpha-2 list
    geopolitical_risk: float = Field(0.0, ge=0.0, le=1.0)
    climate_risk: float = Field(0.0, ge=0.0, le=1.0)


class DisruptionEventNode(BaseModel):
    """
    A real or predicted disruption event. Attached to affected Suppliers,
    Facilities, Ports, or Routes via [:AFFECTS] relationships.
    """
    event_id: str                           # e.g. 'EVT-20240315-001'
    event_type: EventType
    title: str
    description: str
    severity: RiskLevel
    source: str                             # e.g. 'gdelt', 'noaa', 'portwatch', 'manual'
    source_url: Optional[str] = None
    affected_region: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    is_resolved: bool = False
    impact_score: float = Field(0.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)