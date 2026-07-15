"""
Phase 6 — Reconciliation of multiple AgentAssessments for the same
underlying supplier/product risk within a reporting period.

Problem this solves: fetch_period_assessments returns a flat, unsegmented
list of AgentAssessment rows. When the same supplier+product combination
gets reassessed multiple times in one window (e.g. severity upgraded from
'high' to 'critical' as a disruption develops), those rows land in the
report as if they were independent risks -- two dollar figures for the
same underlying exposure, presented with no relationship, reads as a
contradiction rather than an update.

This module groups assessments by (supplier_id, affected_product_ids) --
NOT supplier_id alone, since a single supplier can feed multiple products
through genuinely separate risk paths (e.g. supp_apex_tsmc -> both Apex
Notebook Pro and Apex X1 Smartphone). Collapsing across products would
risk hiding a real second risk, not just deduplicating a real escalation.
affected_product_ids is sorted before use as a key so list ordering never
creates a false distinction between two assessments about the same set
of products.

Output is a flat list[dict], shaped exactly like the input rows (same
keys, from the same Cypher RETURN), so cluster_by_theme and
build_user_payload need no changes to their input contract. Three keys
are added per row for the prompt template to use directly.

IMPORTANT: must be called on the output of fetch_period_assessments
BEFORE cluster_by_theme() and any escalation-rate calculation -- both of
those operate on assessment_id lists, and cluster_by_theme groups by
supplier_id alone. If reconciliation runs after either, the duplicate
supplier+product rows are still visible to them and the fix doesn't
propagate.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ReconciledGroup:
    supplier_id: str
    product_ids: tuple[str, ...]
    latest: dict
    history: list[dict] = field(default_factory=list)  # earlier rows, oldest first

    @property
    def is_escalation(self) -> bool:
        return len(self.history) > 0


def _group_key(assessment: dict) -> tuple[str, tuple[str, ...]]:
    supplier_id = assessment["supplier_id"]
    product_ids = tuple(sorted(assessment.get("affected_product_ids") or []))
    return (supplier_id, product_ids)


def reconcile_assessments(assessments: list[dict]) -> list[ReconciledGroup]:
    """
    Groups a list of assessment dicts (assumed already ORDER BY created_at
    ASC, matching FETCH_PERIOD_ASSESSMENTS) into per supplier+product
    groups. Does not re-sort -- if the caller passes unsorted input, that's
    a separate bug this function should not silently mask.
    """
    groups: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
    for a in assessments:
        groups.setdefault(_group_key(a), []).append(a)

    reconciled = []
    for (supplier_id, product_ids), group in groups.items():
        reconciled.append(
            ReconciledGroup(
                supplier_id=supplier_id,
                product_ids=product_ids,
                latest=group[-1],
                history=group[:-1],
            )
        )
    return reconciled


def build_reconciled_assessment_dicts(assessments: list[dict]) -> list[dict]:
    """
    Drop-in replacement for the raw `assessments` list, called immediately
    after fetch_period_assessments() and before cluster_by_theme() /
    escalation-rate calc / build_user_payload(). Same dict shape as the
    input rows, plus:

      - is_escalation: bool
      - prior_assessment_ids: list[str]   -- audit trail back to superseded rows
      - escalation_note: str | None       -- ready-to-use instruction/summary
                                              for the Groq prompt template

    Single-assessment groups pass through with is_escalation=False and
    escalation_note=None -- zero behavior change for the common case.
    """
    output: list[dict] = []

    for g in reconcile_assessments(assessments):
        row = dict(g.latest)  # shallow copy -- never mutate the original row

        if not g.is_escalation:
            row["is_escalation"] = False
            row["prior_assessment_ids"] = []
            row["escalation_note"] = None
            output.append(row)
            continue

        prior = g.history[-1]
        prior_sev = prior.get("initial_severity") or prior.get("severity") or "unknown"
        latest_sev = g.latest.get("initial_severity") or g.latest.get("severity") or "unknown"
        prior_impact = prior.get("predicted_business_impact") or "not available"
        latest_impact = g.latest.get("predicted_business_impact") or "not available"

        row["is_escalation"] = True
        row["prior_assessment_ids"] = [h["assessment_id"] for h in g.history]

        if prior_sev != latest_sev:
            row["escalation_note"] = (
                f"This supplier/product was reassessed during this reporting "
                f"period: severity changed from '{prior_sev}' to '{latest_sev}' "
                f"(assessment {prior['assessment_id']} -> {g.latest['assessment_id']}). "
                f"Earlier modeled impact: {prior_impact}. Current modeled impact: "
                f"{latest_impact}. Report ONLY the current figure as the operative "
                f"estimate, and add one sentence noting the escalation and why it "
                f"changed (do not present both figures as separate risks)."
            )
        else:
            row["escalation_note"] = (
                f"This supplier/product was reassessed {len(g.history)} additional "
                f"time(s) in this period with unchanged severity ('{latest_sev}'). "
                f"Treat as one ongoing risk with one impact figure, not multiple."
            )

        output.append(row)

    return output