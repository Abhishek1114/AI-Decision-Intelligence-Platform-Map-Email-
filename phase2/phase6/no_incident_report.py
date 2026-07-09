"""
Phase 6 — no_incident_report.py

Zero-assessment periods still produce a report. A manager expecting a
weekly report and getting nothing looks like a broken pipeline, not
good news — so this path exists specifically to avoid that ambiguity.

No LLM call needed here; the content is fully determined by the absence
of data, so templating it directly avoids spending a Groq call (and a
throttle slot) on a report with nothing to synthesize.
"""


def build_no_incident_report(customer_id: str, period_start: str, period_end: str) -> str:
    return (
        "EXECUTIVE VERDICT\n"
        f"No material supply chain incidents were assessed for this customer "
        f"between {period_start} and {period_end}. No action required this period.\n\n"
        "THEMES\n"
        "None — no assessments were generated in this reporting window.\n\n"
        "APPENDIX\n"
        "Escalation rate: 0.0 (0 of 0 assessments).\n"
        "No incidents to detail.\n"
    )