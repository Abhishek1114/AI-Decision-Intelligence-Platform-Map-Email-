import spacy
from sentence_transformers import SentenceTransformer, util
from rapidfuzz import fuzz

import re
from html import unescape

from .config import (
    SPACY_MODEL, EMBEDDING_MODEL, FUZZY_MATCH_THRESHOLD,
    SEMANTIC_MATCH_THRESHOLD, RELEVANT_ENT_TYPES,
)

# Module-level load — once per worker process
_nlp = spacy.load(SPACY_MODEL)
_embedder = SentenceTransformer(EMBEDDING_MODEL)



def clean_text(raw_text: str) -> str:
    """Strip HTML tags/entities from event descriptions before NER.
    RSS-sourced events often contain <a href=...>, &nbsp;, <font> tags
    that spaCy mis-tags as ORG entities (e.g. 'href="https://news.google.com')."""
    if not raw_text:
        return ""
    # Remove HTML tags
    no_tags = re.sub(r"<[^>]+>", " ", raw_text)
    # Decode HTML entities (&nbsp; etc.)
    decoded = unescape(no_tags)
    # Collapse whitespace left behind by tag removal
    return re.sub(r"\s+", " ", decoded).strip()

def extract_entities(text: str) -> list[dict]:
    cleaned  = clean_text(text)
    doc = _nlp(cleaned)
    return [{"text": ent.text, "label": ent.label_} for ent in doc.ents if ent.label_ in RELEVANT_ENT_TYPES and len(ent.text.strip()) >= 3]


def link_entity_to_supplier(entity_text: str, known_suppliers: list[dict]) -> dict | None:
    if not known_suppliers:
        return None

    best_fuzzy = max(
        known_suppliers,
        key=lambda s: fuzz.token_sort_ratio(entity_text.lower(), s["name"].lower()),
    )
    fuzzy_score = fuzz.token_sort_ratio(entity_text.lower(), best_fuzzy["name"].lower())
    if fuzzy_score >= FUZZY_MATCH_THRESHOLD:
        return {"supplier_id": best_fuzzy["supplier_id"], "confidence": fuzzy_score / 100, "method": "fuzzy"}

    entity_emb = _embedder.encode(entity_text, convert_to_tensor=True)
    supplier_names = [s["name"] for s in known_suppliers]
    supplier_embs = _embedder.encode(supplier_names, convert_to_tensor=True)
    scores = util.cos_sim(entity_emb, supplier_embs)[0]
    best_idx = int(scores.argmax())
    best_score = float(scores[best_idx])

    if best_score >= SEMANTIC_MATCH_THRESHOLD:
        return {"supplier_id": known_suppliers[best_idx]["supplier_id"], "confidence": best_score, "method": "semantic"}

    return None