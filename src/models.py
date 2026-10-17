"""Data models for AI news pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NewsItem:
    """Raw news item fetched from an RSS feed."""
    title: str
    url: str
    summary: str
    source: str
    published_at: datetime | None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    item_id: str = ""


@dataclass
class EvaluatedItem:
    """News item after AI evaluation, summarization, and ranking."""
    title: str
    url: str
    source: str
    chinese_summary: str
    importance: int
    keywords: list[str]
    published_at: datetime | None
