# phase2/ingestion/sources/google_news.py
# Replace the existing fetch_google_news function with this

import feedparser
from datetime import datetime, timedelta, timezone
from typing import List

MAX_ARTICLE_AGE_DAYS = 30

SUPPLY_CHAIN_FEEDS = [
    "https://news.google.com/rss/search?q=supply+chain+disruption+when:30d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=factory+shutdown+manufacturing+when:30d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=port+congestion+shipping+delay+when:30d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=semiconductor+chip+shortage+when:30d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=export+ban+trade+sanctions+when:30d&hl=en-US&gl=US&ceid=US:en",
]


def fetch_google_news(max_per_feed: int = 20) -> List[dict]:
    """
    Parse Google News RSS feeds for supply chain relevant articles.
    Two layers of date filtering:
      1. when:7d in the query URL itself (Google-side, undocumented)
      2. Manual cutoff check below (defensive, always enforced)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    articles = []
    skipped_old = 0

    for feed_url in SUPPLY_CHAIN_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:max_per_feed]:
            published_str = entry.get("published", "")

            # Defensive check — drop anything older than 7 days
            # regardless of what when:7d returned
            article_date = _parse_rss_date(published_str)
            if article_date and article_date < cutoff:
                skipped_old += 1
                continue

            articles.append({
                "title":     entry.get("title", ""),
                "url":       entry.get("link", ""),
                "source":    entry.get("source", {}).get("title", "Google News"),
                "published": published_str,
                "summary":   entry.get("summary", ""),
            })

    print(f"[GoogleNews] Fetched {len(articles)} articles, "
          f"skipped {skipped_old} older than {MAX_ARTICLE_AGE_DAYS} days")
    return articles

def normalise_google_news(article: dict) -> dict:
    """
    Normalise a Google News RSS entry to our internal format.
    """
    title     = article.get("title", "Untitled")
    published = article.get("published", "")

    # RSS pubDate format: "Mon, 15 Mar 2024 10:00:00 GMT"
    try:
        dt = datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %Z")
        occurred_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        occurred_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "event_type":  _classify_event_type(title),
        "title":       title[:200],
        "description": f"{article.get('source', 'Google News')}: {title}. "
                       f"{article.get('summary', '')}",
        "country":     "Unknown",   # Phase 3 NLP will extract this
        "region":      None,
        "latitude":    None,
        "longitude":   None,
        "severity":    "medium",    # Phase 3 NLP will score this
        "source":      "gdelt",     # Keep enum value — avoids model change
        "source_url":  article.get("url", ""),
        "occurred_at": occurred_iso,
    }

def _classify_event_type(title: str) -> str:
    title_lower = title.lower()
    if any(w in title_lower for w in ["earthquake", "quake", "tremor"]):
        return "earthquake"
    if any(w in title_lower for w in ["flood", "typhoon", "hurricane", "cyclone"]):
        return "flood"
    if any(w in title_lower for w in ["strike", "labor", "worker protest"]):
        return "labor_strike"
    if any(w in title_lower for w in ["ban", "sanction", "tariff", "export control"]):
        return "export_ban"
    if any(w in title_lower for w in ["port", "shipping", "congestion", "freight"]):
        return "port_congestion"
    if any(w in title_lower for w in ["cyber", "hack", "ransomware"]):
        return "cyber"
    return "political"

def _parse_rss_date(published_str: str):
    """
    Parse RSS pubDate format into a timezone-aware datetime.
    Returns None if parsing fails — caller treats that as 'keep it'
    rather than silently dropping articles with bad date formats.
    """
    if not published_str:
        return None
    try:
        # RSS pubDate format: "Mon, 15 Mar 2024 10:00:00 GMT"
        dt = datetime.strptime(published_str, "%a, %d %b %Y %H:%M:%S %Z")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None