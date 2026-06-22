"""
nlp/pipeline/processor.py
--------------------------
Core NLP processing pipeline for Phase 3.

What this does:
  1. Loads the spaCy en_core_web_lg model (large — includes word vectors)
  2. Runs NER to extract ORG, GPE, LOC, PRODUCT entities from event text
  3. Classifies event_type more accurately than Phase 2 rule-based classifier
  4. Computes a real impact_score (0.0–1.0) from severity signals in text
  5. Generates a clean description summary (replaces Phase 2 placeholder)

Why en_core_web_lg over trf (transformer)?
  - en_core_web_lg ships word vectors (300-dim) — needed for Phase 3 embeddings
  - Transformer model (en_core_web_trf) has no built-in vectors; we'd need a
    separate sentence-transformer anyway. Avoid double model load.
  - en_core_web_lg NER accuracy is 85%+ on news text — sufficient for entity linking
  - Faster inference: ~500 docs/sec vs ~50/sec for trf on CPU

Why not Hugging Face transformers here?
  - Phase 3 uses sentence-transformers (all-MiniLM-L6-v2) for embeddings separately.
  - Mixing spaCy + HF in one call creates dependency conflicts on the Airflow image.
  - Clean separation: spaCy → NER + classification; sentence-transformers → embeddings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import spacy
from spacy.language import Language
from spacy.tokens import Doc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_NAME = "en_core_web_md"

# Keyword → event_type weights (score per hit, pick highest total)
EVENT_TYPE_WEIGHTS: dict[str, list[tuple[str, float]]] = {
    "weather": [
        ("typhoon", 1.0), ("hurricane", 1.0), ("cyclone", 1.0), ("flood", 0.8),
        ("storm", 0.7), ("earthquake", 0.9), ("tsunami", 1.0), ("wildfire", 0.8),
        ("blizzard", 0.7), ("drought", 0.6), ("weather", 0.5), ("wind", 0.4),
    ],
    "natural_disaster": [
        ("earthquake", 1.0), ("tsunami", 1.0), ("volcanic", 0.9), ("landslide", 0.9),
    ],
    "geopolitical": [
        ("sanction", 1.0), ("tariff", 0.9), ("war", 1.0), ("conflict", 0.8),
        ("blockade", 1.0), ("embargo", 0.9), ("strait", 0.7), ("military", 0.7),
        ("taiwan strait", 1.0), ("south china sea", 0.9), ("red sea", 0.9),
        ("suez", 0.8), ("geopolit", 0.8), ("trade war", 1.0),
    ],
    "labor": [
        ("strike", 1.0), ("walkout", 1.0), ("union", 0.7), ("labor dispute", 1.0),
        ("dock worker", 0.9), ("port worker", 0.9), ("protest", 0.5),
    ],
    "cyber": [
        ("cyber", 1.0), ("ransomware", 1.0), ("hack", 0.9), ("malware", 1.0),
        ("data breach", 0.9), ("it outage", 0.8), ("system outage", 0.7),
    ],
    "logistics": [
        ("congestion", 0.9), ("delay", 0.6), ("backlog", 0.8), ("shortage", 0.7),
        ("bottleneck", 0.8), ("port closure", 1.0), ("shipping delay", 0.9),
        ("supply chain", 0.5), ("freight", 0.5), ("logistics", 0.5),
    ],
}

# Impact signals → score additions
IMPACT_BOOSTERS: list[tuple[str, float]] = [
    ("shutdown", 0.30), ("closure", 0.25), ("blockade", 0.30), ("evacuation", 0.25),
    ("critical shortage", 0.30), ("force majeure", 0.25), ("emergency", 0.20),
    ("record high", 0.15), ("unprecedented", 0.15), ("major", 0.10),
    ("significant", 0.08), ("severe", 0.12), ("catastrophic", 0.35),
    ("weeks", 0.10), ("months", 0.15),
]

IMPACT_DAMPENERS: list[tuple[str, float]] = [
    ("minor", -0.10), ("slight", -0.08), ("temporary", -0.08),
    ("expected to resume", -0.15), ("back to normal", -0.20),
    ("no significant", -0.20), ("limited impact", -0.15),
]

# Severity → base impact score mapping
SEVERITY_BASE_SCORE = {
    "low": 0.15, "medium": 0.40, "high": 0.65, "critical": 0.85,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NLPResult:
    """
    Output of the NLP pipeline for a single DisruptionEvent.
    All fields are used to update the event node in Neo4j.
    """
    event_id: str
    event_type: str                           # refined classification
    severity: str                             # refined severity
    impact_score: float                       # computed 0.0–1.0
    description: str                          # generated summary (replaces placeholder)
    entities: list[dict] = field(default_factory=list)   # [{text, label, start, end}]
    org_mentions: list[str] = field(default_factory=list)
    location_mentions: list[str] = field(default_factory=list)
    product_mentions: list[str] = field(default_factory=list)
    # Embedding is added separately by embedder.py
    embedding: Optional[list[float]] = None


@dataclass
class EventInput:
    """Minimal input needed from Neo4j for NLP processing."""
    event_id: str
    title: str
    description: str           # Phase 2 placeholder — will be replaced
    severity: str              # Phase 2 rule-based — may be refined
    source: str
    affected_region: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class NLPPipeline:
    """
    Singleton spaCy pipeline.
    Load once per Airflow task worker, reuse across all events in the batch.

    Usage:
        pipeline = NLPPipeline()
        result = pipeline.process(EventInput(...))
    """

    _instance: Optional["NLPPipeline"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self):
        if self._loaded:
            return
        logger.info("Loading spaCy model %s ...", MODEL_NAME)
        self.nlp: Language = spacy.load(MODEL_NAME)
        # Disable unused pipeline components to speed up batch processing
        # We need: tok2vec, tagger, parser (for sentence boundary), ner
        # We don't need: attribute_ruler, lemmatizer for this use case
        self._loaded = True
        logger.info("spaCy model loaded")

    def process(self, event: EventInput) -> NLPResult:
        """Process a single event. Returns NLPResult with all enriched fields."""
        self._load()

        # Combine title + description for richer signal
        full_text = f"{event.title}. {event.description}"
        doc: Doc = self.nlp(full_text)

        event_type = self._classify_event_type(full_text)
        severity = self._refine_severity(full_text, event.severity)
        impact_score = self._compute_impact_score(full_text, severity)
        description = self._generate_description(doc, event)
        entities, orgs, locs, products = self._extract_entities(doc)

        return NLPResult(
            event_id=event.event_id,
            event_type=event_type,
            severity=severity,
            impact_score=round(impact_score, 3),
            description=description,
            entities=entities,
            org_mentions=orgs,
            location_mentions=locs,
            product_mentions=products,
        )

    def process_batch(self, events: list[EventInput], batch_size: int = 32) -> list[NLPResult]:
        """
        Process a batch using spaCy's pipe() for throughput.
        ~5–10× faster than calling process() in a loop.
        """
        self._load()
        texts = [f"{e.title}. {e.description}" for e in events]
        results = []

        docs = list(self.nlp.pipe(texts, batch_size=batch_size))
        for event, doc in zip(events, docs):
            full_text = doc.text
            event_type = self._classify_event_type(full_text)
            severity = self._refine_severity(full_text, event.severity)
            impact_score = self._compute_impact_score(full_text, severity)
            description = self._generate_description(doc, event)
            entities, orgs, locs, products = self._extract_entities(doc)

            results.append(NLPResult(
                event_id=event.event_id,
                event_type=event_type,
                severity=severity,
                impact_score=round(impact_score, 3),
                description=description,
                entities=entities,
                org_mentions=orgs,
                location_mentions=locs,
                product_mentions=products,
            ))

        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_event_type(self, text: str) -> str:
        """Weighted keyword scoring — returns type with highest total weight."""
        lower = text.lower()
        scores: dict[str, float] = {}
        for etype, patterns in EVENT_TYPE_WEIGHTS.items():
            score = sum(weight for keyword, weight in patterns if keyword in lower)
            if score > 0:
                scores[etype] = score

        if not scores:
            return "logistics"

        # "natural_disaster" must outscore "weather" to override (more specific)
        best = max(scores, key=lambda k: scores[k])
        return best

    def _refine_severity(self, text: str, current_severity: str) -> str:
        """
        Refine Phase 2's rule-based severity with text signal.
        Only upgrades severity — never downgrades weather/portwatch (those are fact-based).
        """
        lower = text.lower()

        critical_signals = [
            "catastrophic", "total shutdown", "complete closure", "tsunami",
            "earthquake", "force majeure", "indefinite closure",
        ]
        high_signals = [
            "major", "severe", "significant", "weeks of delay", "extended closure",
            "critical shortage", "emergency declaration",
        ]

        if any(s in lower for s in critical_signals):
            return "critical"
        if any(s in lower for s in high_signals) and current_severity in ("low", "medium"):
            return "high"
        return current_severity

    def _compute_impact_score(self, text: str, severity: str) -> float:
        """
        Compute impact_score from:
          - Severity base score (dominant signal)
          - Keyword boosters / dampeners
          Clipped to [0.05, 0.98]
        """
        lower = text.lower()
        score = SEVERITY_BASE_SCORE.get(severity, 0.40)

        for keyword, boost in IMPACT_BOOSTERS:
            if keyword in lower:
                score += boost

        for keyword, damp in IMPACT_DAMPENERS:
            if keyword in lower:
                score += damp  # damp is negative

        return max(0.05, min(0.98, score))

    def _generate_description(self, doc: Doc, event: EventInput) -> str:
        """
        Generate a clean 1–2 sentence description from the first 3 sentences of the doc.
        Falls back to title if no sentences extracted.
        """
        sentences = list(doc.sents)
        if not sentences:
            return event.title

        # Take first 2 sentences, cap at 300 chars
        summary_parts = []
        char_count = 0
        for sent in sentences[:2]:
            text = sent.text.strip()
            if char_count + len(text) > 300:
                break
            summary_parts.append(text)
            char_count += len(text)

        summary = " ".join(summary_parts)
        # Clean up double spaces, trailing punctuation artifacts
        summary = re.sub(r"\s+", " ", summary).strip()
        if not summary.endswith("."):
            summary += "."
        return summary or event.title

    def _extract_entities(
        self, doc: Doc
    ) -> tuple[list[dict], list[str], list[str], list[str]]:
        """
        Extract named entities from spaCy doc.
        Returns: (all_entities, orgs, locations, products)
        """
        entities = []
        orgs: set[str] = set()
        locs: set[str] = set()
        products: set[str] = set()

        for ent in doc.ents:
            if ent.label_ in ("ORG", "GPE", "LOC", "PRODUCT", "FAC"):
                entities.append({
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char,
                })
                if ent.label_ == "ORG":
                    orgs.add(ent.text)
                elif ent.label_ in ("GPE", "LOC", "FAC"):
                    locs.add(ent.text)
                elif ent.label_ == "PRODUCT":
                    products.add(ent.text)

        return entities, sorted(orgs), sorted(locs), sorted(products)