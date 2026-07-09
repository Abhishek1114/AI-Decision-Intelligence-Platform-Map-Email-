"""
Phase 6 — generate_report.py

Orchestrator, called by the DAG once per customer per scheduled run.

Failure handling mirrors Phase 5's AIPrediction.evidence pattern exactly:
validate -> on failure, retry once with a tightened prompt (errors
appended) -> on second failure, persist anyway with status="needs_review"
and the raw output attached. Never silently drop a report.
"""

import logging

from neo4j import Session

from phase2.phase6.fetch_assessments import fetch_period_assessments
from phase2.phase6.cluster_themes import cluster_by_theme
from phase2.phase6.escalation import compute_escalation_rate
from phase2.phase6.build_prompt import SYSTEM_PROMPT, build_user_payload
from phase2.phase6.groq_report_client import generate_report_text, MODEL
from phase2.phase6.validate_output import validate_report
from phase2.phase6.persist_report import persist_report
from phase2.phase6.no_incident_report import build_no_incident_report

logger = logging.getLogger("phase6.generate_report")


def generate_customer_report(
    session: Session,
    customer_id: str,
    period_start: str,
    period_end: str,
) -> str:
    assessments = fetch_period_assessments(session, customer_id, period_start, period_end)

    if not assessments:
        content = build_no_incident_report(customer_id, period_start, period_end)
        report_id = persist_report(
            session,
            customer_id,
            period_start,
            period_end,
            content=content,
            status="ok",
            model_used="none",  # templated, no LLM call made — see no_incident_report.py
            escalation_rate={"rate": 0.0},
            theme_count=0,
            assessments=[],
        )
        logger.info("No assessments for %s in period; templated report %s", customer_id, report_id)
        return report_id

    clusters = cluster_by_theme(assessments)
    escalation = compute_escalation_rate(assessments)
    payload = build_user_payload(
        customer_id, period_start, period_end, assessments, clusters, escalation
    )
    valid_event_ids = {eid for a in assessments for eid in (a.get("source_event_ids") or [])}

    content = generate_report_text(SYSTEM_PROMPT, payload)
    ok, errors = validate_report(content, valid_event_ids, assessments)

    if not ok:
        logger.warning("Report validation failed for %s, retrying once: %s", customer_id, errors)
        tightened_prompt = (
            SYSTEM_PROMPT
            + f"\n\nYour previous attempt had the following errors, fix them exactly: {errors}"
        )
        content = generate_report_text(tightened_prompt, payload)
        ok, errors = validate_report(content, valid_event_ids,assessments)

    status = "ok" if ok else "needs_review"
    if not ok:
        logger.error(
            "Report for %s still failing validation after retry, persisting as needs_review: %s",
            customer_id, errors,
        )

    report_id = persist_report(
        session,
        customer_id,
        period_start,
        period_end,
        content=content,
        status=status,
        model_used=MODEL,
        escalation_rate=escalation,
        theme_count=len(clusters),
        assessments=assessments,
    )

    logger.info("Report %s persisted with status=%s", report_id, status)
    return report_id