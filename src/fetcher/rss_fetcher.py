"""RSS feed fetcher with concurrent source support and per-source reporting."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import httpx
from loguru import logger

from src.models import NewsItem
from src.utils.redact import redact

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def fetch_single(name: str, url: str, timeout: int = 15) -> list[NewsItem]:
    """Fetch and parse a single RSS feed. Returns empty list on failure."""
    try:
        r = httpx.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
        r.raise_for_status()
    except Exception as e:
        logger.warning(
            redact(f"RSS HTTP fetch failed for {name} ({url}): {e}")
        )
        return []

    feed = feedparser.parse(r.text)

    if feed.bozo and not feed.entries:
        logger.warning(
            redact(f"RSS parse error for {name}: {feed.bozo_exception}")
        )
        return []

    if feed.bozo:
        logger.debug(
            redact(f"RSS parse warning for {name} (entries present): {feed.bozo_exception}")
        )

    items = []
    for entry in feed.entries:
        published_at = _entry_published_at(entry)

        items.append(NewsItem(
            title=getattr(entry, "title", "").strip(),
            url=getattr(entry, "link", ""),
            summary=getattr(entry, "summary", ""),
            source=name,
            published_at=published_at,
        ))

    logger.info(f"Fetched {len(items)} items from {name}")
    return items


def _entry_published_at(entry) -> "datetime":
    from datetime import datetime, timezone
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(
                *entry.published_parsed[:6], tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


def fetch_all(
    sources: list[dict], timeout: int = 15
) -> list[NewsItem]:
    """Fetch RSS feeds from all sources concurrently (legacy: no report)."""
    items, _ = fetch_all_with_report(sources, timeout=timeout)
    return items


def fetch_all_with_report(
    sources: list[dict], timeout: int = 15
) -> tuple[list[NewsItem], dict[str, dict]]:
    """Fetch RSS feeds and return ``(items, per_source_report)``.

    The report is ``{name: {"ok": bool, "count": int, "error": str|None,
    "duration_ms": int}}``. Use ``Metrics.source_reports`` to surface this
    in the daily ``METRICS`` log line.
    """
    all_items: list[NewsItem] = []
    reports: dict[str, dict] = {}

    def _run(name: str, url: str) -> tuple[str, list[NewsItem], dict]:
        start = time.perf_counter()
        try:
            items = fetch_single(name, url, timeout=timeout)
            elapsed = int((time.perf_counter() - start) * 1000)
            return name, items, {
                "ok": True,
                "count": len(items),
                "error": None,
                "duration_ms": elapsed,
            }
        except Exception as e:
            elapsed = int((time.perf_counter() - start) * 1000)
            return name, [], {
                "ok": False,
                "count": 0,
                "error": redact(str(e)),
                "duration_ms": elapsed,
            }

    with ThreadPoolExecutor(max_workers=min(len(sources), 8)) as executor:
        futures = [
            executor.submit(_run, s["name"], s["url"]) for s in sources
        ]
        for future in as_completed(futures):
            try:
                name, items, report = future.result()
                reports[name] = report
                all_items.extend(items)
            except Exception as e:
                logger.warning(redact(f"Unexpected error in fetch future: {e}"))

    logger.info(
        f"Total fetched: {len(all_items)} items from {len(sources)} sources"
    )
    return all_items, reports