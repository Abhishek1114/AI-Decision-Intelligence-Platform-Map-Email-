"""
Phase 5 — LangGraph agent.

Flow: check_duplicate -> [skip if duplicate] -> fetch_rag -> fetch_graph_context
      -> reason -> persist -> END

check_duplicate hashes the normalized event title and checks for an existing
AgentAssessment for this customer within the dedup window (see graph_tools.py).
If found, the paid Groq call is skipped entirely and the duplicate event is
just linked to the existing assessment — this is the TPM-budget protection
against upstream same-title GlobalEvent duplication.

persist both writes the AgentAssessment node (confirmed decision, not the idea
note's incorrect "CustomerImpact") and incrementally tags the event as
customer-relevant in ChromaDB, so future RAG queries for this customer get
progressively more customer-scoped over time.
"""
from __future__ import annotations
from typing import TypedDict, Optional
import logging

from neo4j import Driver
from groq import Groq
import chromadb

from phase2.phase5.models import AgentOutput, AgentRunStatus, ObservedFacts, AIPrediction
from phase2.phase5.tools.graph_tools import (
    build_observed_facts, compute_dedup_key, find_existing_assessment, link_duplicate_event,
)
from phase2.phase5.tools.rag_tools import query_similar_events, tag_event_for_customer
from phase2.phase5.tools.groq_client import call_groq_structured
from phase2.phase5.tools.persist import persist_agent_assessment
from phase2.phase5.tools.graph_tools import build_fallback_evidence

from langgraph.graph import StateGraph, END

logger = logging.getLogger("phase5.agent")

SYSTEM_PROMPT = """You are a supply chain risk analyst. You will be given OBSERVED FACTS
(pulled directly from a graph database — treat these as ground truth) about a customer's
products, components, and alternative suppliers, plus a description of a disruption event.

Your job: reason about business impact and produce ONLY the following JSON structure,
matching this schema exactly:
{schema}

Rules:
- severity and confidence are YOUR assessment, not restated facts.
- evidence[] must reference specific observed facts (component names, buffer days, etc.)
  that drove your reasoning — do not invent facts not present in the input.
- evidence[] must NOT be empty if any observed facts were used to justify severity,
  confidence, or recommended_actions. If you cited a metric anywhere in your reasoning
  (e.g. congestion_index, average wait time, buffer days, lead times), it must also
  appear in evidence[].
- Only return evidence: [] if observed facts were genuinely insufficient to reason about
  impact at all — in that case, also lower confidence accordingly.
- Do not restate inventory_buffer_days or lead_time_days as if they were your prediction;
  those are already known. Predict what happens GIVEN those numbers and this event.
- Do not calculate or invent dollar figures. Reference computed_exposure verbatim if 
  discussing financial impact.
- When a percentage or ratio appears anywhere in the input (e.g. in computed_exposure
  basis strings), you may reference that number ONLY together with its exact original
  label. Do not rename, reinterpret, or reattach it to a different concept (e.g. a
  precomputed "exposure" percentage must not be described as "coverage", and vice
  versa). If you are unsure what a number represents, quote the source field's
  wording verbatim instead of paraphrasing it.
- "Coverage" and "exposure" are not interchangeable: coverage = 
  alternative_supplier_volume / required_volume;exposure = 1 - coverage (unmet
  share). If you state one, do not derive or restate the other from raw quantities
-Do not calculate ratios or percentages yourself. If discussing coverage,
 either state the raw quantities (e.g., '2,000,000 of 4,500,000 units') without a derived 
 percentage, or reference a precomputed coverage/percentage field verbatim if one is provided in the input.
- Report event duration as a standalone fact only (e.g., "the event is expected to
  last 14 days"). Do not use it in any sentence containing words like "exceeds,"
  "surpasses," or "outlasts" applied to buffer or lead-time figures — that
  comparison is valid only between lead_time_days and inventory_buffer_days.
- Any number, ratio, or day-count must be identical everywhere it appears in your
  output. Before finalizing, check that evidence[], recommended_actions[], and any
  narrative fields do not restate the same fact with conflicting values.
"""


class AgentState(TypedDict):
    customer_id: str
    event_id: str
    supplier_id: str
    event_title: str
    event_text: str  # title + description, used for RAG query text
    dedup_key: Optional[str]
    is_duplicate: bool
    observed: Optional[ObservedFacts]
    similar_event_ids: list[str]
    rag_used_customer_scope: bool
    prediction: Optional[AIPrediction]
    status: AgentRunStatus
    raw_llm_output: Optional[str]
    assessment_id: Optional[str]


def build_graph(driver: Driver, chroma_client: chromadb.HttpClient, groq_client: Groq,redis_client=None):

    def check_duplicate(state: AgentState) -> AgentState:
        dedup_key = compute_dedup_key(state["event_title"])
        existing_id = find_existing_assessment(driver, dedup_key, state["customer_id"], state["supplier_id"])
        if existing_id:
            link_duplicate_event(driver, state["event_id"], existing_id)
            
            logger.info(
                f"Duplicate skipped: event={state['event_id']} customer={state['customer_id']} "
                f"-> existing assessment {existing_id}"
            )
            return {**state, "dedup_key": dedup_key, "is_duplicate": True,
                    "status": AgentRunStatus.DUPLICATE_SKIPPED, "assessment_id": existing_id}
        return {**state, "dedup_key": dedup_key, "is_duplicate": False}

    def route_after_duplicate_check(state: AgentState) -> str:
        return "skip" if state["is_duplicate"] else "continue"

    def fetch_rag(state: AgentState) -> AgentState:
        similar_ids, used_customer_scope = query_similar_events(
            chroma_client, state["event_text"], state["customer_id"], top_k=3
        )
        return {**state, "similar_event_ids": similar_ids,
                "rag_used_customer_scope": used_customer_scope}

    def fetch_graph_context(state: AgentState) -> AgentState:
        observed = build_observed_facts(
            driver, state["customer_id"], state["event_id"], state["supplier_id"],
            state["similar_event_ids"],
        )
        observed.rag_used_customer_scope = state["rag_used_customer_scope"]
        return {**state, "observed": observed}

    def reason(state: AgentState) -> AgentState:
        observed = state["observed"]
        assert observed is not None

        system_prompt = SYSTEM_PROMPT.format(schema=AIPrediction.model_json_schema())
        user_prompt = (
            f"Event: {state['event_text']}\n\n"
            f"Observed facts (JSON):\n{observed.model_dump_json(indent=2)}"
        )

        parsed, raw = call_groq_structured(
            groq_client, system_prompt, user_prompt, AIPrediction, max_retries=1
        )

        if parsed is None:
            fallback_evidence = build_fallback_evidence(observed)
            if fallback_evidence:
                # We still don't trust the model's severity/confidence/impact text
                # since it never validated — but we can at least surface graph
                # facts rather than nothing, and keep status honestly flagged.
                logger.error(
                    f"Agent run needs_review for customer={state['customer_id']} "
                    f"event={state['event_id']} — model never returned valid evidence. "
                    f"Backfilled {len(fallback_evidence)} fact(s) from graph for manual review."
                )
            else:
                logger.error(
                    f"Agent run needs_review for customer={state['customer_id']} "
                    f"event={state['event_id']}. No graph facts available either."
                )
            return {**state, "prediction": None, "status": AgentRunStatus.NEEDS_REVIEW,
                    "raw_llm_output": raw}

        return {**state, "prediction": parsed, "status": AgentRunStatus.OK,
                "raw_llm_output": None}

    def persist(state: AgentState) -> AgentState:
        output = AgentOutput(
            observed=state["observed"],
            prediction=state["prediction"],
            status=state["status"],
            raw_llm_output=state["raw_llm_output"],
        )
        assessment_id = persist_agent_assessment(driver, output, state["dedup_key"], state["supplier_id"],
        redis_client=redis_client)

        # Incremental customer-scoped RAG tagging — only for genuinely new
        # (non-duplicate) events, so we don't spam near-identical duplicate
        # text into the customer-scoped slice.
        severity = state["prediction"].severity.value if state["prediction"] else "unknown"
        tag_event_for_customer(
            chroma_client, state["event_id"], state["customer_id"], state["event_text"],
            severity=severity,
        )

        logger.info(f"Persisted AgentAssessment {assessment_id} (status={output.status.value})")
        return {**state, "assessment_id": assessment_id}

    graph = StateGraph(AgentState)
    graph.add_node("check_duplicate", check_duplicate)
    graph.add_node("fetch_rag", fetch_rag)
    graph.add_node("fetch_graph_context", fetch_graph_context)
    graph.add_node("reason", reason)
    graph.add_node("persist", persist)

    graph.set_entry_point("check_duplicate")
    graph.add_conditional_edges(
        "check_duplicate", route_after_duplicate_check,
        {"skip": END, "continue": "fetch_rag"},
    )
    graph.add_edge("fetch_rag", "fetch_graph_context")
    graph.add_edge("fetch_graph_context", "reason")
    graph.add_edge("reason", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


def run_agent_for_impact(
    driver: Driver,
    chroma_client: chromadb.HttpClient,
    groq_client: Groq,
    customer_id: str,
    event_id: str,
    supplier_id: str,
    event_title: str,
    event_text: str,
    redis_client=None,
) -> AgentOutput:
    compiled = build_graph(driver, chroma_client, groq_client,redis_client=redis_client)
    initial_state: AgentState = {
        "customer_id": customer_id,
        "event_id": event_id,
        "supplier_id": supplier_id,
        "event_title": event_title,
        "event_text": event_text,
        "dedup_key": None,
        "is_duplicate": False,
        "observed": None,
        "similar_event_ids": [],
        "rag_used_customer_scope": False,
        "prediction": None,
        "status": AgentRunStatus.OK,
        "raw_llm_output": None,
        "assessment_id": None,
    }
    final_state = compiled.invoke(initial_state)

    if final_state["is_duplicate"]:
        # No observed/prediction was computed — duplicate short-circuit.
        # Return a minimal AgentOutput referencing the existing assessment.
        return AgentOutput(
            observed=ObservedFacts(
                customer_id=customer_id, event_id=event_id,
                narrowing_method="none",
            ),
            prediction=None,
            status=AgentRunStatus.DUPLICATE_SKIPPED,
            assessment_id=final_state["assessment_id"],
        )

    return AgentOutput(
        observed=final_state["observed"],
        prediction=final_state["prediction"],
        status=final_state["status"],
        raw_llm_output=final_state["raw_llm_output"],
        assessment_id=final_state["assessment_id"],
    )