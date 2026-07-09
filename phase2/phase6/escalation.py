"""
Phase 6 — escalation.py

Raw escalation rate only. No historical baseline, no "high/low/normal"
characterization — that requires a PeriodSummary-style rollup that
doesn't exist yet and is explicitly out of scope for this version.
"""


def compute_escalation_rate(assessments: list[dict]) -> dict:
    total = len(assessments)
    if total == 0:
        return {"escalated_count": 0, "total_count": 0, "rate": 0.0}

    escalated = sum(
        1
        for a in assessments
        if a.get("initial_severity") is not None
        and a.get("severity_reassessed") is not None
        and a["initial_severity"] != a["severity_reassessed"]
    )

    return {
        "escalated_count": escalated,
        "total_count": total,
        "rate": round(escalated / total, 3),
    }