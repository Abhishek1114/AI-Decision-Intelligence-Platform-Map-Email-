"""
Phase 1 — Domain models for the Customer Digital Twin.

Every node in the supply chain graph is owned by a Customer.
customer_id is the multi-tenancy key — every Cypher query filters by it.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class SupplierTier(str, Enum):
    TIER_1 = "tier_1"   # Direct supplier — ships finished components to customer
    TIER_2 = "tier_2"   # Sub-supplier — supplies Tier 1
    TIER_3 = "tier_3"   # Raw material supplier — supplies Tier 2

class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"

class NodeStatus(str, Enum):
    ACTIVE   = "active"
    INACTIVE = "inactive"
    AT_RISK  = "at_risk"
    DISRUPTED = "disrupted"

class TransportMode(str, Enum):
    SEA   = "sea"
    AIR   = "air"
    ROAD  = "road"
    RAIL  = "rail"
    MULTI = "multimodal"

class IndustryVertical(str, Enum):
    ELECTRONICS    = "electronics"
    PHARMA         = "pharma"
    AUTOMOTIVE     = "automotive"
    FMCG           = "fmcg"
    AEROSPACE      = "aerospace"
    SEMICONDUCTOR  = "semiconductor"
    OTHER          = "other"


# ──────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────

class BaseNode(BaseModel):
    """All nodes carry customer_id for multi-tenant isolation."""
    customer_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: NodeStatus = NodeStatus.ACTIVE
    notes: Optional[str] = None


# ──────────────────────────────────────────────
# Customer (root node — one per tenant)
# ──────────────────────────────────────────────

class Customer(BaseModel):
    """
    Root node of the digital twin. One Customer = one tenant.
    All other nodes are owned by exactly one Customer.
    """
    customer_id: str = Field(default_factory=lambda: f"cust_{uuid.uuid4().hex[:8]}")
    company_name: str
    industry: IndustryVertical
    headquarters_country: str
    headquarters_city: str
    contact_email: str
    annual_revenue_usd: Optional[float] = None   # for weighting impact severity
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# ──────────────────────────────────────────────
# Product → Component hierarchy
# ──────────────────────────────────────────────

class Product(BaseNode):
    """
    A finished product the customer sells.
    Example: iPhone 16 Pro, MacBook M4, Galaxy S25
    """
    product_id: str = Field(default_factory=lambda: f"prod_{uuid.uuid4().hex[:8]}")
    name: str
    sku: Optional[str] = None
    category: str                          # e.g. "smartphone", "laptop"
    annual_revenue_usd: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.LOW


class Component(BaseNode):
    """
    A component or sub-assembly used inside one or more Products.
    Example: A-series chip, OLED display, lithium battery cell
    """
    component_id: str = Field(default_factory=lambda: f"comp_{uuid.uuid4().hex[:8]}")
    name: str
    part_number: Optional[str] = None
    category: str                          # e.g. "semiconductor", "display", "battery"
    is_sole_sourced: bool = False          # true = single supplier, high risk
    lead_time_days: Optional[int] = None
    inventory_buffer_days: Optional[int] = None
    risk_level: RiskLevel = RiskLevel.LOW


# ──────────────────────────────────────────────
# Supplier → Factory hierarchy
# ──────────────────────────────────────────────

class Supplier(BaseNode):
    """
    A company that supplies components to the customer.
    The same real-world company (TSMC) is a SEPARATE node for each customer —
    because the relationship (what they supply, what tier) differs per customer.
    """
    supplier_id: str = Field(default_factory=lambda: f"supp_{uuid.uuid4().hex[:8]}")
    company_name: str
    tier: SupplierTier
    country: str
    city: Optional[str] = None
    latitude: Optional[float] = None    # ← ADD — optional since not every
    longitude: Optional[float] = None   # ← ADD   supplier needs precision now
    contract_value_usd: Optional[float] = None
    lead_time_days: Optional[int] = None
    on_time_delivery_rate: Optional[float] = None
    quality_score: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.LOW
    is_sole_source: bool = False

    
class Factory(BaseNode):
    """
    A physical manufacturing site operated by a Supplier.
    One Supplier may have many Factories in different countries.
    """
    factory_id: str = Field(default_factory=lambda: f"fact_{uuid.uuid4().hex[:8]}")
    name: str
    supplier_id: str                       # parent supplier
    country: str
    city: str
    latitude: float
    longitude: float
    capacity_utilisation: Optional[float] = None   # 0.0 – 1.0
    workforce_size: Optional[int] = None
    risk_level: RiskLevel = RiskLevel.LOW
    produces_components: list[str] = Field(default_factory=list)  # component_ids


# ──────────────────────────────────────────────
# Warehouse / Distribution Center
# ──────────────────────────────────────────────

class Warehouse(BaseNode):
    """
    A storage facility owned or used by the customer.
    Holds finished goods or strategic component inventory.
    """
    warehouse_id: str = Field(default_factory=lambda: f"wh_{uuid.uuid4().hex[:8]}")
    name: str
    country: str
    city: str
    latitude: float
    longitude: float
    type: str = "warehouse"                # "warehouse" | "distribution_center" | "dc"
    capacity_sqm: Optional[float] = None
    inventory_buffer_days: Optional[int] = None


# ──────────────────────────────────────────────
# Port
# ──────────────────────────────────────────────

class Port(BaseNode):
    """
    A sea or air port used by the customer's supply chain.
    Ports are customer-scoped — only ports in this customer's routes appear here.
    """
    port_id: str = Field(default_factory=lambda: f"port_{uuid.uuid4().hex[:8]}")
    name: str
    un_locode: str                         # e.g. "TWKHH" for Kaohsiung
    country: str
    city: str
    latitude: float
    longitude: float
    port_type: str = "sea"                 # "sea" | "air"
    annual_throughput_teu: Optional[int] = None
    congestion_level: RiskLevel = RiskLevel.LOW


# ──────────────────────────────────────────────
# Route
# ──────────────────────────────────────────────

class Route(BaseNode):
    """
    A shipping lane used to move goods between two nodes.
    Route is a first-class node (not a relationship) so it can
    carry properties and be targeted by disruption events.
    """
    route_id: str = Field(default_factory=lambda: f"route_{uuid.uuid4().hex[:8]}")
    name: str
    origin_node_id: str                    # factory_id, port_id, or warehouse_id
    origin_node_type: str                  # "Factory" | "Port" | "Warehouse"
    destination_node_id: str
    destination_node_type: str
    transport_mode: TransportMode
    transit_time_days: int
    carrier: Optional[str] = None
    annual_shipment_volume: Optional[int] = None
    risk_level: RiskLevel = RiskLevel.LOW


# ──────────────────────────────────────────────
# Relationships (used in Cypher, documented here for reference)
# ──────────────────────────────────────────────

"""
Graph relationships (direction always left → right):

(Customer)-[:OWNS]->(Product)
(Customer)-[:OWNS]->(Supplier)
(Customer)-[:OWNS]->(Warehouse)

(Product)-[:CONTAINS]->(Component)
(Supplier)-[:SUPPLIES]->(Component)          # with properties: tier, contract_value
(Supplier)-[:OPERATES]->(Factory)
(Factory)-[:PRODUCES]->(Component)
(Factory)-[:SHIPS_VIA]->(Port)
(Warehouse)-[:SERVED_BY]->(Port)
(Route)-[:CONNECTS]->(Port|Factory|Warehouse) # origin
(Port|Factory|Warehouse)-[:CONNECTS]->(Route) # destination

Multi-hop example:
(Customer {customer_id})-[:OWNS]->(Supplier)-[:OPERATES]->
  (Factory)-[:PRODUCES]->(Component)<-[:CONTAINS]-(Product)<-[:OWNS]-(Customer)
"""