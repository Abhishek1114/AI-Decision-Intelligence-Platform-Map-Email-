"""
Phase 4 — Impact scoring and alert-rule logic.

Pure functions, no Neo4j/Airflow dependencies, so they can be unit-tested
in isolation from the graph. Mirrors the weighting scheme from Phase 4
scoping:

    impact_score = severity_weight * tier_weight * sole_source_multiplier * match_confidence

Alert rule (business logic, not derivable from severity alone):

    Tier 1 supplier hit -> alert if severity in {medium, high, critical}
    Tier 2 supplier hit -> alert if severity in {high, critical}
                           AND component_criticality == 'critical'
"""

from typing import Literal, Optional

Severity = Literal["low", "medium", "high", "critical"]
Tier = Literal["tier_1", "tier_2"]

# Configurable weights -- lock these in the schema reference doc once agreed,
# same discipline as enum casing. Change here, not scattered across call sites.
SEVERITY_WEIGHT = {
    "low": 1.0,
    "medium": 2.0,
    "high": 3.0,
    "critical": 4.0,
}

TIER_WEIGHT = {
    "tier_1": 1.0,
    "tier_2": 0.5,  # one hop further from the customer -> discounted, not dismissed
}

SOLE_SOURCE_MULTIPLIER = 2.0
NON_SOLE_SOURCE_MULTIPLIER = 1.0

# Path B (geo) match confidence decays linearly from 1.0 at distance=0
# down to this floor at distance=threshold. Path A (mention) confidence
# comes directly from Phase 3's MENTIONS.confidence -- untouched here.
GEO_CONFIDENCE_FLOOR = 0.3


def geo_match_confidence(distance_m: float, threshold_m: float) -> float:
    """Linear decay from 1.0 at distance=0 to GEO_CONFIDENCE_FLOOR at distance=threshold."""
    if threshold_m <= 0:
        raise ValueError("threshold_m must be > 0")
    ratio = min(max(distance_m / threshold_m, 0.0), 1.0)
    return round(1.0 - ratio * (1.0 - GEO_CONFIDENCE_FLOOR), 4)


def alert_triggered(
    tier: Tier,
    severity: Severity,
    component_criticality: Optional[str] = None,
) -> bool:
    """
    Applies the Phase 4 alert rule. component_criticality is only
    consulted for tier_2 hits -- pass None for tier_1, it's ignored.
    """
    if tier == "tier_1":
        return severity in ("medium", "high", "critical")
    if tier == "tier_2":
        return severity in ("high", "critical") and component_criticality == "critical"
    raise ValueError(f"Unknown tier: {tier!r}")


def impact_score(
    severity: Severity,
    tier: Tier,
    is_sole_source: bool,
    match_confidence: float,
) -> float:
    """
    impact_score = severity_weight * tier_weight * sole_source_multiplier * match_confidence

    Not bounded to [0, 1] -- this is a ranking score for prioritizing
    alerts against each other, not a probability. Given current weights,
    range is roughly [0.15, 32.0] (tier_2/low/non-sole/floor-confidence
    at the bottom, tier_1/critical/sole-source/confidence=1.0 at the top).
    """
    if severity not in SEVERITY_WEIGHT:
        raise ValueError(f"Unknown severity: {severity!r}")
    if tier not in TIER_WEIGHT:
        raise ValueError(f"Unknown tier: {tier!r}")
    if not (0.0 <= match_confidence <= 1.0):
        raise ValueError(f"match_confidence out of range: {match_confidence}")

    sole_source_mult = SOLE_SOURCE_MULTIPLIER if is_sole_source else NON_SOLE_SOURCE_MULTIPLIER
    return round(
        SEVERITY_WEIGHT[severity] * TIER_WEIGHT[tier] * sole_source_mult * match_confidence,
        4,
    )