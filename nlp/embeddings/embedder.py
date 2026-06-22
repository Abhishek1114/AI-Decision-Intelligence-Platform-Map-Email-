"""
nlp/embeddings/embedder.py
---------------------------
Generates sentence embeddings for DisruptionEvent nodes using
sentence-transformers (all-MiniLM-L6-v2).

Why all-MiniLM-L6-v2?
  - 384-dim embeddings (vs 768 for larger models) — fast and small enough for CPU
  - Optimized for semantic similarity — exactly what Phase 4 RAG tool needs
  - 5× faster than paraphrase-mpnet-base-v2 with ~95% of the quality
  - Ships in the sentence-transformers package with no HuggingFace API calls

What embeddings are used for (Phase 4):
  - Semantic dedup: cosine similarity > 0.92 → skip writing duplicate events
  - RAG retrieval: given a user query, find the most semantically similar events
  - Trend detection: cluster events by embedding proximity to detect outbreak patterns

Storage decision: embeddings are stored as a List<Float> property on
DisruptionEvent nodes in Neo4j. This avoids a separate vector store (Pinecone,
Weaviate) in Phase 3. Phase 4 will load embeddings from Neo4j and do in-memory
similarity search with numpy — sufficient for <10K events.
If scale grows beyond 50K events, migrate to a vector index (pgvector or Neo4j
Vector Index, available in Neo4j 5.11+).

Neo4j property: DisruptionEvent.embedding  List<Float> length=384
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
DEDUP_COSINE_THRESHOLD = 0.92   # events more similar than this are considered duplicates


class EventEmbedder:
    """
    Singleton sentence-transformer embedder.
    Load once per Airflow worker, reuse across the batch.

    Usage:
        embedder = EventEmbedder()
        vector = embedder.embed("Taiwan Strait tensions disrupt TSMC supply chain")
        vectors = embedder.embed_batch(["text1", "text2"])
    """

    _instance: Optional["EventEmbedder"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self):
        if self._loaded:
            return
        logger.info("Loading sentence-transformer model %s ...", MODEL_NAME)
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(MODEL_NAME)
        self._loaded = True
        logger.info("Sentence-transformer model loaded (dim=%d)", EMBEDDING_DIM)

    def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns list of 384 floats."""
        self._load()
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """
        Embed multiple texts efficiently.
        Returns list of 384-dim float vectors in the same order as input.
        """
        self._load()
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """
        Cosine similarity between two vectors.
        Since encode() normalizes embeddings, this is just the dot product.
        """
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        return float(np.dot(va, vb))

    def is_duplicate(self, vec_a: list[float], vec_b: list[float]) -> bool:
        """True if two event embeddings are above the dedup threshold."""
        return self.cosine_similarity(vec_a, vec_b) >= DEDUP_COSINE_THRESHOLD

    def find_most_similar(
        self,
        query_vec: list[float],
        candidate_vecs: list[list[float]],
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        """
        Find top-k most similar vectors from candidates.
        Used by Phase 4 RAG tool to retrieve relevant events.

        Returns: list of (index, similarity_score) sorted by score descending
        """
        if not candidate_vecs:
            return []
        q = np.array(query_vec, dtype=np.float32)
        matrix = np.array(candidate_vecs, dtype=np.float32)
        scores = matrix @ q    # dot product (vectors are normalized)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices]


def build_embed_text(title: str, description: str, event_type: str, affected_region: str | None) -> str:
    """
    Construct the text string to embed for an event.
    Using title + event_type + region gives better clustering than title alone.
    """
    parts = [title]
    if event_type:
        parts.append(f"Type: {event_type}")
    if affected_region:
        parts.append(f"Region: {affected_region}")
    if description and description != title:
        # Include first sentence of description only
        first_sentence = description.split(".")[0]
        if len(first_sentence) > 10:
            parts.append(first_sentence)
    return ". ".join(parts)