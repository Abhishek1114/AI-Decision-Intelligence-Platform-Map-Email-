import json

def format_manager_alert(impact: dict, assessment: dict, event_title: str) -> str:
    """Render one AgentAssessment + its matching IMPACTS record as a
    manager-facing alert. `impact` is one entry from ne['impacts']."""
    initial_sev = (impact.get("severity") or "unknown").upper()
    final_sev = (assessment["severity"] or "unknown").upper()
    conf_pct = int(round((assessment["confidence"] or 0) * 100))
    conf_label = "High" if conf_pct >= 80 else "Medium" if conf_pct >= 50 else "Low"

    lines = []
    headline = f"⚠️ {final_sev} — {event_title}"
    headline += f" — customer={assessment['customer_id']} via supplier={assessment['supplier_id']}"
    if initial_sev != final_sev and initial_sev != "UNKNOWN":
        headline += f"  [Initial: {initial_sev} → Reassessed: {final_sev}]"
    lines.append(headline)
    lines.append(f"Confidence: {conf_label} ({conf_pct}%) | Updated: {assessment['updated_at']}")
    lines.append("")

    products = assessment["affected_product_ids"] or []
    lines.append(
        "Affected products: " + (", ".join(products) if products
                                  else "⚠️ NONE IDENTIFIED — check graph traversal / narrowing_method")
    )
    lines.append("")
    lines.append(f"Impact: {assessment['predicted_business_impact']}")
    lines.append("")

    evidence = assessment["evidence"] or []
    if evidence:
        lines.append("Evidence:")
        for e in evidence:
            lines.append(f"  • {e}")
    else:
        lines.append("Evidence: ⚠️ none returned by model — treat impact statement as unverified")
    lines.append("")

    lines.append("Recommended actions:")
    try:
        actions = json.loads(assessment["recommended_actions_json"] or "[]")
    except json.JSONDecodeError:
        actions = []
    for a in actions:
        lines.append(f"  [{a.get('urgency', '?').upper()}] {a.get('action', '')}")
        lines.append(f"      → {a.get('rationale', '')}")

    return "\n".join(lines)