"""Free mode: collects today's news from RSS feeds, so Gemini needs no paid Google Search."""
from __future__ import annotations

import calendar
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote_plus

import feedparser
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
MAX_AGE_HOURS = 36
PER_SOURCE = 15
MAX_ITEMS = 80
MAX_READABLE = 20   # Gemini can open about 20 links per request (URL context)

# Starter sources for the built-in briefings. Lines are RSS feed URLs or Google News searches.
STARTER_SOURCES = {
    "business": [
        "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
        "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
        "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
        "https://www.livemint.com/rss/companies",
        "https://www.livemint.com/rss/economy",
        "https://www.business-standard.com/rss/home_page_top_stories.rss",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://techcrunch.com/feed/",
        "India startup funding",
    ],
    "stock-market": [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.livemint.com/rss/markets",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "Sensex Nifty today",
    ],
}


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published: float | None   # unix time
    summary: str
    readable: bool            # False for Google News links, which can't be opened directly


def parse_sources(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _feed_url(source: str) -> str:
    if source.startswith(("http://", "https://")):
        return source
    query = quote_plus(f"{source} when:1d")
    return f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"


def _clean(text: str, limit: int) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _fetch(source: str) -> list[NewsItem]:
    url = _feed_url(source)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    feed = feedparser.parse(resp.content)
    is_google = "news.google.com" in url
    default_source = _clean(feed.feed.get("title", ""), 60) or url.split("/")[2]
    cutoff = time.time() - MAX_AGE_HOURS * 3600
    items = []
    for entry in feed.entries:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        published = calendar.timegm(parsed) if parsed else None
        if published is not None and published < cutoff:
            continue
        title, link = _clean(entry.get("title", ""), 200), entry.get("link", "")
        if not title or not link.startswith(("http://", "https://")):
            continue
        source_name = default_source
        if is_google and entry.get("source", {}).get("title"):
            source_name = entry["source"]["title"]
            title = title.removesuffix(f" - {source_name}")
        items.append(NewsItem(title, link, source_name, published,
                              "" if is_google else _clean(entry.get("summary", ""), 300), not is_google))
        if len(items) >= PER_SOURCE:
            break
    return items


def collect(sources: list[str]) -> list[NewsItem]:
    """Recent news from all sources: newest first, duplicates removed."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(_fetch, sources))
    seen, items = set(), []
    for item in sorted((i for batch in batches for i in batch), key=lambda i: i.published or 0, reverse=True):
        key = re.sub(r"[^a-z0-9]", "", item.title.lower())[:60]
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items[:MAX_ITEMS]


def as_prompt(items: list[NewsItem], now: float | None = None) -> str:
    now = now or time.time()
    lines, readable = [], 0
    for n, item in enumerate(items, 1):
        age = f"{max(0, (now - item.published) / 3600):.0f}h ago" if item.published else "recent"
        can_open = item.readable and readable < MAX_READABLE
        readable += can_open
        lines.append(f"[{n}] {item.title} ({item.source}, {age})")
        if item.summary:
            lines.append(f"    {item.summary}")
        lines.append(f"    Link: {item.link}" + ("" if can_open else "  (headline only, don't open)"))
    return "\n".join(lines)
