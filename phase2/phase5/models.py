"""
Phase 5 — Pydantic models for the LangGraph agent's structured output.

Key design rule from the idea note: observed facts (pulled straight from the graph)
must be structurally separated from AI predictions (produced by the LLM's reasoning).
This is enforced here, not just by prompt instruction — the two live in different
sub-models, so a downstream consumer can trust `observed` without re-validating
against the LLM.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NarrowingMethod(str, Enum):
    SUPPLIER_MATCH = "supplier_match"   # IMPACTS carried a matched_supplier_id
    NONE = "none"                       # fallback: full customer product graph


# ---------- Observed facts (graph-derived, no LLM involved) ----------

class ObservedComponent(BaseModel):
    component_id: str
    name: str
    category: str
    is_sole_sourced: bool
    lead_time_days: int
    inventory_buffer_days: int
    seeded_risk_level: Optional[str] = None  # static Phase 1 value, never overwritten
    computed_exposure: Optional["ComputedExposure"] = None 


class ComputedExposure(BaseModel):
    """Graph/formula-derived revenue-at-risk estimate — zero LLM contribution.
    The agent may only narrate this; it must never emit its own dollar figure."""
    low: float
    high: float
    exposure_days: int
    effective_days: int
    exposure_fraction: float
    basis: str 

class ObservedSupplierAlternative(BaseModel):
    supplier_id: str
    name: Optional[str] = None
    annual_volume: Optional[int] = None  # nullable per Phase 5 scoping decision
    has_volume_data: bool = True


class ObservedProduct(BaseModel):
    product_id: str
    name: str
    category: str
    annual_revenue_usd: Optional[float] = None
    components: list[ObservedComponent] = Field(default_factory=list)
    alternatives_by_component: dict[str, list[ObservedSupplierAlternative]] = Field(default_factory=dict)
    computed_exposure: Optional["ComputedExposure"] = None   # NEW -- aggregate, worst component

class SimilarEventSummary(BaseModel):
    event_id: str
    title: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    prior_assessment_severity: Optional[str] = None       # if this customer was assessed before
    prior_recommended_action: Optional[str] = None        # top action from that prior assessment, if any


class ObservedFacts(BaseModel):
    """Everything pulled directly from Neo4j / ChromaDB — zero LLM contribution."""
    customer_id: str
    event_id: str
    narrowing_method: NarrowingMethod
    initial_severity: Optional[str] = None  # IMPACTS.severity from Phase 4, ground truth pre-LLM
    affected_products: list[ObservedProduct] = Field(default_factory=list)
    similar_past_events: list[SimilarEventSummary] = Field(default_factory=list)
    rag_used_customer_scope: bool = False  # True if customer-tagged hits were found; False = global fallback
    customer_annual_revenue_usd: Optional[float] = None  # NEW -- ceiling for cross-product aggregation


# ---------- AI prediction (LLM-produced, explicitly labeled as such) ----------

class RecommendedAction(BaseModel):
    action: str
    rationale: str
    urgency: SeverityLevel


class AIPrediction(BaseModel):
    """Everything here is the LLM's reasoning output — never treated as ground truth."""
    severity: SeverityLevel
    confidence: float = Field(ge=0.0, le=1.0)
    predicted_business_impact: str
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    evidence: list[str]  # which observed facts drove this

    @field_validator("evidence")
    @classmethod
    def evidence_must_be_present(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        if not cleaned:
            raise ValueError(
                "evidence must contain at least one non-empty item referencing an observed fact"
            )
        return cleaned

# ---------- Combined agent output ----------

class AgentRunStatus(str, Enum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"        # validation failed twice, written but flagged
    DUPLICATE_SKIPPED = "duplicate_skipped"  # same-title event already assessed recently


class AgentOutput(BaseModel):
    observed: ObservedFacts
    prediction: Optional[AIPrediction] = None  # None if status != ok
    status: AgentRunStatus = AgentRunStatus.OK
    raw_llm_output: Optional[str] = None  # kept only when status == needs_review, for debugging
    assessment_id: Optional[str] = None  # set once persisted (existing one, if duplicate)s