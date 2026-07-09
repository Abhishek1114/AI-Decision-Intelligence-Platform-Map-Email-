"""
Phase 6 — validate_output.py

Never trust the LLM output on its own — same principle as Phase 5's
AIPrediction.evidence validator. Two checks:
  1. Every cited event id actually exists in the source data (no
     fabricated citations slipping through).
  2. The fixed section structure is present (no silent deviation from
     the output contract).
"""

import re

REQUIRED_SECTIONS = ["EXECUTIVE VERDICT", "THEMES", "APPENDIX"]

# Source event IDs are 32-char hex hashes (e.g. d783783878a58a941f910f824fd9dcd3),
# not evt_-prefixed strings. Matched as bare hex tokens of at least 16 chars
# to avoid false-positives on shorter incidental hex-looking substrings.
EVENT_ID_PATTERN = re.compile(r"\b[a-f0-9]{16,}\b")



def validate_evidence_fidelity(content: str, assessments: list[dict]) -> list[str]:
    errors = []
    for a in assessments:
        evidence = a.get("evidence") or []
        aid = a["assessment_id"]
        # Scope to the single line/bullet for this assessment, not the
        # rest of the document -- avoids bleeding into the next entry.
        pattern = rf"{re.escape(aid)}[^\n]*?Evidence:\s*none\b"
        if evidence and re.search(pattern, content):
            errors.append(f"{aid}: non-empty evidence ({len(evidence)} items) rendered as 'none'")
    return errors

def validate_report(
    report_text: str,
    valid_event_ids: set,
    assessments: list[dict],
) -> tuple[bool, list[str]]:

    errors = []

    cited_ids = set(EVENT_ID_PATTERN.findall(report_text))
    unknown = cited_ids - valid_event_ids
    if unknown:
        errors.append(f"Citations not present in source data: {sorted(unknown)}")

    # Catch the opposite failure too: a report with zero citations at all
    # is not "validated," it's just uncited — this used to pass silently
    # when the old regex matched nothing.
    if not cited_ids:
        errors.append("No citations found in report text — cannot verify traceability.")

    for section in REQUIRED_SECTIONS:
        if section not in report_text:
            errors.append(f"Missing required section: {section}")

    if "TREND" in report_text.upper():
        errors.append(
            "Output references a trend/benchmark not supported in this "
            "version — model likely fabricated a comparison."
        )

    # Reject raw JSON/code-fence pass-through — actions must be rendered
    # as prose per the output contract, not dumped as structured data.
    if "```" in report_text or re.search(r'"urgency"\s*:', report_text):
        errors.append(
            "Output contains raw JSON/code blocks instead of synthesized "
            "prose for recommended actions."
        )
    errors.extend(validate_evidence_fidelity(report_text, assessments))

    return (len(errors) == 0, errors)