"""
Phase 5 — RAG tools backed by ChromaDB + all-MiniLM-L6-v2.

Backfill scope: Option A (confirmed) — the batch backfill covers ALL historical
GlobalEvent nodes, tagged scope="global". This gives broad corpus coverage from
day one but is NOT customer-specific.

Customer-specific similarity is added incrementally, not via a separate batch job:
every time the agent processes an event for a customer, that event gets tagged
scope="customer" + customer_id in this same collection (see tag_event_for_customer,
called from agent/graph.py's persist node). Over time this builds up a genuinely
customer-scoped corpus without needing to know customer relevance in advance.

query_similar_events() tries the customer-scoped slice first; if nothing has been
tagged for that customer yet (cold start), it falls back to the global slice.
Callers can check which happened via the returned `used_customer_scope` flag.
"""
from __future__ import annotations
import chromadb
from sentence_transformers import SentenceTransformer

COLLECTION_NAME = "global_events"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_chroma_client(host: str = "chromadb", port: int = 8000) -> chromadb.HttpClient:
    return chromadb.HttpClient(host=host, port=port)


def get_or_create_collection(client: chromadb.HttpClient):
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"embedding_model": EMBEDDING_MODEL},
    )


def backfill_all_events(driver, client: chromadb.HttpClient, batch_size: int = 200) -> int:
    """
    Option A backfill: every GlobalEvent node, tagged scope="global". Uses
    event_id as the Chroma document id so re-runs are idempotent (upsert).
    """
    collection = get_or_create_collection(client)
    embedder = get_embedder()

    query = """
    MATCH (e:GlobalEvent)
    RETURN e.event_id AS event_id, e.title AS title,
           e.description AS description, e.severity AS severity,
           e.category AS category, e.source_tier AS source_tier
    """

    total = 0
    with driver.session() as session:
        result = session.run(query)
        batch_ids, batch_texts, batch_meta = [], [], []

        for record in result:
            text = f"{record['title'] or ''}. {record['description'] or ''}".strip()
            if not text:
                continue
            batch_ids.append(record["event_id"])
            batch_texts.append(text)
            batch_meta.append({
                "scope": "global",
                "customer_id": "",  # Chroma metadata must be scalar; empty string, not None
                "severity": record["severity"] or "unknown",
                "category": record["category"] or "unknown",
                "source_tier": record["source_tier"] or "unknown",
            })

            if len(batch_ids) >= batch_size:
                _flush_batch(collection, embedder, batch_ids, batch_texts, batch_meta)
                total += len(batch_ids)
                batch_ids, batch_texts, batch_meta = [], [], []

        if batch_ids:
            _flush_batch(collection, embedder, batch_ids, batch_texts, batch_meta)
            total += len(batch_ids)

    return total


def _flush_batch(collection, embedder, ids, texts, metadatas):
    embeddings = embedder.encode(texts, show_progress_bar=False).tolist()
    collection.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def tag_event_for_customer(
    client: chromadb.HttpClient, event_id: str, customer_id: str, event_text: str,
    severity: str = "unknown", category: str = "unknown",
):
    """
    Incrementally tags a processed event as customer-relevant. Uses a distinct
    doc id (event_id::customer_id) so the same event can be tagged for multiple
    customers without overwriting the global entry or other customers' tags.
    Called from agent/graph.py's persist node after every successful (non-duplicate) run.
    """
    collection = get_or_create_collection(client)
    embedder = get_embedder()
    doc_id = f"{event_id}::{customer_id}"
    embedding = embedder.encode([event_text]).tolist()
    collection.upsert(
        ids=[doc_id],
        embeddings=embedding,
        documents=[event_text],
        metadatas=[{
            "scope": "customer",
            "customer_id": customer_id,
            "event_id": event_id,
            "severity": severity,
            "category": category,
        }],
    )


def query_similar_events(
    client: chromadb.HttpClient,
    event_text: str,
    customer_id: str,
    top_k: int = 3,
) -> tuple[list[str], bool]:
    """
    Returns (event_ids, used_customer_scope).

    Tries the customer-scoped slice first. If no customer-tagged events exist yet
    (cold start — common early on, since tagging is incremental), falls back to
    the global slice and reports used_customer_scope=False so callers know the
    result is not customer-specific.
    """
    collection = get_or_create_collection(client)
    embedder = get_embedder()
    query_embedding = embedder.encode([event_text]).tolist()

    customer_results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where={"$and": [{"scope": "customer"}, {"customer_id": customer_id}]},
    )
    customer_ids_found = customer_results["ids"][0] if customer_results["ids"] else []
    if customer_ids_found:
        # strip the "::customer_id" suffix back to a plain event_id
        return [doc_id.split("::")[0] for doc_id in customer_ids_found], True

    global_results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k,
        where={"scope": "global"},
    )
    global_ids_found = global_results["ids"][0] if global_results["ids"] else []
    return global_ids_found, False