"""RSS feed fetcher with concurrent source support and per-source reporting."""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urldefrag

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

FetchStatus = Literal["ok", "http_error", "parse_warning", "parse_error"]


@dataclass
class SourceFetchResult:
    """Outcome for one configured feed."""

    name: str
    status: FetchStatus
    items: list[NewsItem] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "parse_warning"}

    @property
    def count(self) -> int:
        return len(self.items)

    def as_report(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "count": self.count,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FetchBatch:
    """Items plus inspectable outcomes for every configured feed."""

    items: list[NewsItem] = field(default_factory=list)
    sources: list[SourceFetchResult] = field(default_factory=list)

    @property
    def reports(self) -> dict[str, dict]:
        return {source.name: source.as_report() for source in self.sources}


def fetch_single(name: str, url: str, timeout: int = 15) -> SourceFetchResult:
    """Fetch one RSS feed and retain whether it failed or was empty."""
    return _fetch_source(name, url, timeout)


def _fetch_source(name: str, url: str, timeout: int) -> SourceFetchResult:
    """Fetch one source while retaining its outcome for the batch report."""
    start = time.perf_counter()
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
        return SourceFetchResult(
            name=name,
            status="http_error",
            error=redact(str(e)),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    try:
        feed = feedparser.parse(r.text)
    except Exception as e:
        logger.warning(redact(f"RSS parse error for {name}: {e}"))
        return SourceFetchResult(
            name=name,
            status="parse_error",
            error=redact(str(e)),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    if feed.bozo and not feed.entries:
        logger.warning(
            redact(f"RSS parse error for {name}: {feed.bozo_exception}")
        )
        return SourceFetchResult(
            name=name,
            status="parse_error",
            error=redact(str(feed.bozo_exception)),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    if feed.bozo:
        logger.debug(
            redact(f"RSS parse warning for {name} (entries present): {feed.bozo_exception}")
        )

    items = []
    for entry in feed.entries:
        published_at = _entry_published_at(entry)
        title = getattr(entry, "title", "").strip()
        url = getattr(entry, "link", "")
        summary = getattr(entry, "summary", "")

        items.append(NewsItem(
            title=title,
            url=url,
            summary=summary,
            source=name,
            published_at=published_at,
            item_id=_entry_identity(name, entry, title, url, summary),
        ))

    logger.info(f"Fetched {len(items)} items from {name}")
    return SourceFetchResult(
        name=name,
        status="parse_warning" if feed.bozo else "ok",
        items=items,
        error=redact(str(feed.bozo_exception)) if feed.bozo else None,
        duration_ms=int((time.perf_counter() - start) * 1000),
    )


def _entry_published_at(entry) -> datetime | None:
    for field_name in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, field_name, None)
        if not parsed:
            continue
        try:
            return datetime(
                parsed[0],
                parsed[1],
                parsed[2],
                parsed[3],
                parsed[4],
                parsed[5],
                tzinfo=timezone.utc,
            )
        except (ValueError, TypeError):
            continue
    return None


def _entry_identity(name: str, entry, title: str, url: str, summary: str) -> str:
    """Return a stable source-scoped identity for one feed entry."""
    raw_id = str(getattr(entry, "id", "") or getattr(entry, "guid", "")).strip()
    normalized_url = urldefrag(url.strip())[0]
    basis = raw_id or normalized_url or f"{title.strip()}\n{summary.strip()}"
    return hashlib.sha256(f"{name}\0{basis}".encode()).hexdigest()


def fetch_all(
    sources: list[dict], timeout: int = 15
) -> list[NewsItem]:
    """Fetch RSS feeds from all sources concurrently (legacy: no report)."""
    return fetch_all_with_report(sources, timeout=timeout).items


def fetch_all_with_report(
    sources: list[dict], timeout: int = 15
) -> FetchBatch:
    """Fetch RSS feeds and retain the result for each configured source."""
    if not sources:
        return FetchBatch()

    indexed_results: list[SourceFetchResult | None] = [None] * len(sources)

    with ThreadPoolExecutor(max_workers=min(len(sources), 8)) as executor:
        futures = {
            executor.submit(_fetch_source, source["name"], source["url"], timeout): index
            for index, source in enumerate(sources)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                indexed_results[index] = future.result()
            except Exception as e:
                logger.warning(redact(f"Unexpected error in fetch future: {e}"))
                indexed_results[index] = SourceFetchResult(
                    name=sources[index]["name"],
                    status="parse_error",
                    error=redact(str(e)),
                )

    source_results = [result for result in indexed_results if result is not None]
    for result in source_results:
        result.items.sort(key=_published_sort_key, reverse=True)

    all_items = [
        source.items[position]
        for position in range(max((len(source.items) for source in source_results), default=0))
        for source in source_results
        if position < len(source.items)
    ]

    logger.info(
        f"Total fetched: {len(all_items)} items from {len(sources)} sources"
    )
    return FetchBatch(items=all_items, sources=source_results)


def _published_sort_key(item: NewsItem) -> float:
    published_at = item.published_at
    if published_at is None:
        return float("-inf")
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return published_at.timestamp()
