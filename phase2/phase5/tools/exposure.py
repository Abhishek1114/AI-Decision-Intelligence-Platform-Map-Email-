"""
Phase 5 — Revenue-at-risk exposure calculation.

Pure function, no Neo4j/LLM dependency — mirrors phase4/scoring.py's
discipline exactly. This is the single place a dollar figure is allowed
to be computed. The LLM in agent/graph.py must never invent one; it may
only narrate the ComputedExposure object handed to it in ObservedFacts.

Model (deliberately conservative, explainable in one sentence each step):

  exposure_days = max(0, lead_time_days - inventory_buffer_days)
      -- days of production with zero cushion once the buffer runs out.

  effective_days = min(assumed_disruption_days, exposure_days)
      -- can't lose more days than the outage lasts, and can't lose more
         than the buffer fails to cover.

  exposure_fraction = 1.0 if sole-sourced (no qualified alternative can
      absorb any volume during a lead-time-scale outage) else the
      unmet-volume share if alternative annual_volume data exists,
      else 1.0 (unknown coverage -> conservative, not optimistic).

  point_estimate = (annual_revenue_usd / 365) * effective_days * exposure_fraction
  low/high = point_estimate -30%/+30%, both hard-capped at annual_revenue_usd.

assumed_disruption_days is an explicit, labeled assumption (per-severity
default, overridable) -- never hidden inside LLM prose. That's what makes
the number falsifiable instead of a black box.
"""
from __future__ import annotations
from typing import Optional, Literal

from phase2.phase5.models import ComputedExposure

Severity = Literal["low", "medium", "high", "critical"]

# Conservative defaults; override with real data from similar_past_events'
# actual resolution time when available (see build_observed_facts).
DEFAULT_DISRUPTION_DAYS: dict[str, int] = {
    "low": 3,
    "medium": 7,
    "high": 14,
    "critical": 21,
}


def compute_component_exposure(
    annual_revenue_usd: Optional[float],
    lead_time_days: int,
    inventory_buffer_days: int,
    is_sole_sourced: bool,
    severity: Optional[str],
    best_alternative_annual_volume: Optional[int] = None,
    required_annual_volume: Optional[int] = None,
    disruption_days_override: Optional[int] = None,
) -> Optional[ComputedExposure]:
    """
    Returns None if annual_revenue_usd is unknown -- we never guess a
    revenue baseline out of thin air. A missing exposure is more honest
    than a fabricated one.
    """
    if annual_revenue_usd is None or annual_revenue_usd <= 0:
        return None

    exposure_days = max(0, lead_time_days - inventory_buffer_days)
    if exposure_days == 0:
        return ComputedExposure(
            low=0.0, high=0.0,
            exposure_days=0, effective_days=0, exposure_fraction=0.0,
            basis=(
                f"Inventory buffer ({inventory_buffer_days}d) covers the full "
                f"lead time ({lead_time_days}d) -- no revenue exposure modeled."
            ),
        )

    severity_key = (severity or "medium").lower()
    assumed_days = disruption_days_override or DEFAULT_DISRUPTION_DAYS.get(severity_key, 7)
    effective_days = min(assumed_days, exposure_days)

    if is_sole_sourced:
        # Sole-sourced means no currently-qualified alternative exists,
        # regardless of what alternatives_by_component lists as candidates
        # (those are unqualified prospects, not active capacity).
        fraction = 1.0
        coverage_note = "sole-sourced -- no qualified alternative capacity"
    elif best_alternative_annual_volume is not None and required_annual_volume:
        unmet = max(0, required_annual_volume - best_alternative_annual_volume)
        fraction = min(1.0, unmet / required_annual_volume)
        coverage_note = (
            f"alternative supplier covers {best_alternative_annual_volume}/"
            f"{required_annual_volume} units/yr of demand"
        )
    else:
        # No volume data to prove coverage -- conservative default, not optimistic.
        fraction = 1.0
        coverage_note = "no alternative volume data available -- treated as fully exposed"

    daily_revenue = annual_revenue_usd / 365.0
    point_estimate = daily_revenue * effective_days * fraction

    low = max(0.0, point_estimate * 0.7)
    high = min(point_estimate * 1.3, annual_revenue_usd)
    low = min(low, high)  # guard against the cap collapsing the range

    basis = (
        f"{effective_days} of {exposure_days} uncovered days "
        f"(lead time {lead_time_days}d - buffer {inventory_buffer_days}d, "
        f"assumed {severity_key}-severity disruption of {assumed_days}d) "
        f"x {fraction:.0%} exposure ({coverage_note}), "
        f"capped at product annual revenue."
    )

    return ComputedExposure(
        low=round(low, 2), high=round(high, 2),
        exposure_days=exposure_days, effective_days=effective_days,
        exposure_fraction=round(fraction, 4), basis=basis,
    )


def aggregate_product_exposure(
    component_exposures: list[ComputedExposure],
) -> Optional[ComputedExposure]:
    """
    A product halts if ANY single critical component fails -- exposure
    across components is NOT additive (that would double-count the same
    halted revenue). Take the single worst component's exposure as the
    product-level figure, not the sum.
    """
    valid = [e for e in component_exposures if e is not None and e.high > 0]
    if not valid:
        return None
    worst = max(valid, key=lambda e: e.high)
    return ComputedExposure(
        low=worst.low, high=worst.high,
        exposure_days=worst.exposure_days, effective_days=worst.effective_days,
        exposure_fraction=worst.exposure_fraction,
        basis=f"Driven by worst-case component: {worst.basis}",
    )