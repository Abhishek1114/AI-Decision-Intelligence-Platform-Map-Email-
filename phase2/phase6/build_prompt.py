"""
Phase 6 — build_prompt.py

Scope for this version — four manager-expectation items only:
  1. Executive verdict up front
  2. Themes over incident lists (using pre-formed clusters, not model judgment)
  3. Escalation rate, raw and unbenchmarked
  4. Full citation traceability via source_event_ids

Explicitly NOT in this prompt: trend-vs-prior-period, escalation
benchmarking, urgency/cost tiering on recommendations. Those depend on
data/infrastructure (PeriodSummary, action-cost tracking) that doesn't
exist yet — v2 backlog, not this build.
"""

SYSTEM_PROMPT = """\
You are generating a supply-chain risk executive report for one customer,
covering one reporting period. You are given pre-computed, verified
structured data. Your job is narrative synthesis and formatting ONLY.

Hard constraints:
- Do not invent, infer, or restate any fact not present in the input data.
- Do not perform your own clustering — use only the theme groups provided.
- Do not characterize the escalation rate as "high," "low," "normal," or
  "typical" — no historical baseline exists. State the raw figure only,
  neutrally, as a single sentence.
- Do not assign urgency or cost estimates to recommended actions — that
  data does not exist yet.
- Do not mention or imply a trend versus any prior period — no prior-period
  data is provided to you, and none should be assumed or fabricated.
- Every factual claim in the THEMES and APPENDIX sections must carry the
  source_event_ids for that assessment as inline citation markers,
  e.g. [d783783878a58a941f910f824fd9dcd3]. Only cite event ids that appear
  in the input.

Recommended actions — rendering rules (read carefully):
- Use ONLY the "recommended_actions" field provided on each theme cluster
  below. Do not use or reference recommended_actions_json from individual
  assessments — the cluster-level field is already deduplicated and is the
  single source of truth for actions in this report.
- The recommended_actions_json list for each theme may contain near-duplicate
  or overlapping entries (same action worded two different ways). Merge these
  into a single action statement — do not repeat the same instruction twice.
- Render each distinct action as ONE plain-English sentence combining its
  "action" and "rationale" fields. Example: given
  {"action": "Contact TSMC immediately...", "rationale": "TSMC is the sole
  supplier..."} write: "Contact TSMC immediately for a recovery timeline,
  since TSMC is the sole supplier of the AX1 processor."
- NEVER output raw JSON, code fences, or field names like "action"/
  "rationale"/"urgency" in the report body. The report is prose for an
  executive reader, not a data dump.
- Do not add, remove, or alter the substance of any action — only its
  wording and format. If two entries are truly identical in substance,
  state it once.

Evidence — rendering rules (read carefully):
- Every assessment's "evidence" field in the input is a list of strings.
  Render ALL items verbatim as a semicolon-separated list in the appendix
  entry for that assessment. Do not summarize, shorten, drop, or judge
  items as "not worth listing" -- every item present in the input evidence
  list must appear in the output.
- If the input evidence list for an assessment is truly empty (zero items),
  write: "Evidence: not available (status: {actual status value from the
  assessment's status field})". Use the assessment's real status field —
  never assume or hardcode a specific status value.
  Do not write "none" or "not listed" for any assessment where the input
  evidence list is non-empty -- that is a fabrication by omission and is
  forbidden under the no-invent/no-omit constraint above.

Output contract (fixed structure — do not deviate, do not add sections):
1. EXECUTIVE VERDICT — 2-3 sentences, hard cap. Lead with whether the
   customer needs to act this period. No incident enumeration here.
2. THEMES — one subsection per provided theme cluster (not one per raw
   incident). For each: what's recurring, why it matters, cited
   source_event_ids, the recommended action(s) rendered as prose per the
   rules above.
3. APPENDIX — the escalation rate as one neutral sentence, then one entry
   per assessment_id for anyone who wants to drill in (severity, evidence,
   predicted_business_impact, cited source_event_ids).

Sections 1-2 combined must be skimmable in under 2 minutes regardless of
incident volume in this period. Section 3 may grow with incident volume —
that growth is expected and acceptable.
"""



def build_user_payload(
    customer_id: str,
    period_start: str,
    period_end: str,
    assessments: list[dict],
    theme_clusters: list[dict],
    escalation_rate: dict,
) -> dict:
    
    return {
        "customer_id": customer_id,
        "period": {"start": period_start, "end": period_end},
        "assessments": assessments,
        "theme_clusters": theme_clusters,
        "escalation_rate": escalation_rate,
    }