"""
ingestion/gdelt/fetcher.py
--------------------------
Fetches supply-chain-relevant articles from the GDELT 2.0 GKG (Global Knowledge Graph)
and the GDELT DOC 2.0 Article Search API.

Why GDELT Doc API over GKG CSV dumps?
  - GKG CSV dumps are 500 MB+ every 15 min — too heavy for an Airflow task.
  - Doc API returns JSON, supports theme/keyword filters, and keeps payloads small.
  - Free, no API key required.

Output: List[GDELTArticle]  →  validated Pydantic models ready for NLP (Phase 3)
        and DisruptionEventNode upsert (Phase 2 DAG).
"""
from __future__ import annotations
from airflow.utils import timeout

import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GDELT_DOC_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

# Supply-chain relevant GDELT themes (subset — extend as needed)
# Full theme list: http://data.gdeltproject.org/api/v2/guides/GDELT-GKGCATEGORIES.TXT
SUPPLY_CHAIN_THEMES = [
    "TRADE",
    "ECON_TRADE",
#    "ENV_CLIMATECHANGE",
#   "ENV_NATURALRESOURCE",
#   "TAX_FREETRADEAGREEMENT",
    "MARITIME",
    "LOGISTICS",
#    "WB_696_TRANSPORT",
#    "MANMADE_DISASTER_IMPLIED",
#    "NATURAL_DISASTER",
#    "STRIKE",                      # labor
#    "CRISISLEX_CRISISLEXREC",
]

# Keywords injected into the query alongside themes for tighter relevance
SUPPLY_CHAIN_KEYWORDS = [
    "supply chain",
    "port congestion"
]

MAX_RECORDS = 10  # GDELT Doc API hard max per request


# ---------------------------------------------------------------------------
# Pydantic raw model — GDELT article as fetched (pre-NLP)
# ---------------------------------------------------------------------------

class GDELTArticle(BaseModel):
    """
    Raw article fetched from GDELT Doc API.
    Phase 3 NLP will classify event_type, extract entities, and compute impact_score.
    """

    article_id: str = Field(description="SHA-256 of URL — stable dedup key")
    title: str
    url: str
    source_domain: str
    published_at: datetime
    seendate: str                          # raw GDELT format: YYYYMMDDTHHMMSSZ
    language: str = "English"
    themes: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    tone: Optional[float] = None           # GDELT sentiment: negative = bad news
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Phase 2 signals (lightweight, no LLM) —— set by classifier.py
    raw_event_type: Optional[str] = None   # "geopolitical"|"labor"|"logistics"|etc.
    affected_region_hint: Optional[str] = None  # region_id best-guess from location field

    @field_validator("published_at", mode="before")
    @classmethod
    def parse_gdelt_date(cls, v):
        if isinstance(v, str):
            # GDELT seendate: "20240815T120000Z"  or  "20240815120000"
            for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    dt = datetime.strptime(v, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            raise ValueError(f"Cannot parse GDELT date: {v!r}")
        return v


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class GDELTFetcher:
    """
    Wraps the GDELT DOC 2.0 Article Search API.

    Usage:
        fetcher = GDELTFetcher()
        articles = fetcher.fetch(timespan="LAST24H")
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SupplyChainMonitor/1.0"})

    def _build_query(self) -> str:
        keyword_part = " OR ".join(f'"{kw}"' for kw in SUPPLY_CHAIN_KEYWORDS)
        return keyword_part

    def fetch(
        self,
        timespan: str = "LAST24H",    # GDELT timespan: "LAST24H", "LAST7DAYS", etc.
        max_records: int = MAX_RECORDS,
        mode: str = "ArtList",
    ) -> list[GDELTArticle]:
        """
        Fetch articles from GDELT Doc API.

        Args:
            timespan:    GDELT timespan string — "LAST24H" for Airflow daily runs
            max_records: Cap on results (max 250 per GDELT's limit)
            mode:        "ArtList" for article list; "TimelineVol" for volume trends

        Returns:
            List of validated GDELTArticle models
        """
        params = {
            "query": self._build_query(),
            "mode": mode,
            "maxrecords": min(max_records, MAX_RECORDS),
            "timespan": timespan,
            "format": "json",
            "sort": "DateDesc",
        }

        logger.info("Fetching GDELT articles: timespan=%s, maxrecords=%d", timespan, max_records)

        try:

            for attempt in range(5):
                resp = self.session.get(
                    GDELT_DOC_BASE,
                    params=params,
                    timeout=self.timeout
                )

                if resp.status_code != 429:
                    resp.raise_for_status()
                    break

                wait = 2 ** attempt
                logger.warning(
                    "GDELT rate limited. Sleeping %s sec",
                    wait
                )
                time.sleep(wait)
            else:
                logger.warning(
                    "GDELT unavailable due to rate limiting. Returning empty result."
                )
                return []
        except requests.RequestException as exc:
            logger.error("GDELT API request failed: %s", exc)
            raise
        
        logger.info("Status=%s", resp.status_code)
        logger.info("Content-Type=%s", resp.headers.get("Content-Type"))
        logger.info("Response=%s", resp.text[:500])

        content_type = resp.headers.get("Content-Type", "")

        if "application/json" not in content_type:
            logger.warning(
                "GDELT returned non-JSON response: %s",
                resp.text[:500]
            )
            return []

        try:
            logger.info("Response=%s", resp.text[:500])
            data = resp.json()
        except ValueError:
            logger.warning(
                "Invalid JSON from GDELT: %s",
                resp.text[:500]
            )
            return []
        raw_articles = data.get("articles", [])

        if not raw_articles:
            logger.warning("GDELT returned 0 articles for timespan=%s", timespan)
            return []

        articles: list[GDELTArticle] = []
        for raw in raw_articles:
            try:
                article = self._parse_article(raw)
                articles.append(article)
            except Exception as exc:
                logger.debug("Skipping malformed GDELT article: %s — %s", raw.get("url"), exc)

        logger.info("Parsed %d / %d GDELT articles", len(articles), len(raw_articles))
        return articles

    def _parse_article(self, raw: dict) -> GDELTArticle:
        url = raw.get("url", "")
        article_id = hashlib.sha256(url.encode()).hexdigest()[:16]

        seendate = raw.get("seendate", "")

        return GDELTArticle(
            article_id=article_id,
            title=raw.get("title", ""),
            url=url,
            source_domain=raw.get("domain", ""),
            published_at=seendate or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            seendate=seendate,
            language=raw.get("language", "English"),
        )

    def fetch_by_keyword(self, keyword: str, timespan: str = "LAST24H") -> list[GDELTArticle]:
        """Convenience method for single-keyword targeted fetch (e.g. 'Taiwan Strait')."""
        params = {
            "query": f'"{keyword}"',
            "mode": "ArtList",
            "maxrecords": 50,
            "timespan": timespan,
            "format": "json",
            "sort": "DateDesc",
        }
        try:

            for attempt in range(5):

                resp = self.session.get(
                    GDELT_DOC_BASE,
                    params=params,
                    timeout=self.timeout
                )

                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("GDELT rate limited. Sleeping %s sec", wait)
                    time.sleep(wait)
                    continue

                if "Please limit requests" in resp.text:
                    wait = 2 ** attempt
                    logger.warning("GDELT text rate limit. Sleeping %s sec", wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                break
            else:
                logger.warning("GDELT unavailable. Returning empty list.")
                return []
            raw_articles = resp.json().get("articles", [])
            return [self._parse_article(r) for r in raw_articles]
        except Exception as exc:
            logger.error("GDELT keyword fetch failed for %r: %s", keyword, exc)
            return []