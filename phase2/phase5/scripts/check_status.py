"""
Phase 5 — Status-check script. One command, one event_id, full trace.

Answers: where is this event in the pipeline, and if it never produced an
AgentAssessment, which stage is it stuck at?

Usage (from inside the running consumer container):
    python -m phase2.phase5.scripts.check_status <event_id>

Or as a one-liner from the host:
    docker compose exec phase5_agent_consumer python -m phase2.phase5.scripts.check_status evt_a1b2c3
"""
from __future__ import annotations
import os
import sys
import json
from neo4j import GraphDatabase
import redis
import chromadb

from phase2.phase5.streaming.redis_stream import STREAM_NAME, CONSUMER_GROUP


def check_neo4j_event(driver, event_id: str) -> dict:
    query = """
    MATCH (e:GlobalEvent {event_id: $event_id})
    OPTIONAL MATCH (e)-[r:IMPACTS]->(c:Customer)
    RETURN e.title AS title, e.description AS description,
           collect({customer_id: c.customer_id, alert_triggered: r.alert_triggered,
                     supplier_id: r.supplier_id, severity: r.severity}) AS impacts
    """
    with driver.session() as session:
        record = session.run(query, event_id=event_id).single()
        if not record:
            return {"exists": False}
        return {
            "exists": True,
            "title": record["title"],
            "description": record["description"],
            "impacts": [i for i in record["impacts"] if i["customer_id"] is not None],
        }


def check_assessments(driver, event_id: str) -> list[dict]:
    query = """
        MATCH (a:AgentAssessment)
        WHERE $event_id IN a.source_event_ids
        RETURN a.assessment_id AS assessment_id, a.customer_id AS customer_id,
            a.supplier_id AS supplier_id, a.status AS status, a.severity AS severity,
            a.confidence AS confidence, a.narrowing_method AS narrowing_method,
            a.affected_product_ids AS affected_product_ids,
            a.source_event_ids AS source_event_ids, a.created_at AS created_at,
            a.updated_at AS updated_at, a.model_used AS model_used,
            a.predicted_business_impact AS predicted_business_impact,
            a.evidence AS evidence,
            a.recommended_actions_json AS recommended_actions_json,
            a.raw_llm_output AS raw_llm_output
        """
    with driver.session() as session:
        return [dict(r) for r in session.run(query, event_id=event_id)]


def check_redis(r: redis.Redis, event_id: str) -> dict:
    """Scans recent stream entries for this event_id — Streams aren't indexed
    by field value, so this is a linear scan capped at 1000 recent entries."""
    entries = r.xrange(STREAM_NAME, count=1000)
    matches = [(msg_id, fields) for msg_id, fields in entries if fields.get("event_id") == event_id]
    if not matches:
        return {"found_on_stream": False}

    pending = r.xpending_range(STREAM_NAME, CONSUMER_GROUP, min="-", max="+", count=1000)
    pending_ids = {p["message_id"] for p in pending}

    result = []
    for msg_id, fields in matches:
        result.append({
            "message_id": msg_id,
            "fields": fields,
            "still_pending": msg_id in pending_ids,
        })
    return {"found_on_stream": True, "entries": result}

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
    
def check_chroma(client: chromadb.HttpClient, event_id: str, customer_ids: list[str]) -> dict:
    collection = client.get_or_create_collection(name="global_events")
    result = {"global_tagged": False, "customer_tagged": {}}

    try:
        global_doc = collection.get(ids=[event_id])
        result["global_tagged"] = len(global_doc["ids"]) > 0
    except Exception:
        result["global_tagged"] = False

    for cid in customer_ids:
        doc_id = f"{event_id}::{cid}"
        try:
            doc = collection.get(ids=[doc_id])
            result["customer_tagged"][cid] = len(doc["ids"]) > 0
        except Exception:
            result["customer_tagged"][cid] = False

    return result


def main():
    if len(sys.argv) != 2:
        print("Usage: python -m phase2.phase5.scripts.check_status <event_id>")
        sys.exit(1)
    event_id = sys.argv[1]

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    )
    redis_client = redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        decode_responses=True,
    )
    chroma_client = chromadb.HttpClient(
        host=os.environ.get("CHROMADB_HOST", "chromadb"),
        port=int(os.environ.get("CHROMADB_PORT", 8000)),
    )

    print(f"\n{'='*60}\nSTATUS CHECK: {event_id}\n{'='*60}\n")

    # --- Neo4j: does the event and IMPACTS exist ---
    ne = check_neo4j_event(driver, event_id)
    print("[1] GlobalEvent + IMPACTS")
    if not ne["exists"]:
        print(f"    NOT FOUND — this event_id does not exist in Neo4j at all.")
        print(f"    -> Nothing downstream can work; check the ID or ingestion.")
    else:
        print(f"    title: {ne['title']}")
        if not ne["impacts"]:
            print("    No IMPACTS relationships — Phase 4 never matched this event to a customer.")
            print("    -> This event was never supposed to reach Phase 5.")
        for imp in ne["impacts"]:
            print(f"    -> customer={imp['customer_id']} alert_triggered={imp['alert_triggered']} "
                  f"supplier_id={imp['supplier_id']} severity={imp['severity']}")

    customer_ids = [i["customer_id"] for i in ne.get("impacts", [])]

    # --- Redis: did it ever reach the stream, is it stuck pending ---
    print("\n[2] Redis Stream")
    rs = check_redis(redis_client, event_id)
    if not rs["found_on_stream"]:
        print("    NOT on the stream (checked last 1000 entries).")
        print("    -> produce_alert() was never called for this event, or it's older")
        print("       than the 1000-entry scan window — check Phase 4's write path.")
    else:
        for entry in rs["entries"]:
            status = "STILL PENDING (not acked — handler may have crashed or is slow)" \
                if entry["still_pending"] else "acked (processed successfully)"
            print(f"    message_id={entry['message_id']} status: {status}")

    # --- Neo4j: AgentAssessment ---
    print("\n[3] AgentAssessment")
    assessments = check_assessments(driver, event_id)
    if not assessments:
        print("    NONE FOUND.")
        if rs["found_on_stream"] and not any(e["still_pending"] for e in rs.get("entries", [])):
            print("    -> Stream shows this was ACKED but no assessment exists.")
            print("       This means the handler ran without raising, but hit a")
            print("       duplicate_skipped short-circuit, OR persist() failed")
            print("       silently. Check consumer logs around this message_id.")
    else:
        for a in assessments:
            print(f"    model={a['model_used']} updated_at={a['updated_at']}")
            print(f"    predicted_business_impact: {a['predicted_business_impact']}")
            print(f"    evidence: {a['evidence']}")
            print(f"    recommended_actions: {a['recommended_actions_json']}")
            if a['status'] == 'needs_review':
                print(f"    raw_llm_output: {a['raw_llm_output']}")
            print(f"    assessment_id={a['assessment_id']} customer={a['customer_id']} "
                  f"supplier={a['supplier_id']} status={a['status']} severity={a['severity']} "
                  f"confidence={a['confidence']}")
            print(f"    narrowing={a['narrowing_method']} "
                  f"affected_products={a['affected_product_ids']}")
            print(f"    source_event_ids={a['source_event_ids']} (>1 means duplicates collapsed here)")

    print("\n[5] Manager alert preview")
    impacts_by_supplier = {i["supplier_id"]: i for i in ne.get("impacts", [])}
    for a in assessments:
            matching_impact = impacts_by_supplier.get(a["supplier_id"], {})
            print("\n" + format_manager_alert(matching_impact, a, ne["title"]))
            print("-" * 60)
    # --- ChromaDB tagging ---
    print("\n[4] ChromaDB RAG tagging")
    if customer_ids:
        cc = check_chroma(chroma_client, event_id, customer_ids)
        print(f"    global scope tagged: {cc['global_tagged']}")
        for cid, tagged in cc["customer_tagged"].items():
            print(f"    customer scope tagged for {cid}: {tagged}")
    else:
        print("    Skipped — no customer_id known for this event (no IMPACTS found above).")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()